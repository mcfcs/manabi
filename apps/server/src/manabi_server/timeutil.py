"""Local-time helpers. Calendar-shaped data (schedule, events, task due dates)
is stored as naive Asia/Manila DATE + minutes-since-midnight — these helpers
are the single place "now"/"today" comparisons come from."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

MANILA = ZoneInfo("Asia/Manila")


def now_manila() -> datetime:
    return datetime.now(MANILA)


def today_manila() -> date:
    return now_manila().date()


def to_manila(dt: datetime) -> datetime:
    """Aware datetime (any tz) → Manila local."""
    return dt.astimezone(MANILA)


def minute_of(dt: datetime) -> int:
    """Minutes since local midnight for an already-Manila datetime."""
    return dt.hour * 60 + dt.minute
