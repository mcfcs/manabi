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


async def sync_canvas_tasks(db: AsyncSession, user: User) -> dict:
    """Pull upcoming + overdue assignments from every Canvas-linked course.
    Canvas stays the source of truth for its own items: existing not-done
    tasks get their title/due refreshed; done tasks are never resurrected.
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
    from manabi_server.api.canvas import _canvas_get

    courses = [
        c
        for c in (await _courses_by_id(db, user)).values()
        if c.canvas_course_id and c.archived_at is None
    ]
    existing = {
        t.canvas_assignment_id: t
        for t in (
            await db.execute(
                select(StudyTask).where(StudyTask.canvas_assignment_id.is_not(None))
            )
        ).scalars()
    }

    created = updated = 0
    for course in courses:
        assignments: dict[int, dict] = {}
        for bucket in ("upcoming", "overdue"):
            data = await _canvas_get(
                f"/courses/{course.canvas_course_id}/assignments", {"bucket": bucket}
            )
            for a in data:
                if isinstance(a, dict) and a.get("id"):
                    assignments[a["id"]] = a

        for aid, a in assignments.items():
            due_raw = a.get("due_at")
            if not due_raw:
                continue
            due_utc = datetime.fromisoformat(due_raw.replace("Z", "+00:00"))
            due_local = due_utc.astimezone(MANILA)
            title = (a.get("name") or f"Assignment {aid}").strip()[:512]

            task = existing.get(aid)
            if task is None:
                db.add(
                    StudyTask(
                        user_id=user.id,
                        title=title,
                        course_id=course.id,
                        due_date=due_local.date(),
                        due_minute=minute_of(due_local),
                        source="canvas",
                        canvas_assignment_id=aid,
                    )
                )
                created += 1
            elif task.done_at is None:
                task.title = title
                task.due_date = due_local.date()
                task.due_minute = minute_of(due_local)
                updated += 1
    await db.commit()
    return {"created": created, "updated": updated, "courses_checked": len(courses)}


@router.post("/canvas-sync", dependencies=[Depends(require_csrf)])
async def canvas_sync(
    user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> dict:
    return await sync_canvas_tasks(db, user)
