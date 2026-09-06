"""Narration orchestration shared by the API (async) and the CPU worker (sync).

Script building is CPU-only and fast (PyMuPDF over the stored PDF); the GPU
worker then fills in audio per segment (manabi_ai.tasks.narrate_document).
"""

from __future__ import annotations

import logging

from manabi_core.models import (
    AINodeHeartbeat,
    AppSettings,
    Document,
    DocumentKind,
    Job,
    JobQueue,
    JobStatus,
    Narration,
    NarrationSegment,
)
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from manabi_server.processing.narration_script import Script, build_script_from_path

log = logging.getLogger("manabi_server")

SCRIPT_VERSION = 1
NARRATE_JOB_TYPE = "narrate_document"
DEFAULT_OPTIONS = {
    "skip_footnotes": True,
    "skip_references": True,
    "skip_citations": True,
    "skip_front_matter": True,
}


def build_for_document(doc: Document) -> Script:
    """Layout pass over the document's (normalized) PDF."""
    from manabi_server.processing.pipeline import parse_source_path

    return build_script_from_path(str(parse_source_path(doc)))


def segment_rows(script: Script) -> list[dict]:
    return [
        {
            "ord": s.ord,
            "page_no": s.page_no,
            "kind": s.kind,
            "text": s.text,
            "spoken_text": s.spoken_text,
        }
        for s in script.segments
    ]


def narratable(doc: Document) -> bool:
    return doc.kind == DocumentKind.pdf and doc.processing_mode != "render_only"


# ── sync side (CPU worker, after a successful parse) ────────────────────────


def tts_available_sync(db: Session) -> bool:
    hb = db.execute(
        select(AINodeHeartbeat).order_by(AINodeHeartbeat.last_seen_at.desc()).limit(1)
    ).scalar_one_or_none()
    return bool(hb and (hb.gpu_info or {}).get("tts"))


def prepare_narration_sync(db: Session, doc: Document) -> int | None:
    """Script the document and queue synthesis when the master switch is on and
    a voice is available. Returns the Job id, or None when skipped. Never
    raises: the parse already succeeded and must stay that way."""
    try:
        settings = db.get(AppSettings, 1)
        if not settings or not settings.narration_enabled or not narratable(doc):
            return None
        if not tts_available_sync(db):
            log.info("narration: voice offline, not queuing doc %s", doc.id)
            return None
        script = build_for_document(doc)
        rows = segment_rows(script)
        if not rows:
            return None
        narration = db.execute(
            select(Narration).where(Narration.document_id == doc.id)
        ).scalar_one_or_none()
        if narration is None:
            narration = Narration(document_id=doc.id, options=dict(DEFAULT_OPTIONS))
            db.add(narration)
            db.flush()
        else:
            db.execute(
                delete(NarrationSegment).where(NarrationSegment.narration_id == narration.id)
            )
        narration.status = "synthesizing"
        narration.script_version = SCRIPT_VERSION
        narration.error = None
        for r in rows:
            db.add(NarrationSegment(narration_id=narration.id, **r))
        from manabi_core.models import User

        owner = db.execute(select(User).order_by(User.id).limit(1)).scalar_one_or_none()
        job = Job(
            user_id=owner.id if owner else None,
            job_type=NARRATE_JOB_TYPE,
            queue=JobQueue.gpu,
            payload={"narration_id": narration.id},
            module_id=doc.module_id,
            document_id=doc.id,
        )
        db.add(job)
        db.flush()
        from manabi_server.jobs.queue import NARRATE_DOCUMENT_TASK, defer_task_sync

        job.procrastinate_job_id = defer_task_sync(
            NARRATE_DOCUMENT_TASK, "gpu", job_id=job.id, narration_id=narration.id
        )
        db.commit()
        log.info("narration: queued %d segments for doc %s (job %s)", len(rows), doc.id, job.id)
        return job.id
    except Exception:  # noqa: BLE001 — best effort
        log.exception("narration: auto-prepare failed for doc %s", doc.id)
        db.rollback()
        return None


def active_narration_job_filter(document_id: int):
    """SQLAlchemy criteria for an in-flight narrate job of one document."""
    return (
        Job.document_id == document_id,
        Job.job_type == NARRATE_JOB_TYPE,
        Job.status.in_([JobStatus.queued, JobStatus.running]),
    )
