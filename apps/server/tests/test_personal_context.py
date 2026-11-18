"""The personal context Steven's letter and the assistant read. Built from the
real Nov 18, 2026 case: Wednesday's internship was marked "No work" and four of
Thursday's classes async, yet the context listed the internship as today's
class and Thursday in full — and the letter told Gio a free Wednesday held "six
straight hours of classes" with a quiz "due today" that was due Thursday."""

from datetime import date
from types import SimpleNamespace as NS

from manabi_server.services import context as ctx

WED = date(2026, 11, 18)
THU = date(2026, 11, 19)
FRI = date(2026, 11, 20)

# course ids: 2 CSCI 70 · 3 CSCI 60 · 4 SocSc 14 · 5 CSCI 142i · 6 ISCS 30.18 · 7 CSCI 161.03
JJ_WED, JJ_THU = 39, 40  # internship blocks (no course)


def meet(d, code, start, end, course_id=None, block_id=1, location=None, url=None):
    return NS(date=d, code=code, course_id=course_id, block_id=block_id,
              start_minute=start, end_minute=end, location=location, meeting_url=url)


def mark(d, mode, course_id=None, block_id=None):
    return NS(date=d, mode=mode, course_id=course_id, block_id=block_id)


MEETINGS = [
    meet(WED, "J&J Internship", 900, 1439, block_id=JJ_WED, location="BGC"),
    meet(THU, "SocSc 14", 480, 570, course_id=4),
    meet(THU, "CSCI 142i", 570, 660, course_id=5),
    meet(THU, "CSCI 70", 660, 750, course_id=2),
    meet(THU, "ISCS 30.18", 780, 840, course_id=6),
    meet(THU, "CSCI 161.03", 840, 930, course_id=7),
    meet(THU, "J&J Internship", 900, 1439, block_id=JJ_THU, location="BGC"),
    meet(THU, "CSCI 60", 1020, 1200, course_id=3, location="F-113"),
]
MARKS = [
    mark(WED, "nowork", block_id=JJ_WED),
    *(mark(THU, "async", course_id=c) for c in (5, 6, 2, 7)),
]


def test_meeting_mode_follows_the_calendar():
    wed = [(m.course_id, m.block_id, m.mode) for m in MARKS if m.date == WED]
    thu = [(m.course_id, m.block_id, m.mode) for m in MARKS if m.date == THU]
    assert ctx.meeting_mode(None, JJ_WED, wed) == "nowork"
    assert ctx.meeting_mode(None, JJ_THU, thu) == "wfh"  # a labeled block defaults to WFH
    assert ctx.meeting_mode(5, 2, thu) == "async"
    assert ctx.meeting_mode(4, 3, thu) == "onsite"
    whole_day_sync = [(None, None, "sync")]
    assert ctx.meeting_mode(4, 3, whole_day_sync) == "sync"
    assert ctx.meeting_mode(4, 3, whole_day_sync + [(4, None, "async")]) == "async"


def test_a_no_work_day_with_no_classes_says_so():
    lines = ctx.schedule_lines(MEETINGS, MARKS, today=WED, now_min=1, forward_days=7)
    assert lines[0] == "Today (Wed Nov 18): no classes or work — a free day."
    assert not any("Wed Nov 18" in ln and "Internship" in ln for ln in lines)


def test_async_classes_are_left_out_and_tomorrow_is_named():
    lines = ctx.schedule_lines(MEETINGS, MARKS, today=WED, now_min=1, forward_days=7)
    upcoming = lines[lines.index("Classes and work in the next 7 days:") + 1:]
    assert upcoming == [
        "  - Thu Nov 19 (tomorrow) SocSc 14 08:00-09:30",
        "  - Thu Nov 19 (tomorrow) J&J Internship 15:00-23:59 (WFH)",
        "  - Thu Nov 19 (tomorrow) CSCI 60 17:00-20:00 @ F-113",
    ]


def test_today_lists_only_what_is_still_ahead_with_its_mode():
    marks = [mark(THU, "sync", course_id=4), mark(THU, "rto", block_id=JJ_THU)]
    lines = ctx.schedule_lines(MEETINGS, marks, today=THU, now_min=600, forward_days=7)
    assert lines[:5] == [
        "Today (Thu Nov 19), still ahead:",
        "  - CSCI 142i 09:30-11:00",  # running now, ends at 11:00
        "  - CSCI 70 11:00-12:30",
        "  - ISCS 30.18 13:00-14:00",
        "  - CSCI 161.03 14:00-15:30",
    ]
    assert "  - J&J Internship 15:00-23:59 @ BGC (RTO)" in lines
    assert not any("SocSc 14" in ln for ln in lines)  # 08:00-09:30 is over


def test_a_day_whose_classes_are_over_is_not_called_free():
    lines = ctx.schedule_lines(MEETINGS, MARKS, today=THU, now_min=1439, forward_days=7)
    assert lines[0] == "Today (Thu Nov 19): nothing left on the schedule."


def test_tasks_due_tomorrow_are_labelled():
    def task(title, code, due):
        return NS(title=title, course_code=code, due_date=due, due_minute=None, done=False)

    tasks = [
        task("Quiz 11 - LAN", "CSCI 60", THU),
        task("Project Files", "CSCI 161.03", FRI),
        task("Old thing", None, date(2026, 11, 16)),
        task("Today thing", None, WED),
    ]
    assert ctx.task_lines(tasks, today=WED) == [
        "Open tasks (by due date):",
        "  - Old thing — due Mon Nov 16 (OVERDUE)",
        "  - Today thing — due Wed Nov 18 (today)",
        "  - [CSCI 60] Quiz 11 - LAN — due Thu Nov 19 (tomorrow)",
        "  - [CSCI 161.03] Project Files — due Fri Nov 20",
    ]
