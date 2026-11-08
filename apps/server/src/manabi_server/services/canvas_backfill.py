"""Catching up after Canvas was out of reach (the token expired 2026-11-06).

The task + grade sync already heals itself once Canvas answers again: it
reads every assignment each time. Announcements do not: the poll asks for
10, and Canvas only returns 14 days unless asked for more, so a long outage
loses some. Backfill re-reads them from the start of the gap.

Pure helpers; the endpoint is api/canvas.py:canvas_backfill."""

from datetime import datetime, timedelta

from manabi_core.models import AppSettings

# Shorter gaps (a blip, a PC asleep) are covered by the regular sync and poll.
BACKFILL_GAP = timedelta(hours=1)


def mark_outage(app: AppSettings) -> None:
    """A Canvas sync failed: remember where the gap starts (the last good sync),
    unless an earlier failure already did."""
    if app.canvas_backfill_since is None:
        app.canvas_backfill_since = app.canvas_last_synced_at


def settle_after_sync(app: AppSettings, now: datetime) -> None:
    """A Canvas sync succeeded: a gap under BACKFILL_GAP is forgotten; a longer
    one stays owed until Backfill runs."""
    since = app.canvas_backfill_since
    if since is not None and now - since < BACKFILL_GAP:
        app.canvas_backfill_since = None


def backfill_due(since: datetime | None, now: datetime) -> bool:
    return since is not None and now - since >= BACKFILL_GAP


def missed_announcements(anns: list, last_notified_id: int | None) -> list:
    """Announcements the poll never pushed. No baseline yet → none (the poll's
    own first run baselines silently, never a notification storm)."""
    if last_notified_id is None:
        return []
    return [a for a in anns if a.id > last_notified_id]


def backfill_push(missed: list) -> dict | None:
    """One summary push for every missed announcement, newest first."""
    if not missed:
        return None
    first = missed[0]
    more = f" (+{len(missed) - 1} more)" if len(missed) > 1 else ""
    return {
        "title": "Missed Canvas announcement" + ("s" if len(missed) > 1 else ""),
        "body": f"{first.course_code}: {first.title}{more}",
        "tag": "manabi-announcement",
        "url": "/",
    }
