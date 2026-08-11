"""HTTP client for the local TTS server (GPT-SoVITS api_v2, port 9880).

Long texts are synthesized in sentence groups (~280 chars — quality degrades
on very long inputs), concatenated, and encoded to mono 64kbps MP3 via
ffmpeg (iOS-safe; ~0.5 MB/min). Swapping engines (e.g. F5-TTS) only means
changing `_request_wav`.
"""

import asyncio
import logging
import os
import re
import shutil
import subprocess
import tempfile
from glob import glob
from pathlib import Path

import httpx

from manabi_ai.config import get_settings

log = logging.getLogger("manabi_ai.tts")

GROUP_CHARS = 280

_ffmpeg_dir: str | None = None


def _tool(name: str) -> str:
    """Resolve ffmpeg/ffprobe: PATH first, then the winget install dir."""
    global _ffmpeg_dir
    found = shutil.which(name)
    if found:
        return found
    if _ffmpeg_dir is None:
        pattern = os.path.expandvars(
            r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\ffmpeg-*\bin"
        )
        dirs = glob(pattern)
        _ffmpeg_dir = dirs[0] if dirs else ""
    candidate = os.path.join(_ffmpeg_dir, f"{name}.exe") if _ffmpeg_dir else ""
    if candidate and os.path.exists(candidate):
        return candidate
    raise RuntimeError(
        f"{name} not found — install ffmpeg (winget install Gyan.FFmpeg) on the "
        "machine running the GPU worker"
    )


_SENT_END = re.compile(r"(?<=[.!?…])\s+")


def _normalize_for_tts(text: str) -> str:
    """Make text friendlier to GPT-SoVITS: turn ellipses/dashes/line breaks into
    plain pauses and collapse repeats. Stray "…", "—", run-on lines and doubled
    punctuation are a common source of the model gasping or skipping words."""
    t = text or ""
    t = t.replace("…", ". ")
    t = re.sub(r"\.{3,}", ". ", t)  # "..." → one pause
    t = re.sub(r"\s*[—–]\s*", ", ", t)  # em/en dash → comma pause
    t = re.sub(r"[ \t]*\n+[ \t]*", ". ", t)  # line breaks → sentence breaks
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s+([.,!?;:])", r"\1", t)  # no space before punctuation
    t = re.sub(r"([.,!?;:])\1+", r"\1", t)  # collapse repeated punctuation
    return t.strip()


def split_sentences(text: str, group_chars: int = GROUP_CHARS) -> list[str]:
    """One TTS fragment per sentence. GPT-SoVITS is most reliable synthesizing a
    single utterance at a time — combining several sentences into one request is
    what made it gasp through and skip the earlier ones. Over-long sentences are
    hard-wrapped on spaces; empty pieces are dropped."""
    text = _normalize_for_tts(text)
    out: list[str] = []
    for s in _SENT_END.split(text):
        s = s.strip()
        while len(s) > group_chars:
            cut = s.rfind(" ", 0, group_chars)
            cut = cut if cut > 0 else group_chars
            head = s[:cut].strip()
            if head:
                out.append(head)
            s = s[cut:].strip()
        if s:
            out.append(s)
    return out


async def _request_wav(client: httpx.AsyncClient, text: str) -> bytes:
    """Synthesize one fragment. Retries once on a transient failure or a
    suspiciously tiny response (an error page / empty clip), so a single bad
    fragment doesn't silently drop words from the middle of a reply."""
    settings = get_settings()
    last: Exception | None = None
    for attempt in range(2):
        try:
            r = await client.get(
                f"{settings.tts_url.rstrip('/')}/tts",
                params={
                    "text": text,
                    "text_lang": "en",
                    "ref_audio_path": settings.tts_ref_audio,
                    "prompt_text": settings.tts_ref_text,
                    "prompt_lang": "en",
                    "speed_factor": settings.tts_speed,
                    "media_type": "wav",
                },
                timeout=300,
            )
            r.raise_for_status()
            if len(r.content) > 1000:  # a real WAV, not an error / empty body
                return r.content
            last = ValueError(f"tiny TTS response ({len(r.content)} bytes)")
        except Exception as exc:  # noqa: BLE001
            last = exc
        log.warning("tts fragment retry (attempt %d): %s", attempt + 1, last)
    raise last or ValueError("tts request failed")


def _encode_mp3(wav_paths: list[Path], out_path: Path) -> None:
    """Concatenate wavs and encode to mono 64kbps mp3."""
    list_file = out_path.with_suffix(".txt")
    list_file.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in wav_paths), encoding="utf-8"
    )
    subprocess.run(
        [
            _tool("ffmpeg"), "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-ac", "1", "-b:a", "64k", str(out_path),
        ],
        check=True,
        capture_output=True,
        timeout=300,
    )


def _probe_duration_ms(path: Path) -> int:
    out = subprocess.run(
        [
            _tool("ffprobe"), "-v", "quiet", "-show_entries", "format=duration",
            "-of", "csv=p=0", str(path),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return int(float(out.stdout.decode().strip() or "0") * 1000)


async def synthesize(text: str) -> tuple[bytes, int]:
    """Returns (mp3 bytes, duration_ms)."""
    groups = split_sentences(text)
    if not groups:
        raise ValueError("empty text")
    with tempfile.TemporaryDirectory(prefix="manabi_tts_") as tmp:
        tmpdir = Path(tmp)
        wavs: list[Path] = []
        async with httpx.AsyncClient() as client:
            for i, group in enumerate(groups):
                wav = await _request_wav(client, group)
                p = tmpdir / f"{i:03d}.wav"
                p.write_bytes(wav)
                wavs.append(p)
        out = tmpdir / "out.mp3"
        await asyncio.to_thread(_encode_mp3, wavs, out)
        duration = await asyncio.to_thread(_probe_duration_ms, out)
        return out.read_bytes(), duration


async def set_weights(gpt_path: str, sovits_path: str) -> None:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=120) as client:
        for endpoint, path in (
            ("set_gpt_weights", gpt_path),
            ("set_sovits_weights", sovits_path),
        ):
            r = await client.get(
                f"{settings.tts_url.rstrip('/')}/{endpoint}",
                params={"weights_path": path},
            )
            r.raise_for_status()


async def synthesize_variant(text: str, variant: str) -> tuple[bytes, int]:
    """Synthesize with a specific weight set. "base" temporarily swaps to the
    pretrained weights and always restores the tuned set afterwards."""
    settings = get_settings()
    use_base = variant == "base"
    has_tuned = bool(settings.tts_tuned_gpt and settings.tts_tuned_sovits)
    if use_base:
        await set_weights(settings.tts_base_gpt, settings.tts_base_sovits)
    try:
        return await synthesize(text)
    finally:
        if use_base and has_tuned:
            await set_weights(settings.tts_tuned_gpt, settings.tts_tuned_sovits)
