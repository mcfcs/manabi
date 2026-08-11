"""General "Manabi AI" assistant — module-less chat threads (module_id NULL),
owned by user_id. PATCH / DELETE / messages / voice reuse the chat router
(they're thread-id based), so only list + create live here.
"""

from fastapi import APIRouter, Depends
from manabi_core.models import ChatThread, Course, Module, User
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.api.chat import ThreadOut, _thread_out
from manabi_server.db import get_db
from manabi_server.security import get_default_user, require_csrf

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
