"""Steven narrates readings — script + per-segment audio for one document.

GET  /api/documents/{id}/narration          status, segments, readiness
POST /api/documents/{id}/narration/prepare  (re)build the script and queue synthesis
GET  /api/narration/segments/{id}/audio     one segment's MP3
DELETE /api/documents/{id}/narration
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Response
from manabi_core.models import (
    Course,
    Document,
    Job,
    JobQueue,
    Module,
    Narration,
    NarrationSegment,
    User,
)
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.api.artifacts import _tts_available
from manabi_server.api.documents import _get_owned_document
from manabi_server.db import get_db
from manabi_server.jobs.queue import NARRATE_DOCUMENT_TASK, defer_task
from manabi_server.security import get_default_user, require_csrf
from manabi_server.services.narration import (
    DEFAULT_OPTIONS,
    NARRATE_JOB_TYPE,
    SCRIPT_VERSION,
    active_narration_job_filter,
    build_for_document,
    narratable,
    segment_rows,
)

router = APIRouter(prefix="/api", tags=["narration"])


class NarrationSegmentOut(BaseModel):
    id: int
    ord: int
    page_no: int
    kind: str  # title | abstract | heading | paragraph | caption
    text: str
    audio_ready: bool
    audio_id: int | None  # cache-buster; None until synthesized
    duration_ms: int | None


class NarrationOut(BaseModel):
    status: str | None  # None = not prepared yet | scripted | synthesizing | ready | failed
    error: str | None = None  # why it failed, so the viewer can offer a retry
    voice_available: bool
    job_active: bool
    job_id: int | None
    segment_count: int
    ready_count: int
    total_ms: int
    options: dict
    segments: list[NarrationSegmentOut]


class PrepareIn(BaseModel):
    force: bool = False  # re-script even when a narration already exists


class PrepareOut(BaseModel):
    job_id: int | None
    segment_count: int
    status: str


async def _active_job(db: AsyncSession, document_id: int) -> Job | None:
    return (
        await db.execute(
            select(Job)
            .where(*active_narration_job_filter(document_id))
            .order_by(Job.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _segments(db: AsyncSession, narration_id: int) -> list[NarrationSegmentOut]:
    rows = (
        await db.execute(
            select(
                NarrationSegment.id,
                NarrationSegment.ord,
                NarrationSegment.page_no,
                NarrationSegment.kind,
                NarrationSegment.text,
                NarrationSegment.duration_ms,
                NarrationSegment.audio.is_not(None),
            )
            .where(NarrationSegment.narration_id == narration_id)
            .order_by(NarrationSegment.ord)
        )
    ).all()
    return [
        NarrationSegmentOut(
            id=r[0],
            ord=r[1],
            page_no=r[2],
            kind=r[3],
            text=r[4],
            duration_ms=r[5],
            audio_ready=bool(r[6]),
            audio_id=r[0] if r[6] else None,
        )
        for r in rows
    ]


@router.get("/documents/{document_id}/narration")
async def get_narration(
    doc: Document = Depends(_get_owned_document),
    db: AsyncSession = Depends(get_db),
) -> NarrationOut:
    voice = await _tts_available(db)
    narration = (
        await db.execute(select(Narration).where(Narration.document_id == doc.id))
    ).scalar_one_or_none()
    job = await _active_job(db, doc.id)
    if narration is None:
        return NarrationOut(
            status=None,
            voice_available=voice,
            job_active=job is not None,
            job_id=job.id if job else None,
            segment_count=0,
            ready_count=0,
            total_ms=0,
            options=dict(DEFAULT_OPTIONS),
            segments=[],
        )
    segments = await _segments(db, narration.id)
    ready = [s for s in segments if s.audio_ready]
    return NarrationOut(
        status=narration.status,
        error=narration.error,
        voice_available=voice,
        job_active=job is not None,
        job_id=job.id if job else None,
        segment_count=len(segments),
        ready_count=len(ready),
        total_ms=sum(s.duration_ms or 0 for s in ready),
        options=narration.options or {},
        segments=segments,
    )


@router.post("/documents/{document_id}/narration/prepare", dependencies=[Depends(require_csrf)])
async def prepare_narration(
    data: PrepareIn | None = None,
    doc: Document = Depends(_get_owned_document),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> PrepareOut:
    """Build (or rebuild) the script and queue Steven's recording. Idempotent:
    an in-flight job is returned as is; an existing script is only rebuilt
    with force=true (or when it has no segments)."""
    force = bool(data and data.force)
    if not narratable(doc):
        raise HTTPException(status_code=409, detail="Narration is available for PDF readings only")
    if doc.extract_status.value != "ready":
        raise HTTPException(status_code=409, detail="The document is still being processed")

    active = await _active_job(db, doc.id)
    narration = (
        await db.execute(select(Narration).where(Narration.document_id == doc.id))
    ).scalar_one_or_none()
    if active is not None and force:
        raise HTTPException(
            status_code=409,
            detail="A recording is already running — cancel it before re-scripting",
        )
    if active is not None:
        count = (
            (
                await db.execute(
                    select(func.count()).where(NarrationSegment.narration_id == narration.id)
                )
            ).scalar_one()
            if narration
            else 0
        )
        return PrepareOut(job_id=active.id, segment_count=count, status="synthesizing")

    need_script = force or narration is None
    if narration is not None and not need_script:
        count = (
            await db.execute(
                select(func.count()).where(NarrationSegment.narration_id == narration.id)
            )
        ).scalar_one()
        need_script = count == 0
    if need_script:
        script = await asyncio.to_thread(build_for_document, doc)
        rows = segment_rows(script)
        if not rows:
            raise HTTPException(status_code=422, detail="Nothing readable was found in this PDF")
        if narration is None:
            narration = Narration(document_id=doc.id, options=dict(DEFAULT_OPTIONS))
            db.add(narration)
            await db.flush()
        else:
            await db.execute(
                delete(NarrationSegment).where(NarrationSegment.narration_id == narration.id)
            )
        narration.script_version = SCRIPT_VERSION
        narration.error = None
        for r in rows:
            db.add(NarrationSegment(narration_id=narration.id, **r))
        await db.flush()

    # Anything left without audio? Queue (or re-queue) synthesis.
    missing = (
        await db.execute(
            select(func.count()).where(
                NarrationSegment.narration_id == narration.id,
                NarrationSegment.audio.is_(None),
            )
        )
    ).scalar_one()
    total = (
        await db.execute(select(func.count()).where(NarrationSegment.narration_id == narration.id))
    ).scalar_one()
    if missing == 0:
        narration.status = "ready"
        await db.commit()
        return PrepareOut(job_id=None, segment_count=total, status="ready")

    narration.status = "synthesizing"
    job = Job(
        user_id=user.id,
        job_type=NARRATE_JOB_TYPE,
        queue=JobQueue.gpu,
        payload={"narration_id": narration.id},
        module_id=doc.module_id,
        document_id=doc.id,
    )
    db.add(job)
    await db.flush()
    job.procrastinate_job_id = await defer_task(
        NARRATE_DOCUMENT_TASK, "gpu", job_id=job.id, narration_id=narration.id
    )
    await db.commit()
    return PrepareOut(job_id=job.id, segment_count=total, status="synthesizing")


@router.delete("/documents/{document_id}/narration", dependencies=[Depends(require_csrf)])
async def delete_narration(
    doc: Document = Depends(_get_owned_document),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await db.execute(delete(Narration).where(Narration.document_id == doc.id))
    await db.commit()
    return {"ok": True}


@router.get("/narration/segments/{segment_id}/audio")
async def segment_audio(
    segment_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    row = (
        await db.execute(
            select(NarrationSegment.audio, NarrationSegment.mime)
            .join(Narration, Narration.id == NarrationSegment.narration_id)
            .join(Document, Document.id == Narration.document_id)
            .join(Module, Module.id == Document.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(NarrationSegment.id == segment_id, Course.user_id == user.id)
        )
    ).first()
    if row is None or row[0] is None:
        raise HTTPException(status_code=404, detail="Audio not synthesized yet")
    return Response(
        content=row[0],
        media_type=row[1] or "audio/mpeg",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )
