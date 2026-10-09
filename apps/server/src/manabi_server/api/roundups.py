"""Class roundups: an evening note on what happened in each class meeting.

Writable for a past day at any time, for today from 8 PM (Manila), never for
a future day — the roundup is written once the classes are over. Shown on the
calendar, listed as a course's class log, and read by Steven's briefing."""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from manabi_core.models import ClassRoundup, Course, User
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.db import get_db
from manabi_server.security import get_default_user, require_csrf
from manabi_server.timeutil import now_manila

router = APIRouter(prefix="/api", tags=["roundups"])

ROUNDUP_OPENS_HOUR = 20  # 8 PM, Manila


def roundup_closed_reason(day: Date, now: datetime) -> str | None:
    """Why a roundup for `day` can't be written at `now` (Manila), or None."""
    today = now.date()
    if day > today:
        return "A roundup is written after the class, not before."
    if day == today and now.hour < ROUNDUP_OPENS_HOUR:
        return "Today's roundup opens at 8 PM."
    return None


class RoundupIn(BaseModel):
    course_id: int
    date: Date
    text: str = Field(max_length=10_000)


class RoundupOut(BaseModel):
    id: int
    course_id: int
    date: Date
    text: str
    updated_at: datetime


def roundup_out(r: ClassRoundup) -> RoundupOut:
    return RoundupOut(
        id=r.id, course_id=r.course_id, date=r.date, text=r.text, updated_at=r.updated_at
    )


async def _owned_course(db: AsyncSession, user: User, course_id: int) -> Course:
    course = await db.get(Course, course_id)
    if course is None or course.user_id != user.id:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


@router.put("/roundups", dependencies=[Depends(require_csrf)])
async def save_roundup(
    data: RoundupIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> RoundupOut | None:
    """Create, replace, or (with empty text) delete one class's roundup."""
    await _owned_course(db, user, data.course_id)
    closed = roundup_closed_reason(data.date, now_manila())
    if closed:
        raise HTTPException(status_code=409, detail=closed)
    row = (
        await db.execute(
            select(ClassRoundup).where(
                ClassRoundup.course_id == data.course_id, ClassRoundup.date == data.date
            )
        )
    ).scalar_one_or_none()
    text = data.text.strip()
    if not text:
        if row is not None:
            await db.delete(row)
            await db.commit()
        return None
    if row is None:
        row = ClassRoundup(course_id=data.course_id, date=data.date, text=text)
        db.add(row)
    else:
        row.text = text
    await db.commit()
    await db.refresh(row)
    return roundup_out(row)


@router.get("/courses/{course_id}/roundups")
async def course_roundups(
    course_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> list[RoundupOut]:
    """The course's class log, newest first."""
    await _owned_course(db, user, course_id)
    rows = (
        await db.execute(
            select(ClassRoundup)
            .where(ClassRoundup.course_id == course_id)
            .order_by(ClassRoundup.date.desc())
        )
    ).scalars()
    return [roundup_out(r) for r in rows]
