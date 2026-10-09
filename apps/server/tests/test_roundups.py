"""Roundups are written after class: past days any time, today from 8 PM."""

from datetime import date, datetime

from manabi_server.api.roundups import roundup_closed_reason
from manabi_server.timeutil import MANILA

TODAY = date(2026, 10, 9)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 9, hour, minute, tzinfo=MANILA)


def test_todays_roundup_opens_at_8_pm():
    assert "8 PM" in roundup_closed_reason(TODAY, at(19, 59))
    assert roundup_closed_reason(TODAY, at(20, 0)) is None
    assert roundup_closed_reason(TODAY, at(23, 30)) is None


def test_past_days_can_be_caught_up_any_time():
    assert roundup_closed_reason(date(2026, 10, 8), at(9)) is None


def test_no_roundup_for_a_future_day():
    assert roundup_closed_reason(date(2026, 10, 10), at(22)) is not None
