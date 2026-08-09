from fastapi import APIRouter, Depends, HTTPException
from manabi_core.models import Job, JobQueue, JobStatus, User
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.db import get_db
from manabi_server.jobs.queue import ECHO_TASK, defer_task
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
    from manabi_core.models import Module

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
