"""Compact plaintext "personal context" for the general Manabi AI assistant.

Serializes the user's schedule (today + this week), upcoming/overdue tasks, near
events, and study streak into ~350-450 tokens so the assistant can answer
"what's due this week / what are my classes today" directly, without any material
retrieval. Reuses the calendar/tasks/stats read helpers verbatim.
"""

from datetime import timedelta

from manabi_core.models import User
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.timeutil import now_manila, today_manila

_MAX_CHARS = 2600


def _hhmm(m: int | None) -> str:
    if m is None:
        return ""
    return f"{m // 60:02d}:{m % 60:02d}"


def _daylabel(d) -> str:
    # Avoid %-d (not supported on Windows strftime).
    return f"{d.strftime('%a %b')} {d.day}" if hasattr(d, "strftime") else str(d)


def meeting_mode(course_id: int | None, block_id: int, marks: list[tuple]) -> str:
    """The calendar's meetingMode (CalendarPage.tsx) for one meeting on a day;
    `marks` are that day's (course_id, block_id, mode). A labeled block (an
    internship, no course) has its own rto|wfh|nowork mark, default wfh; a class
    follows scheduler.class_mode (own mark, then whole-day mark, else onsite)."""
    if course_id is None:
        return next((m for _c, b, m in marks if b == block_id), "wfh")
    from manabi_server.services.scheduler import class_mode

    return class_mode(course_id, marks)


# Marked as not meeting: an async class, a "No work" internship day.
_NO_MEETING = {"async", "nowork"}


def _rel(d, today) -> str:
    if d == today + timedelta(days=1):
        return " (tomorrow)"
    return ""


def _where(m, mode: str) -> str:
    if mode == "sync":
        return " (online)"
    tag = {"rto": " (RTO)", "wfh": " (WFH)"}.get(mode, "")
    if mode == "wfh":
        return tag  # a WFH day isn't at the office's location
    return (f" @ {m.location}" if m.location else "") + tag


def schedule_lines(meetings, marks, *, today, now_min: int, forward_days: int) -> list[str]:
    """Today's and the coming days' meetings with the calendar's marks applied.
    The Nov 18 letter said a free Wednesday held "six straight hours of
    classes": the context ignored marks (the internship was marked No work) and
    simply left the Today section out, so the model filled the gap from
    Thursday. A free day is now said outright, and tomorrow is named."""
    by_day: dict = {}
    for mk in marks:
        by_day.setdefault(mk.date, []).append((mk.course_id, mk.block_id, mk.mode))
    held = []
    for m in meetings:
        mode = meeting_mode(m.course_id, m.block_id, by_day.get(m.date, []))
        if mode not in _NO_MEETING:
            held.append((m, mode))
    held.sort(key=lambda x: (x[0].date, x[0].start_minute))

    lines: list[str] = []
    today_all = [(m, mode) for m, mode in held if m.date == today]
    ahead = [(m, mode) for m, mode in today_all if m.end_minute > now_min]
    if ahead:
        lines.append(f"Today ({_daylabel(today)}), still ahead:")
        for m, mode in ahead[:8]:
            span = f"{_hhmm(m.start_minute)}-{_hhmm(m.end_minute)}"
            lines.append(f"  - {m.code} {span}{_where(m, mode)}")
    elif today_all:
        lines.append(f"Today ({_daylabel(today)}): nothing left on the schedule.")
    else:
        lines.append(f"Today ({_daylabel(today)}): no classes or work — a free day.")

    last = today + timedelta(days=forward_days)
    upcoming = [(m, mode) for m, mode in held if today < m.date <= last]
    if upcoming:
        lines.append(f"Classes and work in the next {forward_days} days:")
        for m, mode in upcoming[:10]:
            span = f"{_hhmm(m.start_minute)}-{_hhmm(m.end_minute)}"
            day = f"{_daylabel(m.date)}{_rel(m.date, today)}"
            lines.append(f"  - {day} {m.code} {span}{_where(m, mode)}")
    return lines


def task_lines(tasks, *, today) -> list[str]:
    """Open dated tasks, soonest first, with overdue / today / tomorrow spelled
    out — the Nov 18 letter called a quiz due Thursday "due today"."""
    open_tasks = [t for t in tasks if not t.done and t.due_date is not None]
    open_tasks.sort(key=lambda t: (t.due_date, t.due_minute or 0))
    if not open_tasks:
        return []
    lines = ["Open tasks (by due date):"]
    for t in open_tasks[:8]:
        if t.due_date < today:
            tag = " (OVERDUE)"
        elif t.due_date == today:
            tag = " (today)"
        else:
            tag = _rel(t.due_date, today)
        code = f"[{t.course_code}] " if t.course_code else ""
        lines.append(f"  - {code}{t.title[:60]} — due {_daylabel(t.due_date)}{tag}")
    return lines


async def build_personal_context(db: AsyncSession, user: User, forward_days: int = 7) -> str:
    """Return a compact plaintext block describing the user's near-term schedule,
    tasks and study activity. Never raises — a degraded context is fine."""
    # Imported here to avoid an import cycle (api → services, and these api
    # modules import services.gcal etc.).
    from manabi_server.api.calendar import _range_data
    from manabi_server.api.stats import stats
    from manabi_server.api.tasks import list_tasks

    today = today_manila()
    now = now_manila()
    now_min = now.hour * 60 + now.minute
    lines: list[str] = [f"PERSONAL CONTEXT (now: {_daylabel(today)}, {_hhmm(now_min)} Manila):"]

    try:
        rng = await _range_data(db, user, today, today + timedelta(days=forward_days))
    except Exception:  # noqa: BLE001 — degrade gracefully
        rng = None

    if rng is not None:
        lines += schedule_lines(
            rng.meetings, rng.marks, today=today, now_min=now_min, forward_days=forward_days
        )

        near_events = [(e.date, e.title, e.start_minute) for e in rng.events] + [
            (g.date, g.title, g.start_minute) for g in rng.gcal
        ]
        near_events.sort(key=lambda x: (x[0], x[2] if x[2] is not None else 0))
        if near_events:
            lines.append("Events:")
            for d, title, sm in near_events[:6]:
                t = f" {_hhmm(sm)}" if sm is not None else ""
                lines.append(f"  - {_daylabel(d)}{t}: {title[:60]}")

    # What the student wrote about yesterday's and today's classes.
    try:
        from manabi_core.models import ClassRoundup, Course
        from sqlalchemy import select

        rows = (
            await db.execute(
                select(ClassRoundup, Course.code)
                .join(Course, Course.id == ClassRoundup.course_id)
                .where(
                    Course.user_id == user.id,
                    ClassRoundup.date >= today - timedelta(days=1),
                )
                .order_by(ClassRoundup.date, Course.code)
            )
        ).all()
    except Exception:  # noqa: BLE001
        rows = []
    if rows:
        lines.append("Class roundups (the student's own notes on what happened):")
        for r, code in rows[:6]:
            when = "today" if r.date == today else "yesterday"
            lines.append(f"  - {code} ({when}): {' '.join(r.text.split())[:220]}")

    try:
        tasks = await list_tasks(user=user, db=db)
    except Exception:  # noqa: BLE001
        tasks = []
    lines += task_lines(tasks, today=today)

    try:
        st = await stats(user=user, db=db)
        lines.append(
            f"Study streak: {st.streak_days} day(s); "
            f"{st.reviews_total} reviews, {st.quizzes_taken} quizzes taken."
        )
    except Exception:  # noqa: BLE001
        pass

    return "\n".join(lines)[:_MAX_CHARS]
