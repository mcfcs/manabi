"""In-process scheduler (FastAPI lifespan task, 5-minute ticks).

Safe because start-manabi.bat runs a single uvicorn worker; if --workers N
is ever introduced this needs a Postgres advisory lock around the tick.

Per tick:
  1. Due-task digest push (07:00–22:00 Manila; notified_at is the
     idempotency latch — set in the same transaction as the send).
  2. Google ICS re-poll when older than 30 minutes.
  3. Optional class-starting-soon pushes (app_settings.class_reminders).
"""

import asyncio
import logging
from datetime import timedelta

from manabi_core.models import AppSettings, Course, ScheduleBlock, StudyTask
from sqlalchemy import select

from manabi_server.services.gcal import fetch_gcal
from manabi_server.services.push import send_to_all
from manabi_server.timeutil import now_manila, today_manila

log = logging.getLogger("manabi.scheduler")

TICK_SECONDS = 300


async def _tick(sessionmaker) -> None:
    now = now_manila()
    async with sessionmaker() as db:
        # 1. due-task digest
        if 7 <= now.hour < 22:
            due = (
                (
                    await db.execute(
                        select(StudyTask).where(
                            StudyTask.done_at.is_(None),
                            StudyTask.notified_at.is_(None),
                            StudyTask.due_date <= today_manila(),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if due:
                titles = ", ".join(t.title[:40] for t in due[:3])
                more = f" +{len(due) - 3} more" if len(due) > 3 else ""
                delivered = await send_to_all(
                    db,
                    {
                        "title": f"{len(due)} task{'s' if len(due) > 1 else ''} due",
                        "body": f"{titles}{more}",
                        "tag": "manabi-due",
                        "url": "/tasks",
                    },
                )
                for t in due:
                    t.notified_at = now
                await db.commit()
                log.info("due digest: %d tasks, %d devices", len(due), delivered)

        # 2. gcal re-poll
        app = await db.get(AppSettings, 1)
        if app is not None and app.gcal_ics_url:
            stale = (
                app.gcal_last_synced_at is None
                or now - app.gcal_last_synced_at > timedelta(minutes=30)
            )
            if stale:
                await fetch_gcal(db)

        # 3. class reminders (10–15 min ahead; 5-min tick → fires once)
        if app is not None and app.class_reminders:
            minute_now = now.hour * 60 + now.minute
            rows = (
                await db.execute(
                    select(ScheduleBlock, Course)
                    .join(Course, Course.id == ScheduleBlock.course_id)
                    .where(ScheduleBlock.day_of_week == now.weekday())
                )
            ).all()
            in_semester = (
                app.semester_start <= today_manila() <= app.semester_end
            )
            for block, course in rows:
                if in_semester and minute_now + 10 <= block.start_minute < minute_now + 15:
                    await send_to_all(
                        db,
                        {
                            "title": f"{course.code} soon",
                            "body": f"Starts {block.start_minute // 60:02d}:"
                            f"{block.start_minute % 60:02d}"
                            + (f" · {block.location}" if block.location else ""),
                            "tag": f"manabi-class-{block.id}",
                            "url": "/schedule",
                        },
                    )


async def run_scheduler(sessionmaker) -> None:
    log.info("scheduler started (%ds ticks)", TICK_SECONDS)
    while True:
        try:
            await _tick(sessionmaker)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — one bad tick must not kill the loop
            log.exception("scheduler tick failed")
        await asyncio.sleep(TICK_SECONDS)
