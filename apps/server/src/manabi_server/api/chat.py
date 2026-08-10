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
    Job,
    JobQueue,
    Module,
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
    created_at: datetime


class MessageOut(BaseModel):
    id: int
    role: ChatRole
    content: str
    grounded: bool
    general_knowledge: bool
    citations: list | None
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
    return [
        ThreadOut(
            id=t.id,
            title=t.title,
            teacher_mode=t.teacher_mode,
            created_at=t.created_at,
        )
        for t in threads
    ]


@router.post("/modules/{module_id}/chat/threads", dependencies=[Depends(require_csrf)])
async def create_thread(
    module: Module = Depends(get_owned_module), db: AsyncSession = Depends(get_db)
) -> ThreadOut:
    thread = ChatThread(module_id=module.id, title="New conversation")
    db.add(thread)
    await db.commit()
    return ThreadOut(
        id=thread.id,
        title=thread.title,
        teacher_mode=thread.teacher_mode,
        created_at=thread.created_at,
    )


class ThreadPatch(BaseModel):
    teacher_mode: bool | None = None
    title: str | None = None


@router.patch("/chat/threads/{thread_id}", dependencies=[Depends(require_csrf)])
async def update_thread(
    data: ThreadPatch,
    thread: ChatThread = Depends(_get_owned_thread),
    db: AsyncSession = Depends(get_db),
) -> ThreadOut:
    if data.teacher_mode is not None:
        thread.teacher_mode = data.teacher_mode
    if data.title is not None and data.title.strip():
        thread.title = data.title.strip()[:255]
    await db.commit()
    return ThreadOut(
        id=thread.id,
        title=thread.title,
        teacher_mode=thread.teacher_mode,
        created_at=thread.created_at,
    )


@router.delete("/chat/threads/{thread_id}", dependencies=[Depends(require_csrf)])
async def delete_thread(
    thread: ChatThread = Depends(_get_owned_thread), db: AsyncSession = Depends(get_db)
) -> dict:
    await db.delete(thread)
    await db.commit()
    return {"ok": True}


@router.get("/chat/threads/{thread_id}/messages")
async def list_messages(
    thread: ChatThread = Depends(_get_owned_thread), db: AsyncSession = Depends(get_db)
) -> list[MessageOut]:
    messages = (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.thread_id == thread.id)
                .order_by(ChatMessage.id)
            )
        )
        .scalars()
        .all()
    )
    return [
        MessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            grounded=m.grounded,
            general_knowledge=m.general_knowledge,
            citations=m.citations,
            created_at=m.created_at,
        )
        for m in messages
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

    # one question in flight per thread
    in_flight = (
        await db.execute(
            select(Job).where(
                Job.job_type == "chat_answer",
                Job.module_id == thread.module_id,
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
    vec = (await asyncio.to_thread(embed_texts, [content], is_query=True))[0]
    hits = await retrieve(db, [thread.module_id], vec, content, k=5)

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
