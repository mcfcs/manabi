"""Speech-to-text for chat voice input: faster-whisper small/int8 on CPU.
Model loads lazily on first use (~1 GB download on first run)."""

import asyncio
import logging
import tempfile
from pathlib import Path

log = logging.getLogger("manabi.stt")

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        log.info("loading faster-whisper small (int8, cpu)")
        _model = WhisperModel("small", device="cpu", compute_type="int8")
    return _model


def _transcribe_sync(path: str) -> str:
    model = _get_model()
    segments, _info = model.transcribe(path, language="en", vad_filter=True)
    return " ".join(s.text.strip() for s in segments).strip()


async def transcribe(audio_bytes: bytes, suffix: str = ".webm") -> str:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        path = f.name
    try:
        return await asyncio.to_thread(_transcribe_sync, path)
    finally:
        await asyncio.to_thread(Path(path).unlink, True)
