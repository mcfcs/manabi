"""Named schedules with flexible entries: course-linked or free-label,
timed or TBA. Seeded class blocks live in the default "Class schedule"."""

from fastapi import APIRouter, Depends, HTTPException
from manabi_core.models import Course, Schedule, ScheduleBlock, User
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.api.courses import canvas_course_url
from manabi_server.db import get_db
from manabi_server.security import get_default_user, require_csrf

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


class EntryOut(BaseModel):
    id: int
    schedule_id: int
    course_id: int | None
    code: str  # course code or free label
    name: str | None
    instructor: str | None
    accent_color: str | None
    day_of_week: int | None  # NULL = TBA
    start_minute: int | None
    end_minute: int | None
    location: str | None
    meeting_url: str | None
    canvas_url: str | None


class ScheduleGroupOut(BaseModel):
    id: int
    title: str
    position: int
    entries: list[EntryOut]


class ScheduleOut(BaseModel):
    schedules: list[ScheduleGroupOut]


class ScheduleIn(BaseModel):
    title: str


class EntryIn(BaseModel):
    course_id: int | None = None
    label: str | None = None
    color: str | None = None
    day_of_week: int | None = None
    start_minute: int | None = None
    end_minute: int | None = None
    location: str | None = None


def _entry_out(b: ScheduleBlock, course: Course | None) -> EntryOut:
    return EntryOut(
        id=b.id,
        schedule_id=b.schedule_id,
        course_id=b.course_id,
        code=course.code if course else (b.label or "—"),
        name=course.name if course else None,
        instructor=course.instructor if course else None,
        accent_color=(course.accent_color if course else None) or b.color,
        day_of_week=b.day_of_week,
        start_minute=b.start_minute,
        end_minute=b.end_minute,
        location=b.location,
        meeting_url=course.meeting_url if course else None,
        canvas_url=canvas_course_url(course.canvas_course_id) if course else None,
    )


@router.get("")
async def get_schedule(
    user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> ScheduleOut:
    courses = {
        c.id: c
        for c in (
            await db.execute(select(Course).where(Course.user_id == user.id))
        ).scalars()
    }
    schedules = (
        (await db.execute(select(Schedule).order_by(Schedule.position, Schedule.id)))
        .scalars()
        .all()
    )
    blocks = (
        (
            await db.execute(
                select(ScheduleBlock).order_by(
                    ScheduleBlock.day_of_week.nulls_last(),
                    ScheduleBlock.start_minute.nulls_last(),
                )
            )
        )
        .scalars()
        .all()
    )
    by_schedule: dict[int, list[EntryOut]] = {}
    for b in blocks:
        by_schedule.setdefault(b.schedule_id, []).append(
            _entry_out(b, courses.get(b.course_id) if b.course_id else None)
        )
    return ScheduleOut(
        schedules=[
            ScheduleGroupOut(
                id=s.id,
                title=s.title,
                position=s.position,
                entries=by_schedule.get(s.id, []),
            )
            for s in schedules
        ]
    )


@router.post("", dependencies=[Depends(require_csrf)])
async def create_schedule(
    data: ScheduleIn, db: AsyncSession = Depends(get_db)
) -> dict:
    if not data.title.strip():
        raise HTTPException(status_code=422, detail="Title required")
    max_pos = (
        await db.execute(select(func.coalesce(func.max(Schedule.position), -1)))
    ).scalar_one()
    sched = Schedule(title=data.title.strip(), position=max_pos + 1)
    db.add(sched)
    await db.commit()
    return {"id": sched.id, "title": sched.title}


@router.delete("/{schedule_id}", dependencies=[Depends(require_csrf)])
async def delete_schedule(schedule_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    sched = await db.get(Schedule, schedule_id)
    if sched is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    count = (
        await db.execute(select(func.count(Schedule.id)))
    ).scalar_one()
    if count <= 1:
        raise HTTPException(status_code=409, detail="Cannot delete the last schedule")
    await db.delete(sched)  # entries cascade
    await db.commit()
    return {"ok": True}


@router.post("/{schedule_id}/entries", dependencies=[Depends(require_csrf)])
async def create_entry(
    schedule_id: int,
    data: EntryIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> EntryOut:
    if await db.get(Schedule, schedule_id) is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    if data.course_id is None and not (data.label or "").strip():
        raise HTTPException(status_code=422, detail="Pick a course or enter a label")
    course = None
    if data.course_id is not None:
        course = await db.get(Course, data.course_id)
        if course is None or course.user_id != user.id:
            raise HTTPException(status_code=404, detail="Course not found")
    if (data.start_minute is None) != (data.end_minute is None) or (
        data.day_of_week is None and data.start_minute is not None
    ):
        raise HTTPException(
            status_code=422, detail="Set day + start + end together, or none (TBA)"
        )
    block = ScheduleBlock(
        schedule_id=schedule_id,
        course_id=data.course_id,
        label=(data.label or "").strip() or None,
        color=data.color,
        day_of_week=data.day_of_week,
        start_minute=data.start_minute,
        end_minute=data.end_minute,
        location=data.location,
    )
    db.add(block)
    await db.commit()
    return _entry_out(block, course)


@router.delete("/entries/{entry_id}", dependencies=[Depends(require_csrf)])
async def delete_entry(entry_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    block = await db.get(ScheduleBlock, entry_id)
    if block is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    await db.delete(block)
    await db.commit()
    return {"ok": True}
