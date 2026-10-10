"""Tasks: manual to-dos + Canvas assignment import, due-count badge."""

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from manabi_core.models import AppSettings, Course, StudyTask, User
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.db import get_db
from manabi_server.security import get_default_user, require_csrf
from manabi_server.timeutil import MANILA, minute_of, now_manila, today_manila

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskOut(BaseModel):
    id: int
    title: str
    notes: str | None
    course_id: int | None
    course_code: str | None
    course_accent_color: str | None
    due_date: date | None
    due_minute: int | None
    done: bool
    done_source: str | None = None  # 'manual' | 'canvas' — who set done
    source: str
    created_at: datetime


class TaskIn(BaseModel):
    title: str
    notes: str | None = None
    course_id: int | None = None
    due_date: date | None = None
    due_minute: int | None = None


class TaskPatch(BaseModel):
    title: str | None = None
    notes: str | None = None
    course_id: int | None = None
    due_date: date | None = None
    due_minute: int | None = None
    done: bool | None = None


def _task_out(t: StudyTask, course: Course | None) -> TaskOut:
    return TaskOut(
        id=t.id,
        title=t.title,
        notes=t.notes,
        course_id=t.course_id,
        course_code=course.code if course else None,
        course_accent_color=course.accent_color if course else None,
        due_date=t.due_date,
        due_minute=t.due_minute,
        done=t.done_at is not None,
        done_source=t.done_source,
        source=t.source,
        created_at=t.created_at,
    )


async def _courses_by_id(db: AsyncSession, user: User) -> dict[int, Course]:
    return {
        c.id: c
        for c in (
            await db.execute(select(Course).where(Course.user_id == user.id))
        ).scalars()
    }


@router.get("")
async def list_tasks(
    user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> list[TaskOut]:
    cutoff = now_manila() - timedelta(days=14)
    tasks = (
        (
            await db.execute(
                select(StudyTask)
                .where(
                    StudyTask.user_id == user.id,
                    (StudyTask.done_at.is_(None)) | (StudyTask.done_at >= cutoff),
                )
                .order_by(StudyTask.due_date.nulls_last(), StudyTask.due_minute.nulls_last())
            )
        )
        .scalars()
        .all()
    )
    courses = await _courses_by_id(db, user)
    return [_task_out(t, courses.get(t.course_id)) for t in tasks]


@router.get("/due-count")
async def due_count(
    user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> dict:
    count = (
        await db.execute(
            select(func.count(StudyTask.id)).where(
                StudyTask.user_id == user.id,
                StudyTask.done_at.is_(None),
                StudyTask.due_date <= today_manila(),
            )
        )
    ).scalar_one()
    return {"count": count}


@router.post("", dependencies=[Depends(require_csrf)])
async def create_task(
    data: TaskIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    if not data.title.strip():
        raise HTTPException(status_code=422, detail="Title required")
    task = StudyTask(user_id=user.id, **data.model_dump())
    db.add(task)
    await db.commit()
    courses = await _courses_by_id(db, user)
    return _task_out(task, courses.get(task.course_id))


@router.patch("/{task_id}", dependencies=[Depends(require_csrf)])
async def update_task(
    task_id: int,
    data: TaskPatch,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    task = await db.get(StudyTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="Task not found")
    fields = data.model_dump(exclude_unset=True)
    done = fields.pop("done", None)
    for key, value in fields.items():
        setattr(task, key, value)
    if done is not None:
        task.done_at = now_manila() if done else None
        task.done_source = "manual"  # the sync never overrides a user's choice
    await db.commit()
    courses = await _courses_by_id(db, user)
    return _task_out(task, courses.get(task.course_id))


@router.delete("/{task_id}", dependencies=[Depends(require_csrf)])
async def delete_task(
    task_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    task = await db.get(StudyTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="Task not found")
    await db.delete(task)
    await db.commit()
    return {"ok": True}


def canvas_says_done(a: dict) -> bool:
    """Canvas reports the student's work on this assignment as done:
    submitted (incl. late / resubmitted), excused, or graded without being
    flagged missing (on-paper / no-submission items graded by the teacher)."""
    s = a.get("submission") or {}
    if s.get("excused"):
        return True
    if s.get("submitted_at"):
        return True  # covers submitted / late / resubmitted
    st = s.get("workflow_state")
    if st in ("submitted", "pending_review"):
        return True
    if st == "graded":
        return not s.get("missing")  # a 0 for "missing" is not "you did it"
    return False


# Submission types Canvas's own `overdue` bucket ignores (nothing to hand in):
# a past-due one of these is not imported as an overdue task.
_NO_SUBMISSION_TYPES = {"none", "not_graded", "on_paper", "wiki_page", ""}


def _expects_submission(a: dict) -> bool:
    types = a.get("submission_types") or []
    return any(t not in _NO_SUBMISSION_TYPES for t in types)


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def apply_canvas_done(task: StudyTask, a: dict, now: datetime) -> str | None:
    """Mirror Canvas's done state onto an existing task through the latch.
    Returns 'closed' / 'reopened' when done_at changed, else None.

    - Canvas says done, latch off → latch on; close the task if it is open.
    - Canvas says done, latch on → nothing (a manual un-check survives).
    - Canvas says not done, latch on (redo / deleted submission) → latch off;
      reopen only if it was Canvas that closed it."""
    if canvas_says_done(a):
        if task.canvas_done_seen:
            return None
        task.canvas_done_seen = True
        if task.done_at is None:
            task.done_at = _parse_ts((a.get("submission") or {}).get("submitted_at")) or now
            task.done_source = "canvas"
            return "closed"
        return None
    if task.canvas_done_seen:
        task.canvas_done_seen = False
        if task.done_source == "canvas" and task.done_at is not None:
            task.done_at = None
            task.done_source = None
            return "reopened"
    return None


async def sync_canvas_tasks(db: AsyncSession, user: User) -> dict:
    """Pull every assignment (with the student's submission) from every
    Canvas-linked course. Canvas stays the source of truth for its own items:
    existing not-done tasks get their title/due refreshed, and a task is
    closed once when Canvas first reports it submitted (see apply_canvas_done).
    Used by the endpoint AND the scheduler's auto-sync — the last-synced
    timestamp (advances only on success) and last error are recorded here
    so both paths share one bookkeeping code path."""
    try:
        result = await _sync_canvas_tasks_inner(db, user)
    except Exception as exc:
        await db.rollback()
        app = await db.get(AppSettings, 1)
        if app is not None:
            app.canvas_last_error = str(exc)[:500]
            await db.commit()
        raise
    app = await db.get(AppSettings, 1)
    if app is not None:
        app.canvas_last_synced_at = datetime.now(UTC)
        app.canvas_last_error = None
        await db.commit()
    return result


async def _sync_canvas_tasks_inner(db: AsyncSession, user: User) -> dict:
    from manabi_server.api.canvas import canvas_assignments, gather_limited

    courses = [
        c
        for c in (await _courses_by_id(db, user)).values()
        if c.canvas_course_id and c.archived_at is None
    ]
    existing = {
        t.canvas_assignment_id: t
        for t in (
            await db.execute(
                select(StudyTask).where(
                    StudyTask.user_id == user.id,
                    StudyTask.canvas_assignment_id.is_not(None),
                )
            )
        ).scalars()
    }
    app = await db.get(AppSettings, 1)
    now = now_manila()
    # New tasks: anything not past due, or past due since the semester began
    # (the old upcoming + overdue buckets). No semester row → last 60 days.
    window_start = app.semester_start if app is not None else (now - timedelta(days=60)).date()

    # One request per course (no bucket — the buckets hide submitted work),
    # fetched concurrently. Any failure fails the sync so the error is recorded.
    per_course = await gather_limited(
        canvas_assignments(c.canvas_course_id) for c in courses
    )

    created = updated = closed = reopened = 0
    # Grades ride on the same download: every linked score is refreshed each
    # sync, so a released score no longer waits for "Sync grades" on /grades.
    from manabi_server.api.grades import apply_canvas_scores, linked_items

    grades_updated = 0
    for course, assignments in zip(courses, per_course, strict=True):
        items = await linked_items(db, course.id)
        if items:
            grades_updated += apply_canvas_scores(items, assignments)[0]
        for a in assignments:
            aid = a.get("id")
            if not aid:
                continue
            due_utc = _parse_ts(a.get("due_at"))
            due_local = due_utc.astimezone(MANILA) if due_utc else None
            title = (a.get("name") or f"Assignment {aid}").strip()[:512]

            task = existing.get(aid)
            if task is None:
                if due_local is None or canvas_says_done(a):
                    continue  # undated, or already done on Canvas
                past_due = due_local < now
                if past_due and (
                    due_local.date() < window_start or not _expects_submission(a)
                ):
                    continue
                task = StudyTask(
                    user_id=user.id,
                    title=title,
                    course_id=course.id,
                    due_date=due_local.date(),
                    due_minute=minute_of(due_local),
                    source="canvas",
                    canvas_assignment_id=aid,
                    canvas_done_seen=False,
                )
                db.add(task)
                existing[aid] = task  # a Canvas course linked twice stays one task
                created += 1
                continue

            if task.done_at is None and due_local is not None:
                task.title = title
                task.due_date = due_local.date()
                task.due_minute = minute_of(due_local)
                updated += 1
            change = apply_canvas_done(task, a, now)
            if change == "closed":
                closed += 1
            elif change == "reopened":
                reopened += 1
    await db.commit()
    return {
        "created": created,
        "updated": updated,
        "closed": closed,
        "reopened": reopened,
        "grades_updated": grades_updated,
        "courses_checked": len(courses),
    }


@router.post("/canvas-sync", dependencies=[Depends(require_csrf)])
async def canvas_sync(
    user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> dict:
    return await sync_canvas_tasks(db, user)
