"""Outbound .ics: classes (weekly RRULEs) + custom events, for a one-time
import into Google Calendar. Stable UIDs so re-imports update, not duplicate."""

from datetime import UTC, date, datetime, timedelta

from manabi_core.models import CalendarEvent, Course, ScheduleBlock

from manabi_server.timeutil import MANILA


def _first_on_or_after(start: date, weekday: int) -> date:
    return start + timedelta(days=(weekday - start.weekday()) % 7)


def _local(day: date, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=MANILA)


def _until_utc(sem_end: date) -> datetime:
    # RFC 5545: UNTIL must be UTC when DTSTART carries a TZID
    return datetime(
        sem_end.year, sem_end.month, sem_end.day, 23, 59, 59, tzinfo=MANILA
    ).astimezone(UTC)


def build_ics(
    blocks: list[tuple[ScheduleBlock, Course]],
    events: list[CalendarEvent],
    sem_start: date,
    sem_end: date,
) -> bytes:
    import icalendar

    cal = icalendar.Calendar()
    cal.add("prodid", "-//Manabi//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "Manabi")
    cal.add_component(icalendar.Timezone.from_tzinfo(MANILA))

    for block, course in blocks:
        first = _first_on_or_after(sem_start, block.day_of_week)
        if first > sem_end:
            continue
        ev = icalendar.Event()
        ev.add("uid", f"manabi-block-{block.id}@manabi")
        ev.add("summary", course.code)
        ev.add("dtstart", _local(first, block.start_minute))
        ev.add("dtend", _local(first, block.end_minute))
        ev.add("rrule", {"FREQ": "WEEKLY", "UNTIL": _until_utc(sem_end)})
        if block.location:
            ev.add("location", block.location)
        ev.add("description", course.name)
        cal.add_component(ev)

    for event in events:
        ev = icalendar.Event()
        ev.add("uid", f"manabi-event-{event.id}@manabi")
        ev.add("summary", event.title)
        if event.start_minute is not None:
            ev.add("dtstart", _local(event.date, event.start_minute))
            ev.add(
                "dtend",
                _local(event.date, event.end_minute or (event.start_minute + 60)),
            )
        else:  # all-day
            ev.add("dtstart", event.date)
            ev.add("dtend", event.date + timedelta(days=1))
        if event.repeat_weekly and event.repeat_until:
            ev.add("rrule", {"FREQ": "WEEKLY", "UNTIL": _until_utc(event.repeat_until)})
        if event.notes:
            ev.add("description", event.notes)
        cal.add_component(ev)

    return cal.to_ical()
