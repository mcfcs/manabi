from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from manabi_core.models import Document, Job, JobQueue, JobStatus, Module, User
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.db import get_db
from manabi_server.jobs.queue import ECHO_TASK, cancel_task, defer_task
from manabi_server.security import get_default_user, require_csrf

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class JobOut(BaseModel):
    id: int
    job_type: str
    queue: JobQueue
    status: JobStatus
    progress_pct: int | None
    progress_note: str | None
    preview: str | None
    result: dict | None
    error: str | None


def _to_out(job: Job) -> JobOut:
    return JobOut(
        id=job.id,
        job_type=job.job_type,
        queue=job.queue,
        status=job.status,
        progress_pct=job.progress_pct,
        progress_note=job.progress_note,
        preview=job.preview,
        result=job.result,
        error=job.error,
    )


@router.post("/echo", dependencies=[Depends(require_csrf)])
async def create_echo_job(
    user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> JobOut:
    """Phase-0 spine test: a trivial gpu-queue job executed on phillmyeol."""
    job = Job(user_id=user.id, job_type="echo", queue=JobQueue.gpu, payload={})
    db.add(job)
    await db.flush()

    job.procrastinate_job_id = await defer_task(ECHO_TASK, "gpu", job_id=job.id)
    await db.commit()
    return _to_out(job)


@router.get("/active")
async def global_active_jobs(
    user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """All in-flight AI jobs with module context — powers the sidebar
    activity indicator."""
    rows = (
        await db.execute(
            select(Job, Module.title, Module.course_id)
            .outerjoin(Module, Module.id == Job.module_id)
            .where(
                Job.user_id == user.id,
                Job.status.in_([JobStatus.queued, JobStatus.running]),
                Job.job_type != "process_document",
            )
            .order_by(Job.id)
        )
    ).all()
    return [
        {
            "job_id": j.id,
            "job_type": j.job_type,
            "status": j.status,
            "progress_note": j.progress_note,
            "module_id": j.module_id,
            "module_title": title,
            "course_id": course_id,
        }
        for j, title, course_id in rows
    ]


class JobListItem(BaseModel):
    """A run, for the activity list. `preview` is deliberately absent: it is the
    rolling tail of a model's output and can be large."""

    id: int
    job_type: str
    queue: JobQueue
    status: JobStatus
    progress_note: str | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    module_id: int | None
    module_title: str | None
    course_id: int | None
    document_id: int | None
    document_title: str | None


@router.get("")
async def list_jobs(
    status: Annotated[list[JobStatus] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> list[JobListItem]:
    """Recent runs, newest first. Without this a generation that failed while
    you were on another page left no trace anywhere: /active only ever shows
    queued|running, and the per-tab failure banners key off a job id held in
    component state, which a reload throws away."""
    q = (
        select(Job, Module.title, Module.course_id, Document.filename)
        .outerjoin(Module, Module.id == Job.module_id)
        .outerjoin(Document, Document.id == Job.document_id)
        .where(Job.user_id == user.id)
        .order_by(Job.id.desc())
        .limit(limit)
    )
    if status:
        q = q.where(Job.status.in_(status))
    rows = (await db.execute(q)).all()
    return [
        JobListItem(
            id=j.id,
            job_type=j.job_type,
            queue=j.queue,
            status=j.status,
            progress_note=j.progress_note,
            error=j.error,
            created_at=j.created_at,
            started_at=j.started_at,
            finished_at=j.finished_at,
            module_id=j.module_id,
            module_title=title,
            course_id=course_id,
            document_id=j.document_id,
            document_title=filename,
        )
        for j, title, course_id, filename in rows
    ]


@router.get("/{job_id}")
async def get_job(
    job_id: int, user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> JobOut:
    job = (
        await db.execute(select(Job).where(Job.id == job_id, Job.user_id == user.id))
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_out(job)


@router.post("/{job_id}/cancel", dependencies=[Depends(require_csrf)])
async def cancel_job(
    job_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> JobOut:
    """Cancel a queued/running generation. Idempotent for terminal jobs. The
    optimistic status write clears the UI even if no live worker observes the
    abort (e.g. an orphaned job) — the worker reaper cleans procrastinate up."""
    job = (
        await db.execute(select(Job).where(Job.id == job_id, Job.user_id == user.id))
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in (JobStatus.succeeded, JobStatus.failed, JobStatus.cancelled):
        return _to_out(job)  # no-op

    if job.procrastinate_job_id is not None:
        import contextlib

        # Proceed with the DB flip even if procrastinate can't be reached.
        with contextlib.suppress(Exception):
            await cancel_task(job.procrastinate_job_id)
    # Compare-and-set: never clobber a job that JUST reached a terminal state.
    await db.execute(
        update(Job)
        .where(Job.id == job.id, Job.status.in_([JobStatus.queued, JobStatus.running]))
        .values(
            status=JobStatus.cancelled,
            progress_note="Cancelled",
            finished_at=datetime.now(UTC),
        )
    )
    await db.commit()
    await db.refresh(job)
    return _to_out(job)
