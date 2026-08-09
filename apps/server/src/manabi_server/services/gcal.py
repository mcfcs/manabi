"""Google Calendar inbound: poll one or more secret ICS feeds and cache events.

Feeds come from GCAL_ICS_URLS in .env (comma-separated, optionally
"Name|url") plus the optional single URL stored via the settings UI. Secret
addresses grant read access to the whole calendar, so they live server-side
only and are never echoed to the browser in full.
"""

import logging
import re
from datetime import date, datetime, timedelta
from urllib.parse import unquote

import httpx
from manabi_core.models import AppSettings, GcalEvent
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.config import get_settings
from manabi_server.timeutil import MANILA, minute_of, now_manila

log = logging.getLogger("manabi.gcal")


def _feed_list(app: AppSettings) -> list[tuple[str | None, str]]:
    """[(name_override, url)] from env + settings row."""
    feeds: list[tuple[str | None, str]] = []
    for raw in get_settings().gcal_ics_urls.split(","):
        raw = raw.strip()
        if not raw:
            continue
        if "|" in raw.split("://", 1)[0]:  # "Name|https://..."
            name, url = raw.split("|", 1)
            feeds.append((name.strip(), url.strip()))
        else:
            feeds.append((None, raw))
    if app.gcal_ics_url:
        feeds.append((None, app.gcal_ics_url))
    # dedupe by url, keep first
    seen: set[str] = set()
    out = []
    for name, url in feeds:
        if url not in seen:
            seen.add(url)
            out.append((name, url))
    return out


def _feed_owner_email(url: str) -> str | None:
    """Google secret ICS URLs embed the calendar owner: .../ical/<email>/private-..."""
    m = re.search(r"/ical/([^/]+)/", url)
    return unquote(m.group(1)).lower() if m else None


def _party(value) -> tuple[str | None, str | None, str]:
    """vCalAddress → (email, display name, partstat)."""
    email = str(value).replace("mailto:", "").lower() or None
    params = getattr(value, "params", {}) or {}
    name = params.get("CN") or (email.split("@")[0] if email else None)
    status = str(params.get("PARTSTAT", "")).lower().replace("_", "-") or "needs-action"
    return email, name, status


def _attendee_info(event, owner_email: str | None) -> dict:
    organizer = None
    if event.get("ORGANIZER") is not None:
        _, organizer, _ = _party(event.get("ORGANIZER"))
    raw = event.get("ATTENDEE")
    if raw is None:
        return {"organizer": organizer, "attendees": None, "my_status": None}
    values = raw if isinstance(raw, list) else [raw]
    attendees = []
    my_status = None
    for v in values:
        email, name, status = _party(v)
        if owner_email and email == owner_email:
            my_status = status
        attendees.append({"name": name, "status": status})
    return {"organizer": organizer, "attendees": attendees or None, "my_status": my_status}


def _occurrence_rows(
    event, uid: str, calendar: str | None, owner_email: str | None = None
) -> list[dict]:
    """One expanded VEVENT occurrence → per-day row dicts (Manila-local)."""
    start = event.get("DTSTART").dt if event.get("DTSTART") else None
    end = event.get("DTEND").dt if event.get("DTEND") else None
    title = str(event.get("SUMMARY", "")) or "(untitled)"
    location = str(event.get("LOCATION", "")) or None
    if start is None:
        return []

    base = {"uid": uid, "title": title, "location": location, "calendar": calendar}
    base.update(_attendee_info(event, owner_email))
    rows: list[dict] = []
    if isinstance(start, datetime):
        start_l = start.astimezone(MANILA) if start.tzinfo else start.replace(tzinfo=MANILA)
        end_l = None
        if isinstance(end, datetime):
            end_l = end.astimezone(MANILA) if end.tzinfo else end.replace(tzinfo=MANILA)
        if end_l is None or end_l.date() == start_l.date():
            rows.append(
                {
                    **base,
                    "date": start_l.date(),
                    "start_minute": minute_of(start_l),
                    "end_minute": minute_of(end_l) if end_l else None,
                }
            )
        else:  # spans days → one row per day (timed on first/last, all-day between)
            day = start_l.date()
            while day <= end_l.date():
                rows.append(
                    {
                        **base,
                        "date": day,
                        "start_minute": minute_of(start_l) if day == start_l.date() else None,
                        "end_minute": minute_of(end_l) if day == end_l.date() else None,
                    }
                )
                day += timedelta(days=1)
    else:  # DATE-typed = all-day; DTEND is exclusive per RFC 5545
        last = (end - timedelta(days=1)) if isinstance(end, date) else start
        day = start
        while day <= max(start, last):
            rows.append(
                {**base, "date": day, "start_minute": None, "end_minute": None}
            )
            day += timedelta(days=1)
    return rows


async def _fetch_one(
    client: httpx.AsyncClient,
    name: str | None,
    url: str,
    window_start: date,
    window_end: date,
) -> list[dict]:
    import icalendar
    import recurring_ical_events

    r = await client.get(url)
    r.raise_for_status()
    cal = icalendar.Calendar.from_ical(r.content)
    calendar_name = name or str(cal.get("X-WR-CALNAME", "")) or "Google"
    owner_email = _feed_owner_email(url)
    rows: list[dict] = []
    for ev in recurring_ical_events.of(cal).between(window_start, window_end):
        uid = str(ev.get("UID", "")) or "no-uid"
        rows.extend(_occurrence_rows(ev, uid, calendar_name, owner_email))
    return rows


async def fetch_gcal(db: AsyncSession) -> tuple[int, str | None]:
    """Fetch + expand + cache all feeds. Returns (event_count, error-summary).
    A single failing feed doesn't block the others. Never raises."""
    settings_row = await db.get(AppSettings, 1)
    if settings_row is None:
        return 0, "no settings row"
    feeds = _feed_list(settings_row)
    if not feeds:
        return 0, "no feed configured"

    window_start = settings_row.semester_start
    window_end = settings_row.semester_end + timedelta(days=1)
    rows: list[dict] = []
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for name, url in feeds:
            try:
                rows.extend(
                    await _fetch_one(client, name, url, window_start, window_end)
                )
            except Exception as exc:  # noqa: BLE001 — collect, don't block others
                errors.append(f"{name or url[-24:]}: {type(exc).__name__}")
                log.warning("gcal feed failed (%s): %s", url[-40:], exc)

    error = "; ".join(errors) if errors else None
    if rows or not errors:  # only wipe the cache when something succeeded
        await db.execute(delete(GcalEvent))
        for row in rows:
            db.add(GcalEvent(**row))
    settings_row.gcal_last_synced_at = now_manila()
    settings_row.gcal_last_error = error
    await db.commit()
    log.info("gcal sync: %d occurrences from %d feeds", len(rows), len(feeds))
    return len(rows), error
