"""HTTP client for the local TTS server (GPT-SoVITS api_v2, port 9880).

Long texts are synthesized in sentence groups (~200 chars — quality degrades
on very long inputs), concatenated, and encoded to mono 64kbps MP3 via
ffmpeg (iOS-safe; ~0.5 MB/min). Swapping engines (e.g. F5-TTS) only means
changing `_request_wav`.
"""

import array
import asyncio
import io
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from glob import glob
from pathlib import Path

import httpx

from manabi_ai.config import get_settings
from manabi_ai.tts_verification import verify_wav

log = logging.getLogger("manabi_ai.tts")

GROUP_CHARS = 200

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
_ABBREVIATION_END = re.compile(
    r"\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|e\.g|i\.e|(?:[A-Za-z]\.)+[A-Za-z])\.$",
    re.IGNORECASE,
)
_SECTION_LABEL = re.compile(r"^(?:section|article|chapter|part)\s+[\w-]+[.:]$", re.IGNORECASE)


class TTSQualityError(ValueError):
    """A successful HTTP response contained unusable or suspiciously short speech."""


def _normalize_for_tts(text: str) -> str:
    """Make text friendlier to GPT-SoVITS: turn ellipses/dashes/line breaks into
    plain pauses and collapse repeats. Stray "…", "—", run-on lines and doubled
    punctuation are a common source of the model gasping or skipping words."""
    t = text or ""
    # Uppercase legal labels are words, not initialisms ("S E C T I O N").
    # Limit this to numbered labels so real acronyms elsewhere stay intact.
    t = re.sub(
        r"\b(SECTION|ARTICLE|CHAPTER|PART)(?=\s+(?:\d+|[IVXLCDM]+)\b)",
        lambda m: m[0].capitalize(),
        t,
    )
    t = t.replace("…", ". ")
    t = re.sub(r"\.{3,}", ". ", t)  # "..." → one pause
    t = re.sub(r"\s*[—–]\s*", ", ", t)  # em/en dash → comma pause
    t = re.sub(r"[ \t]*\n+[ \t]*", ". ", t)  # line breaks → sentence breaks
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s+([.,!?;:])", r"\1", t)  # no space before punctuation
    t = re.sub(r"([.,!?;:])\1+", r"\1", t)  # collapse repeated punctuation
    return t.strip()


def _speakable(text: str) -> bool:
    """Does this fragment contain anything a voice can actually say? A paragraph
    that opens mid-sentence ("… but for low-resource languages") normalizes to
    ". but for …" and then splits into a bare "." — which GPT-SoVITS rejects with
    a 400 that fails the whole recording. Punctuation-only fragments are silence,
    so drop them rather than asking the model to voice them."""
    return any(ch.isalnum() for ch in text)


def split_sentences(text: str, group_chars: int = GROUP_CHARS) -> list[str]:
    """One TTS fragment per sentence. GPT-SoVITS is most reliable synthesizing a
    single utterance at a time. Keep section labels and abbreviations attached;
    split long sentences at clauses where possible, then at word boundaries.
    Pieces with nothing to say are dropped."""
    text = _normalize_for_tts(text)
    sentences: list[str] = []
    for s in _SENT_END.split(text):
        s = s.strip()
        if sentences and (
            _ABBREVIATION_END.search(sentences[-1]) or _SECTION_LABEL.fullmatch(sentences[-1])
        ):
            sentences[-1] += " " + s
        elif _speakable(s):
            sentences.append(s)
    out: list[str] = []
    for s in sentences:
        while len(s) > group_chars:
            # A clause boundary keeps the voice's phrasing intact. Only fall
            # back to a word boundary when the sentence has no nearby pause.
            clauses = list(re.finditer(r"[,;:]\s+", s[: group_chars + 1]))
            if clauses and clauses[-1].start() >= group_chars // 3:
                cut = clauses[-1].start() + 1
            else:
                cut = s.rfind(" ", 0, group_chars + 1)
                cut = cut if cut > 0 else group_chars
            # Don't strand a tiny tail such as "by law.". It has too little
            # context for this voice and can repeatedly produce silence.
            min_tail = min(30, max(10, group_chars // 2))
            if len(s) - cut < min_tail:
                earlier = s.rfind(" ", 0, len(s) - min_tail + 1)
                if earlier > 0:
                    cut = earlier
            head = s[:cut].strip()
            if _speakable(head):
                out.append(head)
            s = s[cut:].strip()
        if _speakable(s):
            out.append(s)
    return out


def _validate_and_trim_wav(content: bytes, text: str, speed: float = 1.0) -> bytes:
    """Reject silent/early-stop takes; keep breathing room at the two edges.

    This is an acoustic sanity check, not word-level recognition. A large WAV
    can be almost entirely silence. Never trim an internal gap to disguise a
    missing clause, and never return the 'longest' take when every take fails.
    """
    try:
        with wave.open(io.BytesIO(content), "rb") as source:
            params = source.getparams()
            pcm = source.readframes(params.nframes)
    except (wave.Error, EOFError) as exc:
        raise TTSQualityError("Voice server returned an invalid WAV") from exc
    if params.sampwidth != 2 or params.comptype != "NONE" or not params.framerate:
        raise TTSQualityError("Voice server returned unsupported WAV audio")
    if len(pcm) != params.nframes * params.nchannels * params.sampwidth:
        raise TTSQualityError("Voice server returned a truncated WAV")
    samples = array.array("h", pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    window = max(1, params.framerate // 100) * params.nchannels  # 10 ms
    levels = [
        math.sqrt(sum(v * v for v in samples[i : i + window]) / len(samples[i : i + window]))
        for i in range(0, len(samples), window)
    ]
    active = [i for i, level in enumerate(levels) if level >= 184]  # -45 dBFS RMS
    words = len(re.findall(r"\b[\w]+(?:['’-][\w]+)*\b", text))
    voiced_seconds = len(active) / 100
    minimum = max(0.12, words / (10 * max(0.25, speed)))
    if not active or voiced_seconds < minimum:
        raise TTSQualityError(
            f"Voice stopped early or was silent ({voiced_seconds:.2f}s speech for {words} words)"
        )
    if any(b - a > 150 for a, b in zip(active, active[1:], strict=False)):
        raise TTSQualityError("Voice contains a long silent gap inside a sentence")
    # A lower threshold plus margins protects soft consonants and breaths.
    audible = [i for i, level in enumerate(levels) if level >= 58]  # -55 dBFS
    first = max(0, audible[0] - 10) * window
    last = min(len(samples), (audible[-1] + 19) * window)
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setparams(params)
        target.writeframes(pcm[first * 2 : last * 2])
    return output.getvalue()


async def _request_wav(client: httpx.AsyncClient, text: str, *, verify: bool = False) -> bytes:
    """Retry failed takes with fresh sampling instead of caching missing speech."""
    settings = get_settings()
    last: Exception | None = None
    for attempt in range(3):
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
                    # We already split sentences/clauses. The default cut5
                    # splits them AGAIN at commas and can return silent pieces.
                    "text_split_method": "cut0",
                    "fragment_interval": 0,
                    "seed": -1,
                    "media_type": "wav",
                },
                timeout=300,
            )
            r.raise_for_status()
            wav = await asyncio.to_thread(
                _validate_and_trim_wav, r.content, text, settings.tts_speed
            )
            if verify:
                problem = await asyncio.to_thread(verify_wav, wav, text)
                if problem:
                    raise TTSQualityError(problem)
            return wav
        except Exception as exc:  # noqa: BLE001
            last = exc
        log.warning("tts fragment retry (attempt %d): %s", attempt + 1, last)
    raise last or ValueError("tts request failed")


async def _fragment_wavs(
    client: httpx.AsyncClient, text: str, *, verify: bool = False
) -> list[bytes]:
    try:
        return [await _request_wav(client, text, verify=verify)]
    except TTSQualityError:
        # One bounded fallback: a stubborn sentence often works as shorter
        # clauses. Every clause must pass; a failure never silently drops one.
        parts = split_sentences(text, group_chars=max(40, len(text) // 2))
        if len(parts) < 2:
            raise
        return [await _request_wav(client, part, verify=verify) for part in parts]


def _encode_mp3(wav_paths: list[Path], out_path: Path) -> None:
    """Concatenate wavs and encode to mono 64kbps mp3."""
    list_file = out_path.with_suffix(".txt")
    list_file.write_text("\n".join(f"file '{p.as_posix()}'" for p in wav_paths), encoding="utf-8")
    subprocess.run(
        [
            _tool("ffmpeg"),
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-ac",
            "1",
            "-b:a",
            "64k",
            str(out_path),
        ],
        check=True,
        capture_output=True,
        timeout=300,
    )


def _probe_duration_ms(path: Path) -> int:
    out = subprocess.run(
        [
            _tool("ffprobe"),
            "-v",
            "quiet",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return int(float(out.stdout.decode().strip() or "0") * 1000)


async def synthesize(text: str, *, verify: bool = False) -> tuple[bytes, int]:
    """Returns (mp3 bytes, duration_ms)."""
    groups = split_sentences(text)
    if not groups:
        raise ValueError("empty text")
    with tempfile.TemporaryDirectory(prefix="manabi_tts_") as tmp:
        tmpdir = Path(tmp)
        wavs: list[Path] = []
        async with httpx.AsyncClient() as client:
            for group in groups:
                for wav in await _fragment_wavs(client, group, verify=verify):
                    p = tmpdir / f"{len(wavs):03d}.wav"
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
