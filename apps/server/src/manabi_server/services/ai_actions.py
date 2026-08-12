"""Execute AI-proposed actions ("Steven takes actions").

The proposed params are stored server-side on the ChatMessage; these builders
validate them and create the Task / CalendarEvent, reusing the same models as
the manual endpoints. They flush (not commit) so the caller can update the
message's action status in the same transaction.
"""

from datetime import date

from manabi_core.models import CalendarEvent, Course, StudyTask, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _course_id_by_code(db: AsyncSession, user: User, code: str | None) -> int | None:
    """Resolve a course by its code (case-insensitive, active only)."""
    if not code or not code.strip():
        return None
    course = (
        await db.execute(
            select(Course).where(
                Course.user_id == user.id,
                Course.code.ilike(code.strip()),
                Course.archived_at.is_(None),
            )
        )
    ).scalars().first()
    return course.id if course else None


def _parse_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _minute(value: object) -> int | None:
    return value if isinstance(value, int) and 0 <= value <= 1439 else None


async def execute_task_action(db: AsyncSession, user: User, params: dict) -> dict:
    title = (params.get("title") or "").strip()
    if not title:
        raise ValueError("A task needs a title.")
    task = StudyTask(
        user_id=user.id,
        title=title[:512],
        notes=(params.get("notes") or None),
        course_id=await _course_id_by_code(db, user, params.get("course_code")),
        due_date=_parse_date(params.get("due_date")),
        due_minute=_minute(params.get("due_minute")),
        source="manual",
    )
    db.add(task)
    await db.flush()
    return {"kind": "task", "id": task.id, "title": task.title}


async def execute_event_action(db: AsyncSession, user: User, params: dict) -> dict:
    title = (params.get("title") or "").strip()
    if not title:
        raise ValueError("An event needs a title.")
    when = _parse_date(params.get("date"))
    if when is None:
        raise ValueError("An event needs a valid date.")
    event = CalendarEvent(
        user_id=user.id,
        title=title[:255],
        notes=(params.get("notes") or None),
        course_id=await _course_id_by_code(db, user, params.get("course_code")),
        date=when,
        start_minute=_minute(params.get("start_minute")),
        end_minute=_minute(params.get("end_minute")),
        repeat_weekly=False,
    )
    db.add(event)
    await db.flush()
    return {"kind": "event", "id": event.id, "title": event.title}
