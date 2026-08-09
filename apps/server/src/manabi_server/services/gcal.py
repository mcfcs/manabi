"""Google Calendar inbound: poll the user's secret ICS feed and cache events.

The feed URL is the "Secret address in iCal format" from Google Calendar
settings — it grants read access to the whole calendar, so it is stored
server-side only and never echoed back to the browser in full.
"""

import logging
from datetime import date, datetime, timedelta

import httpx
from manabi_core.models import AppSettings, GcalEvent
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.timeutil import MANILA, minute_of, now_manila

log = logging.getLogger("manabi.gcal")


def _occurrence_rows(event, uid: str) -> list[dict]:
    """One expanded VEVENT occurrence → per-day row dicts (Manila-local)."""
    start = event.get("DTSTART").dt if event.get("DTSTART") else None
    end = event.get("DTEND").dt if event.get("DTEND") else None
    title = str(event.get("SUMMARY", "")) or "(untitled)"
    location = str(event.get("LOCATION", "")) or None
    if start is None:
        return []

    rows: list[dict] = []
    if isinstance(start, datetime):
        start_l = start.astimezone(MANILA) if start.tzinfo else start.replace(tzinfo=MANILA)
        end_l = None
        if isinstance(end, datetime):
            end_l = end.astimezone(MANILA) if end.tzinfo else end.replace(tzinfo=MANILA)
        if end_l is None or end_l.date() == start_l.date():
            rows.append(
                {
                    "uid": uid,
                    "title": title,
                    "date": start_l.date(),
                    "start_minute": minute_of(start_l),
                    "end_minute": minute_of(end_l) if end_l else None,
                    "location": location,
                }
            )
        else:  # spans days → one row per day (timed on first/last, all-day between)
            day = start_l.date()
            while day <= end_l.date():
                rows.append(
                    {
                        "uid": uid,
                        "title": title,
                        "date": day,
                        "start_minute": minute_of(start_l) if day == start_l.date() else None,
                        "end_minute": minute_of(end_l) if day == end_l.date() else None,
                        "location": location,
                    }
                )
                day += timedelta(days=1)
    else:  # DATE-typed = all-day; DTEND is exclusive per RFC 5545
        last = (end - timedelta(days=1)) if isinstance(end, date) else start
        day = start
        while day <= max(start, last):
            rows.append(
                {
                    "uid": uid,
                    "title": title,
                    "date": day,
                    "start_minute": None,
                    "end_minute": None,
                    "location": location,
                }
            )
            day += timedelta(days=1)
    return rows


async def fetch_gcal(db: AsyncSession) -> tuple[int, str | None]:
    """Fetch + expand + cache. Returns (event_count, error). Never raises."""
    settings_row = await db.get(AppSettings, 1)
    if settings_row is None or not settings_row.gcal_ics_url:
        return 0, "no feed configured"

    try:
        import icalendar
        import recurring_ical_events

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.get(settings_row.gcal_ics_url)
        r.raise_for_status()
        cal = icalendar.Calendar.from_ical(r.content)
        window_start = settings_row.semester_start
        window_end = settings_row.semester_end + timedelta(days=1)
        occurrences = recurring_ical_events.of(cal).between(window_start, window_end)

        rows: list[dict] = []
        for ev in occurrences:
            uid = str(ev.get("UID", "")) or "no-uid"
            rows.extend(_occurrence_rows(ev, uid))

        await db.execute(delete(GcalEvent))
        for row in rows:
            db.add(GcalEvent(**row))
        settings_row.gcal_last_synced_at = now_manila()
        settings_row.gcal_last_error = None
        await db.commit()
        log.info("gcal sync: %d occurrences cached", len(rows))
        return len(rows), None
    except Exception as exc:  # noqa: BLE001 — surface in settings, never crash
        await db.rollback()
        settings_row = await db.get(AppSettings, 1)
        if settings_row is not None:
            settings_row.gcal_last_error = f"{type(exc).__name__}: {str(exc)[:300]}"
            await db.commit()
        log.warning("gcal sync failed: %s", exc)
        return 0, str(exc)
