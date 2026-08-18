"""Calendar: month view (classes expanded from schedule_blocks + custom
events + cached Google events + sync/async day marks), event CRUD, marks
upsert, Google refresh, and .ics export."""

import calendar as calmod

# `Date` alias: models below have fields literally named `date`, which
# would shadow the type inside the class namespace during resolution.
from datetime import date as Date
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from manabi_core.models import (
    CalendarEvent,
    Course,
    DayMark,
    GcalEvent,
    Schedule,
    ScheduleBlock,
    StudyTask,
    User,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.api.settings import get_app_settings
from manabi_server.config import get_settings
from manabi_server.db import get_db
from manabi_server.security import get_default_user, require_csrf
from manabi_server.services.gcal import fetch_gcal
from manabi_server.services.ics_export import build_ics

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


class MeetingOut(BaseModel):
    date: Date
    course_id: int | None
    block_id: int  # source schedule block (used for RTO/WFH marks on labeled blocks)
    schedule_id: int  # which schedule group (Class schedule / Internship / …)
    schedule_title: str
    code: str
    accent_color: str | None
    start_minute: int
    end_minute: int
    location: str | None
    meeting_url: str | None


class EventOut(BaseModel):
    id: int
    title: str
    notes: str | None
    course_id: int | None
    date: Date  # occurrence date (repeating events expand per occurrence)
    start_minute: int | None
    end_minute: int | None
    repeat_weekly: bool
    repeat_until: Date | None


class GcalOut(BaseModel):
    date: Date
    title: str
    calendar: str | None
    start_minute: int | None
    end_minute: int | None
    location: str | None
    organizer: str | None
    attendees: list[dict] | None  # [{name, status}]
    my_status: str | None  # accepted | declined | tentative | needs-action


class MarkOut(BaseModel):
    date: Date
    course_id: int | None
    block_id: int | None
    mode: str
    note: str | None


class CalTaskOut(BaseModel):
    id: int
    date: Date
    title: str
    course_id: int | None
    course_code: str | None
    accent_color: str | None
    due_minute: int | None
    done: bool


class MonthOut(BaseModel):
    ym: str | None
    semester_start: Date
    semester_end: Date
    meetings: list[MeetingOut]
    events: list[EventOut]
    gcal: list[GcalOut]
    marks: list[MarkOut]
    tasks: list[CalTaskOut]
    gcal_configured: bool


class EventIn(BaseModel):
    title: str
    notes: str | None = None
    course_id: int | None = None
    date: Date
    start_minute: int | None = None
    end_minute: int | None = None
    repeat_weekly: bool = False
    repeat_until: Date | None = None


class EventPatch(BaseModel):
    title: str | None = None
    notes: str | None = None
    course_id: int | None = None
    date: Date | None = None
    start_minute: int | None = None
    end_minute: int | None = None
    repeat_weekly: bool | None = None
    repeat_until: Date | None = None


class MarkIn(BaseModel):
    date: Date
    course_id: int | None = None
    block_id: int | None = None  # set for a labeled block's RTO/WFH mark
    mode: str | None = None  # sync|async (classes) · rto|wfh (block) · None = delete
    note: str | None = None


def _parse_ym(ym: str) -> tuple[Date, Date]:
    try:
        year, month = int(ym[:4]), int(ym[5:7])
        first = Date(year, month, 1)
    except (ValueError, IndexError):
        raise HTTPException(status_code=422, detail="ym must be YYYY-MM") from None
    last = Date(year, month, calmod.monthrange(year, month)[1])
    return first, last


def _event_out(ev: CalendarEvent, occurrence: Date | None = None) -> EventOut:
    return EventOut(
        id=ev.id,
        title=ev.title,
        notes=ev.notes,
        course_id=ev.course_id,
        date=occurrence or ev.date,
        start_minute=ev.start_minute,
        end_minute=ev.end_minute,
        repeat_weekly=ev.repeat_weekly,
        repeat_until=ev.repeat_until,
    )


async def _range_data(
    db: AsyncSession, user: User, first: Date, last: Date, ym: str | None = None
) -> MonthOut:
    app = await get_app_settings(db)

    courses = {
        c.id: c
        for c in (
            await db.execute(
                select(Course).where(
                    Course.user_id == user.id, Course.archived_at.is_(None)
                )
            )
        ).scalars()
    }
    blocks = (
        (await db.execute(select(ScheduleBlock))).scalars().all()
    )
    schedule_titles = {
        s.id: s.title
        for s in (await db.execute(select(Schedule))).scalars().all()
    }

    # Classes + labeled entries: expand timed blocks over the range ∩ semester
    meetings: list[MeetingOut] = []
    day = max(first, app.semester_start)
    stop = min(last, app.semester_end)
    while day <= stop:
        for b in blocks:
            if b.day_of_week != day.weekday() or b.start_minute is None:
                continue
            c = courses.get(b.course_id) if b.course_id else None
            meetings.append(
                MeetingOut(
                    date=day,
                    course_id=c.id if c else None,
                    block_id=b.id,
                    schedule_id=b.schedule_id,
                    schedule_title=schedule_titles.get(b.schedule_id, "Schedule"),
                    code=c.code if c else (b.label or "—"),
                    accent_color=(c.accent_color if c else None) or b.color,
                    start_minute=b.start_minute,
                    end_minute=b.end_minute,
                    location=b.location,
                    meeting_url=c.meeting_url if c else None,
                )
            )
        day += timedelta(days=1)

    # Custom events: singles in month + weekly repeats intersecting it
    all_events = (
        (
            await db.execute(
                select(CalendarEvent).where(CalendarEvent.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    events: list[EventOut] = []
    for ev in all_events:
        if not ev.repeat_weekly:
            if first <= ev.date <= last:
                events.append(_event_out(ev))
        else:
            until = ev.repeat_until or last
            occ = ev.date
            while occ <= min(until, last):
                if occ >= first:
                    events.append(_event_out(ev, occurrence=occ))
                occ += timedelta(days=7)

    gcal_rows = (
        (
            await db.execute(
                select(GcalEvent)
                .where(GcalEvent.date >= first, GcalEvent.date <= last)
                .order_by(GcalEvent.date, GcalEvent.start_minute)
            )
        )
        .scalars()
        .all()
    )
    marks = (
        (
            await db.execute(
                select(DayMark).where(DayMark.date >= first, DayMark.date <= last)
            )
        )
        .scalars()
        .all()
    )
    task_rows = (
        (
            await db.execute(
                select(StudyTask).where(
                    StudyTask.user_id == user.id,
                    StudyTask.due_date >= first,
                    StudyTask.due_date <= last,
                )
            )
        )
        .scalars()
        .all()
    )

    return MonthOut(
        ym=ym,
        semester_start=app.semester_start,
        semester_end=app.semester_end,
        meetings=meetings,
        events=sorted(events, key=lambda e: (e.date, e.start_minute or 0)),
        gcal=[
            GcalOut(
                date=g.date,
                title=g.title,
                calendar=g.calendar,
                start_minute=g.start_minute,
                end_minute=g.end_minute,
                location=g.location,
                organizer=g.organizer,
                attendees=g.attendees,
                my_status=g.my_status,
            )
            for g in gcal_rows
        ],
        marks=[
            MarkOut(
                date=m.date,
                course_id=m.course_id,
                block_id=m.block_id,
                mode=m.mode,
                note=m.note,
            )
            for m in marks
        ],
        tasks=[
            CalTaskOut(
                id=t.id,
                date=t.due_date,
                title=t.title,
                course_id=t.course_id,
                course_code=courses[t.course_id].code if t.course_id in courses else None,
                accent_color=courses[t.course_id].accent_color
                if t.course_id in courses
                else None,
                due_minute=t.due_minute,
                done=t.done_at is not None,
            )
            for t in task_rows
        ],
        gcal_configured=bool(app.gcal_ics_url) or bool(get_settings().gcal_ics_urls),
    )


@router.get("/month")
async def month_view(
    ym: str = Query(...),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> MonthOut:
    first, last = _parse_ym(ym)
    return await _range_data(db, user, first, last, ym=ym)


@router.get("/range")
async def range_view(
    start: Date = Query(...),
    end: Date = Query(...),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> MonthOut:
    if end < start or (end - start).days > 62:
        raise HTTPException(status_code=422, detail="range must be 0-62 days")
    return await _range_data(db, user, start, end)


@router.post("/events", dependencies=[Depends(require_csrf)])
async def create_event(
    data: EventIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> EventOut:
    if data.repeat_weekly and data.repeat_until is None:
        raise HTTPException(status_code=422, detail="repeat_until required")
    ev = CalendarEvent(user_id=user.id, **data.model_dump())
    db.add(ev)
    await db.commit()
    return _event_out(ev)


async def _get_event(db: AsyncSession, user: User, event_id: int) -> CalendarEvent:
    ev = await db.get(CalendarEvent, event_id)
    if ev is None or ev.user_id != user.id:
        raise HTTPException(status_code=404, detail="Event not found")
    return ev


@router.patch("/events/{event_id}", dependencies=[Depends(require_csrf)])
async def update_event(
    event_id: int,
    data: EventPatch,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> EventOut:
    ev = await _get_event(db, user, event_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(ev, key, value)
    await db.commit()
    return _event_out(ev)


@router.delete("/events/{event_id}", dependencies=[Depends(require_csrf)])
async def delete_event(
    event_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    ev = await _get_event(db, user, event_id)
    await db.delete(ev)
    await db.commit()
    return {"ok": True}


@router.put("/marks", dependencies=[Depends(require_csrf)])
async def put_mark(data: MarkIn, db: AsyncSession = Depends(get_db)) -> dict:
    # A mark targets a labeled block (RTO/WFH/No-work) or a class scope
    # (sync/async).
    allowed = (
        ("rto", "wfh", "nowork") if data.block_id is not None else ("sync", "async")
    )
    existing = (
        await db.execute(
            select(DayMark).where(
                DayMark.date == data.date,
                DayMark.course_id.is_(None)
                if data.course_id is None
                else DayMark.course_id == data.course_id,
                DayMark.block_id.is_(None)
                if data.block_id is None
                else DayMark.block_id == data.block_id,
            )
        )
    ).scalar_one_or_none()
    if data.mode is None:
        if existing is not None:
            await db.delete(existing)
    elif data.mode not in allowed:
        raise HTTPException(
            status_code=422, detail=f"mode must be one of {allowed}"
        )
    elif existing is not None:
        existing.mode = data.mode
        existing.note = data.note
    else:
        db.add(
            DayMark(
                date=data.date,
                course_id=data.course_id,
                block_id=data.block_id,
                mode=data.mode,
                note=data.note,
            )
        )
    await db.commit()
    return {"ok": True}


@router.post("/gcal/refresh", dependencies=[Depends(require_csrf)])
async def refresh_gcal(db: AsyncSession = Depends(get_db)) -> dict:
    count, error = await fetch_gcal(db)
    return {"count": count, "error": error, "synced_at": datetime.now().isoformat()}


@router.get("/export.ics")
async def export_ics(
    user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> Response:
    app = await get_app_settings(db)
    rows = (
        await db.execute(
            select(ScheduleBlock, Course)
            .join(Course, Course.id == ScheduleBlock.course_id)
            .where(Course.user_id == user.id, Course.archived_at.is_(None))
        )
    ).all()
    events = (
        (
            await db.execute(
                select(CalendarEvent).where(CalendarEvent.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    payload = build_ics(
        [(b, c) for b, c in rows], events, app.semester_start, app.semester_end
    )
    return Response(
        content=payload,
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="manabi.ics"'},
    )
