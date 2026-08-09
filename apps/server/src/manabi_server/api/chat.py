"""Per-module chatbot: threads + messages, answers generated on the gpu queue.

Answers are grounded in module materials (retrieval + citations) whenever the
materials cover the question; otherwise the assistant explicitly says so and
may answer from general knowledge, clearly flagged."""

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from manabi_core.models import (
    ChatMessage,
    ChatRole,
    ChatThread,
    Course,
    Job,
    JobQueue,
    Module,
    User,
)
from manabi_core.retrieval import retrieve
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.api.modules import get_owned_module
from manabi_server.db import get_db
from manabi_server.jobs.queue import CHAT_ANSWER_TASK, defer_task
from manabi_server.security import get_default_user, require_csrf

router = APIRouter(prefix="/api", tags=["chat"])


class ThreadOut(BaseModel):
    id: int
    title: str
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
    return [ThreadOut(id=t.id, title=t.title, created_at=t.created_at) for t in threads]


@router.post("/modules/{module_id}/chat/threads", dependencies=[Depends(require_csrf)])
async def create_thread(
    module: Module = Depends(get_owned_module), db: AsyncSession = Depends(get_db)
) -> ThreadOut:
    thread = ChatThread(module_id=module.id, title="New conversation")
    db.add(thread)
    await db.commit()
    return ThreadOut(id=thread.id, title=thread.title, created_at=thread.created_at)


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
    hits = await retrieve(db, [thread.module_id], vec, content, k=8)

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
