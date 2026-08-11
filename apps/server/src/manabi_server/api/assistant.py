"""General "Manabi AI" assistant — module-less chat threads (module_id NULL),
owned by user_id. PATCH / DELETE / messages / voice reuse the chat router
(they're thread-id based), so only list + create live here.
"""

from fastapi import APIRouter, Depends
from manabi_core.models import (
    ChatMessage,
    ChatRole,
    ChatThread,
    Course,
    Job,
    JobQueue,
    JobStatus,
    Module,
    User,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.api.chat import ThreadOut, _thread_out
from manabi_server.db import get_db
from manabi_server.jobs.queue import DAILY_BRIEFING_TASK, defer_task
from manabi_server.security import get_default_user, require_csrf
from manabi_server.timeutil import today_manila

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class AssistantModuleOut(BaseModel):
    id: int
    title: str
    course_id: int
    course_code: str
    accent_color: str | None


@router.get("/modules")
async def list_assistant_modules(
    user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> list[AssistantModuleOut]:
    """The user's real modules (for the cross-module material picker)."""
    rows = (
        await db.execute(
            select(Module.id, Module.title, Course.id, Course.code, Course.accent_color)
            .join(Course, Course.id == Module.course_id)
            .where(Course.user_id == user.id, Module.is_general.is_(False))
            .order_by(Course.code, Module.position)
        )
    ).all()
    return [
        AssistantModuleOut(
            id=r[0], title=r[1], course_id=r[2], course_code=r[3], accent_color=r[4]
        )
        for r in rows
    ]


@router.get("/threads")
async def list_assistant_threads(
    user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> list[ThreadOut]:
    threads = (
        (
            await db.execute(
                select(ChatThread)
                .where(ChatThread.user_id == user.id, ChatThread.module_id.is_(None))
                .order_by(ChatThread.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_thread_out(t) for t in threads]


@router.post("/threads", dependencies=[Depends(require_csrf)])
async def create_assistant_thread(
    user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> ThreadOut:
    thread = ChatThread(
        user_id=user.id,
        module_id=None,
        title="New conversation",
        teacher_mode=True,  # Steven Starphase is the assistant's default voice
        strict_grounding=False,  # the general assistant answers freely
    )
    db.add(thread)
    await db.commit()
    return _thread_out(thread)


class BriefingOut(BaseModel):
    thread_id: int
    message_id: int | None = None
    job_id: int | None = None
    generating: bool


@router.post("/briefing", dependencies=[Depends(require_csrf)])
async def ensure_daily_briefing(
    user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> BriefingOut:
    """Ensure today's (Manila) morning briefing exists. Steven posts a "good day"
    digest as his first assistant message in a per-day thread. Idempotent: called
    on assistant open, it generates ONCE per Manila day — repeat calls the same
    day return the same thread with no new job."""
    # Lazy imports (mirror api/chat.py) to avoid app-startup import cycles.
    from manabi_server.api.settings import get_app_settings
    from manabi_server.services.context import build_personal_context

    today = today_manila()
    settings = await get_app_settings(db)
    title = f"{today.strftime('%b')} {today.day} — Morning briefing"

    thread = (
        await db.execute(
            select(ChatThread).where(
                ChatThread.user_id == user.id,
                ChatThread.module_id.is_(None),
                ChatThread.title == title,
            )
        )
    ).scalar_one_or_none()

    # Already produced today → return the cached thread + its greeting, no job.
    if settings.last_briefing_date == today and thread is not None:
        msg_id = (
            await db.execute(
                select(ChatMessage.id)
                .where(
                    ChatMessage.thread_id == thread.id,
                    ChatMessage.role == ChatRole.assistant,
                )
                .order_by(ChatMessage.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        return BriefingOut(thread_id=thread.id, message_id=msg_id, generating=False)

    # A briefing job already in flight for today's thread → don't double-generate.
    if thread is not None:
        in_flight = (
            await db.execute(
                select(Job).where(
                    Job.job_type == "daily_briefing",
                    Job.payload["thread_id"].as_string() == str(thread.id),
                    Job.status.in_([JobStatus.queued, JobStatus.running]),
                )
            )
        ).scalar_one_or_none()
        if in_flight is not None:
            return BriefingOut(
                thread_id=thread.id, job_id=in_flight.id, generating=True
            )

    if thread is None:
        thread = ChatThread(
            user_id=user.id,
            module_id=None,
            title=title,
            teacher_mode=True,  # Steven reads his briefing aloud
            strict_grounding=False,
        )
        db.add(thread)
        await db.flush()

    personal_context = await build_personal_context(db, user)
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
        model=settings.general_chat_model,
    )
    # Flip the once-per-day gate in the same commit that defers (closes the race).
    settings.last_briefing_date = today
    await db.commit()
    return BriefingOut(thread_id=thread.id, job_id=job.id, generating=True)
