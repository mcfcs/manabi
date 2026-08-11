"""Per-module chatbot: threads + messages, answers generated on the gpu queue.

Answers are grounded in module materials (retrieval + citations) whenever the
materials cover the question; otherwise the assistant explicitly says so and
may answer from general knowledge, clearly flagged."""

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from manabi_core.models import (
    ChatMessage,
    ChatRole,
    ChatThread,
    Course,
    Document,
    Job,
    JobQueue,
    Module,
    Note,
    SpeechClip,
    User,
)
from manabi_core.retrieval import retrieve
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.api.modules import get_owned_module
from manabi_server.db import get_db
from manabi_server.jobs.queue import CHAT_ANSWER_TASK, SPEAK_TEXT_TASK, defer_task
from manabi_server.security import get_default_user, require_csrf

router = APIRouter(prefix="/api", tags=["chat"])


class ThreadOut(BaseModel):
    id: int
    title: str
    teacher_mode: bool
    strict_grounding: bool  # False = material + free reasoning
    # None = all module materials of that kind; [] = none of that kind
    scope_document_ids: list[int] | None
    scope_note_ids: list[int] | None
    # Viewer-originated "discussion": the passage this thread is about.
    source_document_id: int | None
    source_page: int | None
    source_quote: str | None
    created_at: datetime


def _thread_out(t: ChatThread) -> ThreadOut:
    return ThreadOut(
        id=t.id,
        title=t.title,
        teacher_mode=t.teacher_mode,
        strict_grounding=t.strict_grounding,
        scope_document_ids=t.scope_document_ids,
        scope_note_ids=t.scope_note_ids,
        source_document_id=t.source_document_id,
        source_page=t.source_page,
        source_quote=t.source_quote,
        created_at=t.created_at,
    )


class MessageOut(BaseModel):
    id: int
    role: ChatRole
    content: str
    grounded: bool
    general_knowledge: bool
    citations: list | None
    has_audio: bool = False
    audio_id: int | None = None  # cache-buster; changes if re-synthesized
    created_at: datetime


class MessageIn(BaseModel):
    content: str


async def _get_owned_thread(
    thread_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> ChatThread:
    thread = (
        await db.execute(
            select(ChatThread)
            .join(Module, Module.id == ChatThread.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(ChatThread.id == thread_id, Course.user_id == user.id)
        )
    ).scalar_one_or_none()
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


@router.get("/modules/{module_id}/chat/threads")
async def list_threads(
    module: Module = Depends(get_owned_module), db: AsyncSession = Depends(get_db)
) -> list[ThreadOut]:
    threads = (
        (
            await db.execute(
                select(ChatThread)
                .where(ChatThread.module_id == module.id)
                .order_by(ChatThread.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_thread_out(t) for t in threads]


@router.post("/modules/{module_id}/chat/threads", dependencies=[Depends(require_csrf)])
async def create_thread(
    module: Module = Depends(get_owned_module), db: AsyncSession = Depends(get_db)
) -> ThreadOut:
    thread = ChatThread(module_id=module.id, title="New conversation")
    db.add(thread)
    await db.commit()
    return _thread_out(thread)


class ThreadPatch(BaseModel):
    teacher_mode: bool | None = None
    strict_grounding: bool | None = None
    title: str | None = None
    # Omitted field = unchanged; explicit null = back to "all" (model_fields_set
    # distinguishes the two).
    scope_document_ids: list[int] | None = None
    scope_note_ids: list[int] | None = None


@router.patch("/chat/threads/{thread_id}", dependencies=[Depends(require_csrf)])
async def update_thread(
    data: ThreadPatch,
    thread: ChatThread = Depends(_get_owned_thread),
    db: AsyncSession = Depends(get_db),
) -> ThreadOut:
    if data.teacher_mode is not None:
        thread.teacher_mode = data.teacher_mode
    if data.strict_grounding is not None:
        thread.strict_grounding = data.strict_grounding
    if data.title is not None and data.title.strip():
        thread.title = data.title.strip()[:255]
    if "scope_document_ids" in data.model_fields_set:
        if data.scope_document_ids:
            valid = set(
                (
                    await db.execute(
                        select(Document.id).where(
                            Document.module_id == thread.module_id,
                            Document.deleted_at.is_(None),
                        )
                    )
                ).scalars()
            )
            if not set(data.scope_document_ids) <= valid:
                raise HTTPException(
                    status_code=422, detail="Document not in this module"
                )
        thread.scope_document_ids = data.scope_document_ids
    if "scope_note_ids" in data.model_fields_set:
        if data.scope_note_ids:
            valid = set(
                (
                    await db.execute(
                        select(Note.id).where(Note.module_id == thread.module_id)
                    )
                ).scalars()
            )
            if not set(data.scope_note_ids) <= valid:
                raise HTTPException(status_code=422, detail="Note not in this module")
        thread.scope_note_ids = data.scope_note_ids
    await db.commit()
    return _thread_out(thread)


@router.delete("/chat/threads/{thread_id}", dependencies=[Depends(require_csrf)])
async def delete_thread(
    thread: ChatThread = Depends(_get_owned_thread), db: AsyncSession = Depends(get_db)
) -> dict:
    await db.delete(thread)
    await db.commit()
    return {"ok": True}


# ── Viewer discussions: source-anchored threads about a document passage ──


async def _owned_document(
    document_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> Document:
    doc = (
        await db.execute(
            select(Document)
            .join(Module, Module.id == Document.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(Document.id == document_id, Course.user_id == user.id)
        )
    ).scalar_one_or_none()
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


class DiscussIn(BaseModel):
    quote: str
    page: int | None = None


@router.get("/documents/{document_id}/threads")
async def list_document_threads(
    doc: Document = Depends(_owned_document), db: AsyncSession = Depends(get_db)
) -> list[ThreadOut]:
    """Viewer-originated discussions about this document, newest first."""
    rows = (
        (
            await db.execute(
                select(ChatThread)
                .where(ChatThread.source_document_id == doc.id)
                .order_by(ChatThread.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_thread_out(t) for t in rows]


@router.post("/documents/{document_id}/discuss", dependencies=[Depends(require_csrf)])
async def discuss_document(
    data: DiscussIn,
    doc: Document = Depends(_owned_document),
    db: AsyncSession = Depends(get_db),
) -> ThreadOut:
    """Open a Steven-taught, reasoning-mode thread anchored to a passage. The
    caller then posts the seed question via the normal messages endpoint."""
    quote = data.quote.strip()[:2000]
    title = (quote[:60] + "…") if len(quote) > 60 else (quote or "Discussion")
    thread = ChatThread(
        module_id=doc.module_id,
        title=title,
        teacher_mode=True,
        strict_grounding=False,  # explaining a passage often needs reasoning
        # Focus retrieval on the document the passage came from so the quoted
        # text is actually found (module-wide search can miss one page).
        scope_document_ids=[doc.id],
        source_document_id=doc.id,
        source_page=data.page,
        source_quote=quote or None,
    )
    db.add(thread)
    await db.commit()
    return _thread_out(thread)


@router.get("/chat/threads/{thread_id}/messages")
async def list_messages(
    thread: ChatThread = Depends(_get_owned_thread), db: AsyncSession = Depends(get_db)
) -> list[MessageOut]:
    rows = (
        await db.execute(
            select(ChatMessage, SpeechClip.id)
            .outerjoin(SpeechClip, SpeechClip.chat_message_id == ChatMessage.id)
            .where(ChatMessage.thread_id == thread.id)
            .order_by(ChatMessage.id)
        )
    ).all()
    return [
        MessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            grounded=m.grounded,
            general_knowledge=m.general_knowledge,
            citations=m.citations,
            has_audio=clip_id is not None,
            audio_id=clip_id,
            created_at=m.created_at,
        )
        for m, clip_id in rows
    ]


@router.post(
    "/chat/threads/{thread_id}/messages", dependencies=[Depends(require_csrf)]
)
async def post_message(
    data: MessageIn,
    thread: ChatThread = Depends(_get_owned_thread),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from manabi_core.models import JobStatus

    from manabi_server.processing.embedding import embed_texts

    content = data.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Message is empty")

    # One question in flight per THREAD (not per module) — so a viewer
    # discussion isn't blocked by the module Chat tab still answering.
    in_flight = (
        await db.execute(
            select(Job).where(
                Job.job_type == "chat_answer",
                Job.payload["thread_id"].as_string() == str(thread.id),
                Job.status.in_([JobStatus.queued, JobStatus.running]),
            )
        )
    ).scalar_one_or_none()
    if in_flight is not None:
        raise HTTPException(status_code=409, detail="Still answering the previous question")

    message = ChatMessage(thread_id=thread.id, role=ChatRole.user, content=content)
    db.add(message)
    if thread.title == "New conversation":
        thread.title = content[:80]
    await db.flush()

    # Retrieval happens here (app server owns the embedding model)
    if thread.scope_document_ids == []:
        hits = []  # documents excluded from scope — skip retrieval entirely
    else:
        vec = (await asyncio.to_thread(embed_texts, [content], is_query=True))[0]
        hits = await retrieve(
            db,
            [thread.module_id],
            vec,
            content,
            k=5,
            document_ids=thread.scope_document_ids,
        )

    job = Job(
        user_id=user.id,
        job_type="chat_answer",
        queue=JobQueue.gpu,
        payload={"thread_id": thread.id},
        module_id=thread.module_id,
    )
    db.add(job)
    await db.flush()
    job.procrastinate_job_id = await defer_task(
        CHAT_ANSWER_TASK,
        "gpu",
        job_id=job.id,
        thread_id=thread.id,
        chunk_ids=[h.id for h in hits],
    )
    await db.commit()
    return {"job_id": job.id, "message_id": message.id}


# ── Voice: spoken replies + voice input ───────────────────────────────────


async def _get_owned_message(
    message_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> ChatMessage:
    message = (
        await db.execute(
            select(ChatMessage)
            .join(ChatThread, ChatThread.id == ChatMessage.thread_id)
            .join(Module, Module.id == ChatThread.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(ChatMessage.id == message_id, Course.user_id == user.id)
        )
    ).scalar_one_or_none()
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return message


@router.post("/chat/messages/{message_id}/speak", dependencies=[Depends(require_csrf)])
async def speak_message(
    message: ChatMessage = Depends(_get_owned_message),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    existing = (
        await db.execute(
            select(SpeechClip.id).where(SpeechClip.chat_message_id == message.id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {"ready": True}
    job = Job(user_id=user.id, job_type="speak_text", queue=JobQueue.gpu)
    db.add(job)
    await db.flush()
    job.procrastinate_job_id = await defer_task(
        SPEAK_TEXT_TASK, "gpu", job_id=job.id, message_id=message.id
    )
    await db.commit()
    return {"ready": False, "job_id": job.id}


@router.get("/chat/messages/{message_id}/audio")
async def message_audio(
    message: ChatMessage = Depends(_get_owned_message),
    db: AsyncSession = Depends(get_db),
) -> Response:
    clip = (
        await db.execute(
            select(SpeechClip).where(SpeechClip.chat_message_id == message.id)
        )
    ).scalar_one_or_none()
    if clip is None:
        raise HTTPException(status_code=404, detail="Not synthesized yet")
    return Response(
        content=clip.audio,
        media_type=clip.mime,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.post(
    "/chat/threads/{thread_id}/voice-message", dependencies=[Depends(require_csrf)]
)
async def post_voice_message(
    audio: UploadFile = File(...),  # noqa: B008 — FastAPI idiom
    thread: ChatThread = Depends(_get_owned_thread),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Voice note → transcript → the normal chat flow. Turn-based, not live:
    STT (~2-6s) + answer generation, staged progress shown by the UI."""
    from manabi_server.processing.stt import transcribe

    raw = await audio.read()
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Recording too large")
    suffix = ".webm" if "webm" in (audio.content_type or "") else ".ogg"
    transcript = await transcribe(raw, suffix)
    if not transcript.strip():
        raise HTTPException(status_code=422, detail="Could not hear anything in that")
    result = await post_message(MessageIn(content=transcript), thread, user, db)
    return {**result, "transcript": transcript}
