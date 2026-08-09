"""Weekly class schedule (read-only — data owned by seed_schedule.py)."""

from fastapi import APIRouter, Depends
from manabi_core.models import Course, ScheduleBlock, User
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.api.courses import canvas_course_url
from manabi_server.db import get_db
from manabi_server.security import get_default_user

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


class BlockOut(BaseModel):
    id: int
    course_id: int
    code: str
    name: str
    accent_color: str | None
    day_of_week: int
    start_minute: int
    end_minute: int
    location: str | None


class UnscheduledOut(BaseModel):
    course_id: int
    code: str
    name: str
    instructor: str | None
    accent_color: str | None
    canvas_url: str | None


class ScheduleOut(BaseModel):
    blocks: list[BlockOut]
    unscheduled: list[UnscheduledOut]


@router.get("")
async def get_schedule(
    user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> ScheduleOut:
    courses = (
        (
            await db.execute(
                select(Course)
                .where(Course.user_id == user.id, Course.archived_at.is_(None))
                .order_by(Course.position)
            )
        )
        .scalars()
        .all()
    )
    by_id = {c.id: c for c in courses}
    blocks = (
        (
            await db.execute(
                select(ScheduleBlock)
                .where(ScheduleBlock.course_id.in_(by_id.keys()))
                .order_by(ScheduleBlock.day_of_week, ScheduleBlock.start_minute)
            )
        )
        .scalars()
        .all()
    )
    scheduled_ids = {b.course_id for b in blocks}
    return ScheduleOut(
        blocks=[
            BlockOut(
                id=b.id,
                course_id=b.course_id,
                code=by_id[b.course_id].code,
                name=by_id[b.course_id].name,
                accent_color=by_id[b.course_id].accent_color,
                day_of_week=b.day_of_week,
                start_minute=b.start_minute,
                end_minute=b.end_minute,
                location=b.location,
            )
            for b in blocks
        ],
        unscheduled=[
            UnscheduledOut(
                course_id=c.id,
                code=c.code,
                name=c.name,
                instructor=c.instructor,
                accent_color=c.accent_color,
                canvas_url=canvas_course_url(c.canvas_course_id),
            )
            for c in courses
            # Only courses that are part of this term's plan (have a Canvas
            # mapping) but no fixed slot — e.g. thesis. Plain local courses
            # without schedule data stay off the schedule page.
            if c.id not in scheduled_ids and c.canvas_course_id
        ],
    )
