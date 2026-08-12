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
    JobStatus,
    Module,
    Note,
    SpeechClip,
    User,
)
from manabi_core.retrieval import retrieve, retrieve_relevant
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.api.modules import get_owned_module
from manabi_server.db import get_db
from manabi_server.jobs.queue import (
    CHAT_ANSWER_TASK,
    DAILY_BRIEFING_TASK,
    SPEAK_TEXT_TASK,
    defer_task,
)
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
    # General ("Manabi AI") assistant fields: module_id is None for general
    # threads; scope_module_ids/auto_materials drive cross-module material scope.
    module_id: int | None = None
    is_general: bool = False
    scope_module_ids: list[int] | None = None
    auto_materials: bool = False
    model_override: str | None = None
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
        module_id=t.module_id,
        is_general=t.module_id is None,
        scope_module_ids=t.scope_module_ids,
        auto_materials=t.auto_materials,
        model_override=t.model_override,
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
    action: dict | None = None  # Steven's proposed action (create_task/event)
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
    # Ownership by user_id — works for both module and general (module_id NULL)
    # threads without a Module join.
    thread = (
        await db.execute(
            select(ChatThread).where(
                ChatThread.id == thread_id, ChatThread.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


async def _all_user_module_ids(db: AsyncSession, user: User) -> list[int]:
    """Every real (non course-files) module the user owns — the general
    assistant's auto-scan scope."""
    return list(
        (
            await db.execute(
                select(Module.id)
                .join(Course, Course.id == Module.course_id)
                .where(Course.user_id == user.id, Module.is_general.is_(False))
            )
        ).scalars()
    )


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
    module: Module = Depends(get_owned_module),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> ThreadOut:
    thread = ChatThread(
        user_id=user.id, module_id=module.id, title="New conversation"
    )
    db.add(thread)
    await db.commit()
    return _thread_out(thread)


class ThreadAllOut(BaseModel):
    id: int
    title: str
    teacher_mode: bool
    is_general: bool
    module_id: int | None
    module_title: str | None
    course_id: int | None
    course_code: str | None
    created_at: datetime


@router.get("/chat/threads/all")
async def list_all_threads(
    user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> list[ThreadAllOut]:
    """Every thread the user owns (module + general), for the assistant's
    "Module chats" section. outerjoin so general threads (no module) appear."""
    rows = (
        await db.execute(
            select(
                ChatThread.id,
                ChatThread.title,
                ChatThread.teacher_mode,
                ChatThread.module_id,
                Module.title,
                Course.id,
                Course.code,
                ChatThread.created_at,
            )
            .outerjoin(Module, Module.id == ChatThread.module_id)
            .outerjoin(Course, Course.id == Module.course_id)
            .where(ChatThread.user_id == user.id)
            .order_by(ChatThread.id.desc())
        )
    ).all()
    return [
        ThreadAllOut(
            id=r[0],
            title=r[1],
            teacher_mode=r[2],
            is_general=r[3] is None,
            module_id=r[3],
            module_title=r[4],
            course_id=r[5],
            course_code=r[6],
            created_at=r[7],
        )
        for r in rows
    ]


class ThreadPatch(BaseModel):
    teacher_mode: bool | None = None
    strict_grounding: bool | None = None
    title: str | None = None
    # Omitted field = unchanged; explicit null = back to "all" (model_fields_set
    # distinguishes the two).
    scope_document_ids: list[int] | None = None
    scope_note_ids: list[int] | None = None
    # General-assistant material scope + auto-scan toggle.
    scope_module_ids: list[int] | None = None
    auto_materials: bool | None = None
    # Per-chat model (general threads only). Explicit null = back to the default.
    model_override: str | None = None


@router.patch("/chat/threads/{thread_id}", dependencies=[Depends(require_csrf)])
async def update_thread(
    data: ThreadPatch,
    thread: ChatThread = Depends(_get_owned_thread),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> ThreadOut:
    if data.teacher_mode is not None:
        thread.teacher_mode = data.teacher_mode
    if data.strict_grounding is not None:
        thread.strict_grounding = data.strict_grounding
    if data.title is not None and data.title.strip():
        thread.title = data.title.strip()[:255]
    if data.auto_materials is not None:
        thread.auto_materials = data.auto_materials
    if "model_override" in data.model_fields_set:
        # Only general threads carry a per-chat model; empty string clears it.
        thread.model_override = (data.model_override or None) if thread.module_id is None else None
    if "scope_module_ids" in data.model_fields_set:
        if data.scope_module_ids:
            valid_mods = set(await _all_user_module_ids(db, user))
            if not set(data.scope_module_ids) <= valid_mods:
                raise HTTPException(status_code=422, detail="Module not owned by user")
        thread.scope_module_ids = data.scope_module_ids
    # Per-module document/note scope only applies to a module thread.
    if thread.module_id is not None and "scope_document_ids" in data.model_fields_set:
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
    if thread.module_id is not None and "scope_note_ids" in data.model_fields_set:
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
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> ThreadOut:
    """Open a Steven-taught, reasoning-mode thread anchored to a passage. The
    caller then posts the seed question via the normal messages endpoint."""
    quote = data.quote.strip()[:2000]
    title = (quote[:60] + "…") if len(quote) > 60 else (quote or "Discussion")
    thread = ChatThread(
        user_id=user.id,
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
            action=m.action,
            has_audio=clip_id is not None,
            audio_id=clip_id,
            created_at=m.created_at,
        )
        for m, clip_id in rows
    ]


async def _answer_in_flight(db: AsyncSession, thread_id: int) -> Job | None:
    """A chat_answer / daily_briefing job already generating for this thread."""
    return (
        await db.execute(
            select(Job).where(
                Job.job_type.in_(["chat_answer", "daily_briefing"]),
                Job.payload["thread_id"].as_string() == str(thread_id),
                Job.status.in_([JobStatus.queued, JobStatus.running]),
            )
        )
    ).scalar_one_or_none()


async def _dispatch_answer(
    db: AsyncSession, user: User, thread: ChatThread, content: str
) -> int:
    """Retrieve context for `content` and defer a chat_answer job; returns the
    Job id. Shared by post_message (new question) and regenerate (re-answer the
    same question). Retrieval runs here — the app server owns the embed model."""
    from manabi_server.processing.embedding import embed_texts

    personal_context: str | None = None
    model: str | None = None

    async def _embed() -> list[float]:
        return (await asyncio.to_thread(embed_texts, [content], is_query=True))[0]

    if thread.module_id is not None:
        # ── Module thread (behavior unchanged) ──
        if thread.scope_document_ids == []:
            chunk_ids: list[int] = []  # documents excluded from scope
        else:
            hits = await retrieve(
                db, [thread.module_id], await _embed(), content, k=5,
                document_ids=thread.scope_document_ids,
            )
            chunk_ids = [h.id for h in hits]
    else:
        # ── General assistant thread ──
        from manabi_server.api.settings import get_app_settings
        from manabi_server.services.context import build_personal_context

        personal_context = await build_personal_context(db, user)
        # Per-chat override wins; else the global default; else the node default.
        model = thread.model_override or (await get_app_settings(db)).general_chat_model
        if thread.scope_module_ids:  # manual cross-module scope wins (no gate)
            hits = await retrieve(db, list(thread.scope_module_ids), await _embed(), content, k=6)
            chunk_ids = [h.id for h in hits]
        elif thread.auto_materials:  # auto-scan, gated by relevance
            hits, ok = await retrieve_relevant(
                db, await _all_user_module_ids(db, user), await _embed(), content
            )
            chunk_ids = [h.id for h in hits] if ok else []
        else:  # default: personal + general knowledge, no material scan
            chunk_ids = []

    job = Job(
        user_id=user.id,
        job_type="chat_answer",
        queue=JobQueue.gpu,
        payload={"thread_id": thread.id},
        module_id=thread.module_id,
    )
    db.add(job)
    await db.flush()
    # Extra kwargs only for general threads → module chat is provably unaffected.
    extra = (
        {}
        if thread.module_id is not None
        else {"personal_context": personal_context, "model": model}
    )
    job.procrastinate_job_id = await defer_task(
        CHAT_ANSWER_TASK,
        "gpu",
        job_id=job.id,
        thread_id=thread.id,
        chunk_ids=chunk_ids,
        **extra,
    )
    return job.id


@router.post(
    "/chat/threads/{thread_id}/messages", dependencies=[Depends(require_csrf)]
)
async def post_message(
    data: MessageIn,
    thread: ChatThread = Depends(_get_owned_thread),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    content = data.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Message is empty")
    # One question in flight per THREAD (not per module).
    if await _answer_in_flight(db, thread.id) is not None:
        raise HTTPException(status_code=409, detail="Still answering the previous question")

    message = ChatMessage(thread_id=thread.id, role=ChatRole.user, content=content)
    db.add(message)
    if thread.title == "New conversation":
        thread.title = content[:80]
    await db.flush()
    job_id = await _dispatch_answer(db, user, thread, content)
    await db.commit()
    return {"job_id": job_id, "message_id": message.id}


# ── Voice: spoken replies + voice input ───────────────────────────────────


async def _get_owned_message(
    message_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> ChatMessage:
    # User-scoped (not via Module) so messages in general threads (module_id
    # NULL) resolve too — an inner Module join would drop them.
    message = (
        await db.execute(
            select(ChatMessage)
            .join(ChatThread, ChatThread.id == ChatMessage.thread_id)
            .where(ChatMessage.id == message_id, ChatThread.user_id == user.id)
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


@router.delete("/chat/messages/{message_id}", dependencies=[Depends(require_csrf)])
async def delete_message(
    message: ChatMessage = Depends(_get_owned_message),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a single chat message (its audio clip cascades)."""
    await db.delete(message)
    await db.commit()
    return {"ok": True}


@router.post(
    "/chat/messages/{message_id}/regenerate", dependencies=[Depends(require_csrf)]
)
async def regenerate_message(
    message: ChatMessage = Depends(_get_owned_message),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Regenerate an assistant reply: delete it and re-answer the same question
    (or re-run the daily briefing if it has no preceding question)."""
    if message.role != ChatRole.assistant:
        raise HTTPException(
            status_code=422, detail="Only Steven's replies can be regenerated"
        )
    thread = (
        await db.execute(select(ChatThread).where(ChatThread.id == message.thread_id))
    ).scalar_one()
    if await _answer_in_flight(db, thread.id) is not None:
        raise HTTPException(status_code=409, detail="Still answering — try again in a moment")

    # the question this reply answered = the last user message before it
    last_user = (
        await db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.thread_id == thread.id,
                ChatMessage.role == ChatRole.user,
                ChatMessage.id < message.id,
            )
            .order_by(ChatMessage.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    await db.delete(message)  # drop the old reply (its clip cascades)
    await db.flush()

    if last_user is not None:
        job_id = await _dispatch_answer(db, user, thread, last_user.content)
    elif thread.module_id is None:
        # No question before it → the daily briefing. Rebuild + re-run it.
        from manabi_server.api.settings import get_app_settings
        from manabi_server.services.context import build_personal_context

        personal_context = await build_personal_context(db, user)
        model = (await get_app_settings(db)).general_chat_model
        job = Job(
            user_id=user.id,
            job_type="daily_briefing",
            queue=JobQueue.gpu,
            payload={"thread_id": thread.id},
        )
        db.add(job)
        await db.flush()
        job.procrastinate_job_id = await defer_task(
            DAILY_BRIEFING_TASK,
            "gpu",
            job_id=job.id,
            thread_id=thread.id,
            personal_context=personal_context,
            model=model,
        )
        job_id = job.id
    else:
        raise HTTPException(status_code=422, detail="Nothing to regenerate")
    await db.commit()
    return {"job_id": job_id}


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
