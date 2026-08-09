"""Increment 9: ICS export, Google ICS parsing, timeutil, boilerplate of push."""

from datetime import UTC, date, datetime

from manabi_core.models import CalendarEvent, Course, ScheduleBlock
from manabi_server.services.gcal import _occurrence_rows
from manabi_server.services.ics_export import build_ics
from manabi_server.timeutil import MANILA


def _block(**kw) -> ScheduleBlock:
    defaults = dict(
        id=1, course_id=1, day_of_week=0, start_minute=480, end_minute=570,
        location="SEC-B201A",
    )
    defaults.update(kw)
    return ScheduleBlock(**defaults)


def _course(**kw) -> Course:
    defaults = dict(id=1, user_id=1, code="SocSc 14", name="POLITICS", position=0)
    defaults.update(kw)
    return Course(**defaults)


SEM_START = date(2026, 8, 5)  # a Wednesday
SEM_END = date(2026, 12, 12)


class TestIcsExport:
    def test_weekly_class_rrule(self):
        ics = build_ics([(_block(), _course())], [], SEM_START, SEM_END).decode()
        # First Monday on/after Aug 5 2026 is Aug 10
        assert "DTSTART;TZID=Asia/Manila:20260810T080000" in ics
        assert "RRULE:FREQ=WEEKLY;UNTIL=" in ics
        # RFC 5545: UNTIL must be UTC (Z) when DTSTART carries a TZID
        assert "UNTIL=20261212T155959Z" in ics
        assert "LOCATION:SEC-B201A" in ics
        assert "UID:manabi-block-1@manabi" in ics
        assert "BEGIN:VTIMEZONE" in ics

    def test_all_day_event(self):
        ev = CalendarEvent(
            id=7, user_id=1, title="Holiday", date=date(2026, 8, 21),
            start_minute=None, end_minute=None, repeat_weekly=False,
        )
        ics = build_ics([], [ev], SEM_START, SEM_END).decode()
        assert "DTSTART;VALUE=DATE:20260821" in ics
        assert "UID:manabi-event-7@manabi" in ics

    def test_block_after_semester_end_skipped(self):
        # Semester is a single Wednesday; a Monday block never occurs
        ics = build_ics(
            [(_block(), _course())], [], date(2026, 12, 9), date(2026, 12, 9)
        ).decode()
        assert "manabi-block" not in ics


class TestGcalOccurrenceRows:
    def test_timed_event_utc_converted_to_manila(self):
        import icalendar

        ev = icalendar.Event()
        ev.add("summary", "Internship sync")
        # 06:00 UTC = 14:00 Manila
        ev.add("dtstart", datetime(2026, 9, 1, 6, 0, tzinfo=UTC))
        ev.add("dtend", datetime(2026, 9, 1, 7, 0, tzinfo=UTC))
        rows = _occurrence_rows(ev, "uid1")
        assert len(rows) == 1
        assert rows[0]["date"] == date(2026, 9, 1)
        assert rows[0]["start_minute"] == 14 * 60
        assert rows[0]["end_minute"] == 15 * 60

    def test_all_day_dtend_exclusive(self):
        import icalendar

        ev = icalendar.Event()
        ev.add("summary", "Org fair")
        ev.add("dtstart", date(2026, 9, 3))
        ev.add("dtend", date(2026, 9, 5))  # exclusive → Sep 3 + Sep 4 only
        rows = _occurrence_rows(ev, "uid2")
        assert [r["date"] for r in rows] == [date(2026, 9, 3), date(2026, 9, 4)]
        assert all(r["start_minute"] is None for r in rows)

    def test_naive_datetime_assumed_manila(self):
        import icalendar

        ev = icalendar.Event()
        ev.add("summary", "Floating")
        ev.add("dtstart", datetime(2026, 9, 2, 9, 30))
        rows = _occurrence_rows(ev, "uid3")
        assert rows[0]["start_minute"] == 9 * 60 + 30


class TestTimeutil:
    def test_manila_offset(self):
        from manabi_server.timeutil import now_manila

        assert now_manila().utcoffset().total_seconds() == 8 * 3600

    def test_minute_of(self):
        from manabi_server.timeutil import minute_of

        assert minute_of(datetime(2026, 8, 10, 17, 45, tzinfo=MANILA)) == 1065
