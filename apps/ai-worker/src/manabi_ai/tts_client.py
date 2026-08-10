"""HTTP client for the local TTS server (GPT-SoVITS api_v2, port 9880).

Long texts are synthesized in sentence groups (~280 chars — quality degrades
on very long inputs), concatenated, and encoded to mono 64kbps MP3 via
ffmpeg (iOS-safe; ~0.5 MB/min). Swapping engines (e.g. F5-TTS) only means
changing `_request_wav`.
"""

import asyncio
import logging
import re
import subprocess
import tempfile
from pathlib import Path

import httpx

from manabi_ai.config import get_settings

log = logging.getLogger("manabi_ai.tts")

GROUP_CHARS = 280


def split_sentences(text: str, group_chars: int = GROUP_CHARS) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    groups: list[str] = []
    buf = ""
    for s in sentences:
        if buf and len(buf) + len(s) + 1 > group_chars:
            groups.append(buf)
            buf = s
        else:
            buf = f"{buf} {s}".strip()
    if buf:
        groups.append(buf)
    return groups


async def _request_wav(client: httpx.AsyncClient, text: str) -> bytes:
    settings = get_settings()
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
    return r.content


def _encode_mp3(wav_paths: list[Path], out_path: Path) -> None:
    """Concatenate wavs and encode to mono 64kbps mp3."""
    list_file = out_path.with_suffix(".txt")
    list_file.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in wav_paths), encoding="utf-8"
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-ac", "1", "-b:a", "64k", str(out_path),
        ],
        check=True,
        capture_output=True,
        timeout=300,
    )


def _probe_duration_ms(path: Path) -> int:
    out = subprocess.run(
        [
            "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
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
