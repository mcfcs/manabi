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
    ScheduleBlock,
    User,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.api.settings import get_app_settings
from manabi_server.db import get_db
from manabi_server.security import get_default_user, require_csrf
from manabi_server.services.gcal import fetch_gcal
from manabi_server.services.ics_export import build_ics

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


class MeetingOut(BaseModel):
    date: Date
    course_id: int
    code: str
    accent_color: str | None
    start_minute: int
    end_minute: int
    location: str | None


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
    start_minute: int | None
    end_minute: int | None
    location: str | None


class MarkOut(BaseModel):
    date: Date
    course_id: int | None
    mode: str
    note: str | None


class MonthOut(BaseModel):
    ym: str
    semester_start: Date
    semester_end: Date
    meetings: list[MeetingOut]
    events: list[EventOut]
    gcal: list[GcalOut]
    marks: list[MarkOut]
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
    mode: str | None = None  # "sync" | "async" | None = delete
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


@router.get("/month")
async def month_view(
    ym: str = Query(...),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> MonthOut:
    first, last = _parse_ym(ym)
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
        (
            await db.execute(
                select(ScheduleBlock).where(ScheduleBlock.course_id.in_(courses.keys()))
            )
        )
        .scalars()
        .all()
    )

    # Classes: expand blocks over the month ∩ semester
    meetings: list[MeetingOut] = []
    day = max(first, app.semester_start)
    stop = min(last, app.semester_end)
    while day <= stop:
        for b in blocks:
            if b.day_of_week == day.weekday():
                c = courses[b.course_id]
                meetings.append(
                    MeetingOut(
                        date=day,
                        course_id=c.id,
                        code=c.code,
                        accent_color=c.accent_color,
                        start_minute=b.start_minute,
                        end_minute=b.end_minute,
                        location=b.location,
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
                start_minute=g.start_minute,
                end_minute=g.end_minute,
                location=g.location,
            )
            for g in gcal_rows
        ],
        marks=[
            MarkOut(date=m.date, course_id=m.course_id, mode=m.mode, note=m.note)
            for m in marks
        ],
        gcal_configured=bool(app.gcal_ics_url),
    )


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
    existing = (
        await db.execute(
            select(DayMark).where(
                DayMark.date == data.date,
                DayMark.course_id.is_(None)
                if data.course_id is None
                else DayMark.course_id == data.course_id,
            )
        )
    ).scalar_one_or_none()
    if data.mode is None:
        if existing is not None:
            await db.delete(existing)
    elif data.mode not in ("sync", "async"):
        raise HTTPException(status_code=422, detail="mode must be sync or async")
    elif existing is not None:
        existing.mode = data.mode
        existing.note = data.note
    else:
        db.add(
            DayMark(
                date=data.date, course_id=data.course_id, mode=data.mode, note=data.note
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
