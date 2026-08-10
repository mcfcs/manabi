"""Voice lab: A/B compare the zero-shot vs fine-tuned Steven voice on any
line. Renders are cached per (variant, text)."""

from fastapi import APIRouter, Depends, HTTPException, Response
from manabi_core.models import Job, JobQueue, JobStatus, User, VoicePreview
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.db import get_db
from manabi_server.jobs.queue import VOICE_PREVIEW_TASK, defer_task
from manabi_server.security import get_default_user, require_csrf

router = APIRouter(prefix="/api/voice", tags=["voice"])

VARIANTS = ("base", "tuned")


class PreviewIn(BaseModel):
    text: str
    variant: str


@router.post("/preview", dependencies=[Depends(require_csrf)])
async def request_preview(
    data: PreviewIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Idempotent: returns the cached render if it exists, else queues one.
    The UI polls this until ready=true."""
    if data.variant not in VARIANTS:
        raise HTTPException(status_code=422, detail=f"variant must be one of {VARIANTS}")
    text = data.text.strip()[:500]
    if len(text) < 3:
        raise HTTPException(status_code=422, detail="Text too short")
    existing = (
        await db.execute(
            select(VoicePreview.id).where(
                VoicePreview.variant == data.variant, VoicePreview.text == text
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {"ready": True, "id": existing}
    in_flight = (
        await db.execute(
            select(Job).where(
                Job.job_type == "voice_preview",
                Job.status.in_([JobStatus.queued, JobStatus.running]),
                Job.payload["variant"].as_string() == data.variant,
                Job.payload["text"].as_string() == text,
            )
        )
    ).scalar_one_or_none()
    if in_flight is not None:
        return {"ready": False, "job_id": in_flight.id}
    job = Job(
        user_id=user.id,
        job_type="voice_preview",
        queue=JobQueue.gpu,
        payload={"text": text, "variant": data.variant},
    )
    db.add(job)
    await db.flush()
    job.procrastinate_job_id = await defer_task(
        VOICE_PREVIEW_TASK, "gpu", job_id=job.id, text=text, variant=data.variant
    )
    await db.commit()
    return {"ready": False, "job_id": job.id}


@router.get("/previews/{preview_id}")
async def preview_audio(
    preview_id: int, db: AsyncSession = Depends(get_db)
) -> Response:
    row = await db.get(VoicePreview, preview_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Preview not found")
    return Response(
        content=row.audio,
        media_type=row.mime,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )
