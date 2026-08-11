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


async def build_personal_context(
    db: AsyncSession, user: User, forward_days: int = 7
) -> str:
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
    lines: list[str] = [
        f"PERSONAL CONTEXT (now: {_daylabel(today)}, {_hhmm(now_min)} Manila):"
    ]

    try:
        rng = await _range_data(db, user, today, today + timedelta(days=forward_days))
    except Exception:  # noqa: BLE001 — degrade gracefully
        rng = None

    if rng is not None:
        today_meets = sorted(
            (m for m in rng.meetings if m.date == today and m.end_minute > now_min),
            key=lambda m: m.start_minute,
        )
        if today_meets:
            lines.append("Classes still today:")
            for m in today_meets[:8]:
                where = f" @ {m.location}" if m.location else (" (online)" if m.meeting_url else "")
                lines.append(f"  - {m.code} {_hhmm(m.start_minute)}-{_hhmm(m.end_minute)}{where}")

        upcoming = sorted(
            (m for m in rng.meetings if m.date > today),
            key=lambda m: (m.date, m.start_minute),
        )
        if upcoming:
            lines.append(f"Classes in the next {forward_days} days:")
            for m in upcoming[:10]:
                span = f"{_hhmm(m.start_minute)}-{_hhmm(m.end_minute)}"
                lines.append(f"  - {_daylabel(m.date)} {m.code} {span}")

        near_events = [
            (e.date, e.title, e.start_minute) for e in rng.events
        ] + [(g.date, g.title, g.start_minute) for g in rng.gcal]
        near_events.sort(key=lambda x: (x[0], x[2] if x[2] is not None else 0))
        if near_events:
            lines.append("Events:")
            for d, title, sm in near_events[:6]:
                t = f" {_hhmm(sm)}" if sm is not None else ""
                lines.append(f"  - {_daylabel(d)}{t}: {title[:60]}")

    try:
        tasks = await list_tasks(user=user, db=db)
    except Exception:  # noqa: BLE001
        tasks = []
    open_tasks = [t for t in tasks if not t.done and t.due_date is not None]
    open_tasks.sort(key=lambda t: (t.due_date, t.due_minute or 0))
    if open_tasks:
        lines.append("Open tasks (by due date):")
        for t in open_tasks[:8]:
            if t.due_date < today:
                tag = " (OVERDUE)"
            elif t.due_date == today:
                tag = " (today)"
            else:
                tag = ""
            code = f"[{t.course_code}] " if t.course_code else ""
            lines.append(f"  - {code}{t.title[:60]} — due {_daylabel(t.due_date)}{tag}")

    try:
        st = await stats(user=user, db=db)
        lines.append(
            f"Study streak: {st.streak_days} day(s); "
            f"{st.reviews_total} reviews, {st.quizzes_taken} quizzes taken."
        )
    except Exception:  # noqa: BLE001
        pass

    return "\n".join(lines)[:_MAX_CHARS]
