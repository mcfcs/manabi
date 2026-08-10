"""GPU-queue TTS tasks: lecture narration + spoken chat replies.

Audio flows back through Postgres (bytea) — the worker has no file path to
the app server's storage. Idempotent per segment so retries are safe and the
UI can play early segments while later ones render.
"""

import logging
import re
from datetime import UTC, datetime

from manabi_core.models import (
    Artifact,
    ChatMessage,
    Job,
    JobStatus,
    LectureAudio,
    SpeechClip,
)
from sqlalchemy import select

from manabi_ai.app import app
from manabi_ai.config import get_settings
from manabi_ai.db import session_factory
from manabi_ai.tts_client import synthesize

log = logging.getLogger("manabi_ai.tts")


def _chat_text_for_tts(text: str) -> str:
    """Chat answers aren't written under the spoken-text rules — strip
    markdown before synthesis."""
    text = re.sub(r"[*#`_|\[\]]", "", text or "")
    return re.sub(r"\s+", " ", text).strip()


@app.task(name="manabi_ai.tasks.synthesize_lecture", queue="gpu", retry=1)
async def synthesize_lecture(job_id: int, artifact_id: int) -> None:
    settings = get_settings()
    async with session_factory()() as db:
        job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()
        job.status = JobStatus.running
        job.started_at = datetime.now(UTC)
        await db.commit()
        try:
            if not settings.tts_enabled:
                raise RuntimeError("TTS is not configured on this worker")
            artifact = (
                await db.execute(select(Artifact).where(Artifact.id == artifact_id))
            ).scalar_one()
            segments = (artifact.content or {}).get("segments", [])
            existing = {
                r.segment_index
                for r in (
                    await db.execute(
                        select(LectureAudio.segment_index).where(
                            LectureAudio.artifact_id == artifact_id
                        )
                    )
                ).scalars()
            }
            todo = [
                (i, s) for i, s in enumerate(segments) if i not in existing
            ]
            for done, (i, seg) in enumerate(todo):
                job.progress_pct = int(100 * done / max(len(todo), 1))
                job.progress_note = f"Synthesizing segment {i + 1}/{len(segments)}"
                await db.commit()
                audio, duration = await synthesize(seg.get("spoken_text", ""))
                db.add(
                    LectureAudio(
                        artifact_id=artifact_id,
                        segment_index=i,
                        audio=audio,
                        mime="audio/mpeg",
                        duration_ms=duration,
                        voice=settings.tts_voice,
                    )
                )
                await db.commit()  # per-segment: playable immediately
            job.status = JobStatus.succeeded
            job.progress_pct = 100
            job.progress_note = "Voice ready"
            job.finished_at = datetime.now(UTC)
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            log.exception("lecture synthesis failed")
            await db.rollback()
            job.status = JobStatus.failed
            job.error = f"{type(exc).__name__}: {str(exc)[:400]}"
            job.finished_at = datetime.now(UTC)
            await db.commit()


@app.task(name="manabi_ai.tasks.speak_text", queue="gpu", retry=1)
async def speak_text(job_id: int, message_id: int) -> None:
    settings = get_settings()
    async with session_factory()() as db:
        job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()
        job.status = JobStatus.running
        job.started_at = datetime.now(UTC)
        await db.commit()
        try:
            if not settings.tts_enabled:
                raise RuntimeError("TTS is not configured on this worker")
            existing = (
                await db.execute(
                    select(SpeechClip).where(SpeechClip.chat_message_id == message_id)
                )
            ).scalar_one_or_none()
            if existing is None:
                message = (
                    await db.execute(
                        select(ChatMessage).where(ChatMessage.id == message_id)
                    )
                ).scalar_one()
                audio, duration = await synthesize(_chat_text_for_tts(message.content))
                db.add(
                    SpeechClip(
                        chat_message_id=message_id,
                        audio=audio,
                        mime="audio/mpeg",
                        duration_ms=duration,
                        voice=settings.tts_voice,
                    )
                )
            job.status = JobStatus.succeeded
            job.progress_pct = 100
            job.finished_at = datetime.now(UTC)
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            log.exception("speech synthesis failed")
            await db.rollback()
            job.status = JobStatus.failed
            job.error = f"{type(exc).__name__}: {str(exc)[:400]}"
            job.finished_at = datetime.now(UTC)
            await db.commit()


@app.task(name="manabi_ai.tasks.voice_preview", queue="gpu", retry=1)
async def voice_preview(job_id: int, text: str, variant: str) -> None:
    """Voice-lab A/B render: synthesize one line with the requested weight
    set (base = pretrained zero-shot, tuned = fine-tuned) and cache it."""
    from manabi_core.models import VoicePreview

    from manabi_ai.tts_client import synthesize_variant

    settings = get_settings()
    async with session_factory()() as db:
        job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()
        job.status = JobStatus.running
        job.started_at = datetime.now(UTC)
        job.progress_note = f"Rendering {variant} voice"
        await db.commit()
        try:
            if not settings.tts_enabled:
                raise RuntimeError("TTS is not configured on this worker")
            text = text.strip()[:500]
            existing = (
                await db.execute(
                    select(VoicePreview).where(
                        VoicePreview.variant == variant, VoicePreview.text == text
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                audio, duration = await synthesize_variant(text, variant)
                db.add(
                    VoicePreview(
                        variant=variant,
                        text=text,
                        audio=audio,
                        mime="audio/mpeg",
                        duration_ms=duration,
                    )
                )
            job.status = JobStatus.succeeded
            job.progress_pct = 100
            job.finished_at = datetime.now(UTC)
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            log.exception("voice preview failed")
            await db.rollback()
            job.status = JobStatus.failed
            job.error = f"{type(exc).__name__}: {str(exc)[:400]}"
            job.finished_at = datetime.now(UTC)
            await db.commit()
