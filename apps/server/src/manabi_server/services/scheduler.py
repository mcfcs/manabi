"""In-process scheduler (FastAPI lifespan task, 5-minute ticks).

Safe because start-manabi.bat runs a single uvicorn worker; if --workers N
is ever introduced this needs a Postgres advisory lock around the tick.

Per tick:
  1. Due-task digest push (07:00–22:00 Manila; notified_at is the
     idempotency latch — set in the same transaction as the send).
  2. Google ICS re-poll when older than 30 minutes.
  2a. Canvas task sync when last success is older than 10 minutes.
  2b. Canvas announcement poll (~30 min, daytime).
  3. Optional class-starting-soon pushes (app_settings.class_reminders).
"""

import asyncio
import logging
from datetime import timedelta

from manabi_core.models import AppSettings, Course, ScheduleBlock, StudyTask
from sqlalchemy import select

from manabi_server.config import get_settings
from manabi_server.services.gcal import fetch_gcal
from manabi_server.services.push import send_to_all
from manabi_server.timeutil import now_manila, today_manila

log = logging.getLogger("manabi.scheduler")

TICK_SECONDS = 300
CANVAS_SYNC_INTERVAL = timedelta(minutes=10)


def canvas_sync_due(last_synced_at, now) -> bool:
    """Pure predicate so the cadence is testable: never-synced or stale."""
    return last_synced_at is None or now - last_synced_at > CANVAS_SYNC_INTERVAL


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
        if app is not None and (
            app.gcal_ics_url or get_settings().gcal_ics_urls
        ):
            stale = (
                app.gcal_last_synced_at is None
                or now - app.gcal_last_synced_at > timedelta(minutes=30)
            )
            if stale:
                await fetch_gcal(db)

        # 2a. Canvas task auto-sync — staleness-based so restarts, PC sleep,
        # and tick drift can't silently skip a window; retries every tick
        # while failing (the timestamp only advances on success).
        if canvas_sync_due(app.canvas_last_synced_at if app else None, now):
            try:
                from manabi_core.models import User

                from manabi_server.api.tasks import sync_canvas_tasks

                user = (
                    await db.execute(select(User).order_by(User.id).limit(1))
                ).scalar_one_or_none()
                if user is not None:
                    result = await sync_canvas_tasks(db, user)
                    if result["created"]:
                        log.info("canvas auto-sync: %s", result)
            except Exception:  # noqa: BLE001 — canvas down must not kill ticks
                log.exception("canvas task auto-sync failed")

        # 2b. Canvas announcements poll (~30 min cadence via minute check)
        if app is not None and 7 <= now.hour < 22 and now.minute < 5:
            try:
                from manabi_core.models import User

                from manabi_server.api.canvas import fetch_announcements

                user = (
                    await db.execute(select(User).order_by(User.id).limit(1))
                ).scalar_one_or_none()
                if user is not None:
                    anns = await fetch_announcements(db, user.id, limit=10)
                    fresh = [
                        a
                        for a in anns
                        if app.last_announcement_id is None
                        or a.id > app.last_announcement_id
                    ]
                    if anns:
                        newest = max(a.id for a in anns)
                        if app.last_announcement_id is None:
                            # first run: baseline silently, no notification storm
                            app.last_announcement_id = newest
                            await db.commit()
                        elif fresh:
                            first = fresh[0]
                            body = f"{first.course_code}: {first.title}" + (
                                f" (+{len(fresh) - 1} more)" if len(fresh) > 1 else ""
                            )
                            await send_to_all(
                                db,
                                {
                                    "title": "New Canvas announcement",
                                    "body": body,
                                    "tag": "manabi-announcement",
                                    "url": "/",
                                },
                            )
                            app.last_announcement_id = newest
                            await db.commit()
            except Exception:  # noqa: BLE001 — canvas down must not kill ticks
                log.exception("announcement poll failed")

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
