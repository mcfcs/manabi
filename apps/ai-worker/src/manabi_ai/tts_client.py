"""HTTP client for the local TTS server (GPT-SoVITS api_v2, port 9880).

Long texts are synthesized in sentence groups (~200 chars — quality degrades
on very long inputs), levelled, joined with pauses that follow the
punctuation, and encoded to mono 96kbps MP3 via ffmpeg (iOS-safe;
~0.7 MB/min). Swapping engines (e.g. F5-TTS) only means changing
`_request_wav`.
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
    return [part for part, _ in split_parts(text, group_chars)]


def split_parts(text: str, group_chars: int = GROUP_CHARS) -> list[tuple[str, str]]:
    """split_sentences, with how each piece ends: "sentence", "clause" (cut at
    a comma inside a long sentence) or "word" (cut mid-phrase). The boundary
    sets the pause after it — every gap used to be the same ~0.3 s, so a comma
    inside a sentence sounded like a full stop and a paragraph end like a
    comma."""
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
    out: list[tuple[str, str]] = []
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
                out.append((head, "clause" if head[-1] in ",;:" else "word"))
            s = s[cut:].strip()
        if _speakable(s):
            out.append((s, "sentence"))
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
    # A lower threshold plus margins protects soft consonants and breaths. The
    # margins are short on purpose: the pause between pieces is added by
    # synthesize() according to the boundary, not left to trimming.
    audible = [i for i, level in enumerate(levels) if level >= 58]  # -55 dBFS
    first = max(0, audible[0] - HEAD_MARGIN_MS // 10) * window
    last = min(len(samples), (audible[-1] + TAIL_MARGIN_MS // 10) * window)
    piece = _level(samples[first:last], levels[audible[0] : audible[-1] + 1])
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setparams(params)
        target.writeframes(piece.tobytes() if sys.byteorder == "little" else _swapped(piece))
    return output.getvalue()


HEAD_MARGIN_MS = 50
TAIL_MARGIN_MS = 120
# Silence added after a piece, by how it ends (on top of the two margins). A
# comma inside a sentence breathes, a full stop rests, a paragraph or a
# heading leaves room to take it in.
PAUSE_MS = {"word": 0, "clause": 60, "sentence": 250}
END_PAUSE_MS = {"paragraph": 480, "heading": 680, "title": 830}
# Every take is sampled on its own, so loudness drifted from one sentence to
# the next. Level each to the same speech loudness (-20 dBFS RMS over the
# voiced 10 ms windows), within limits, and never past -0.3 dBFS peak.
TARGET_RMS = 3277
GAIN_RANGE = (0.5, 2.5)
PEAK_CEILING = 31760


def _level(samples: "array.array", levels: list[float]) -> "array.array":
    voiced = [v for v in levels if v >= 184] or levels
    rms = math.sqrt(sum(v * v for v in voiced) / max(1, len(voiced)))
    peak = max((abs(v) for v in samples), default=0)
    if rms <= 0 or peak <= 0:
        return samples
    gain = min(max(TARGET_RMS / rms, GAIN_RANGE[0]), GAIN_RANGE[1], PEAK_CEILING / peak)
    if abs(gain - 1) < 0.02:
        return samples
    return array.array("h", (int(v * gain) for v in samples))


def _swapped(piece: "array.array") -> bytes:
    copy = array.array("h", piece)
    copy.byteswap()
    return copy.tobytes()


def _silence_wav(like: bytes, ms: int) -> bytes:
    """`ms` of silence in the same WAV format as `like`, so ffmpeg's concat
    demuxer can join it without re-encoding."""
    with wave.open(io.BytesIO(like), "rb") as source:
        params = source.getparams()
    frames = params.framerate * ms // 1000
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setparams(params)
        target.writeframes(b"\x00" * frames * params.nchannels * params.sampwidth)
    return output.getvalue()


# Silent takes are intermittent (sampling is seeded per request): "A main
# function serves as the driver." failed three takes in a row inside a lecture
# and passed twice straight after. Five takes before giving up.
TAKE_ATTEMPTS = 5


def mood_for(text: str, default: str = "calm") -> str:
    """The delivery for one piece: a question asks, an exclamation lands
    harder, anything else takes the caller's default (calm narration, warm
    chat). Only moods with a clip in tts_refs change anything."""
    end = text.rstrip(" \"'”’)")[-1:]
    if end == "?":
        return "question"
    if end == "!":
        return "emphatic"
    return default


def reference(mood: str = "calm") -> tuple[str, str]:
    """(reference wav, its transcript) for a mood; the calm default when the
    bank has no clip for it."""
    settings = get_settings()
    return settings.tts_ref_bank.get(mood) or (settings.tts_ref_audio, settings.tts_ref_text)


async def _request_wav(
    client: httpx.AsyncClient, text: str, *, verify: bool = False, mood: str = "calm"
) -> bytes:
    """Retry failed takes with fresh sampling instead of caching missing speech."""
    settings = get_settings()
    ref_audio, ref_text = reference(mood)
    last: Exception | None = None
    for attempt in range(TAKE_ATTEMPTS):
        try:
            r = await client.get(
                f"{settings.tts_url.rstrip('/')}/tts",
                params={
                    "text": text,
                    "text_lang": "en",
                    "ref_audio_path": ref_audio,
                    "prompt_text": ref_text,
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
    client: httpx.AsyncClient, text: str, *, verify: bool = False, mood: str = "calm"
) -> list[tuple[bytes, str]]:
    """Takes for one group, each with the boundary after it ("" = the group's
    own end, decided by the caller)."""
    try:
        return [(await _request_wav(client, text, verify=verify, mood=mood), "")]
    except TTSQualityError:
        # One bounded fallback: a stubborn sentence often works as shorter
        # clauses. Every clause must pass; a failure never silently drops one.
        parts = split_parts(text, group_chars=max(40, len(text) // 2))
        if len(parts) < 2:
            raise
        out = [
            (await _request_wav(client, part, verify=verify, mood=mood), b) for part, b in parts
        ]
        out[-1] = (out[-1][0], "")
        return out


def _encode_mp3(wav_paths: list[Path], out_path: Path) -> None:
    """Concatenate wavs and encode to mono 96kbps mp3 (64k smeared sibilants)."""
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
            "96k",
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


TINY_GROUP_WORDS = 4


def merge_tiny_groups(groups: list[str], max_chars: int = GROUP_CHARS) -> list[str]:
    """Fold sentences under TINY_GROUP_WORDS words into a neighbour.

    The v2ProPlus voice returns silence for a lone two-word utterance: every
    new lecture opened with "Welcome back." as its own group, failed the
    quality check three times, and the whole recording failed. Spoken with the
    sentence after it, it is fine."""
    return [g for g, _ in merge_tiny_parts([(g, "sentence") for g in groups], max_chars)]


def merge_tiny_parts(
    parts: list[tuple[str, str]], max_chars: int = GROUP_CHARS
) -> list[tuple[str, str]]:
    """merge_tiny_groups over (text, boundary) pairs: a merged piece ends the
    way its last part ends."""
    out: list[tuple[str, str]] = []
    carry = ""
    for g, boundary in parts:
        g = f"{carry} {g}".strip() if carry else g
        carry = ""
        if len(g.split()) < TINY_GROUP_WORDS:
            carry = g
            continue
        out.append((g, boundary))
    if carry:
        if out and len(out[-1][0]) + len(carry) + 1 <= max_chars * 2:
            out[-1] = (f"{out[-1][0]} {carry}", "sentence")
        else:
            out.append((carry, "sentence"))
    return out


def pause_after(boundary: str, *, last: bool, end: str) -> int:
    """Silence (ms) to add after a piece. `end` is how the whole text ends:
    "paragraph", "heading", "title" — or "none" when the caller joins the
    audio itself (chat replies, previews)."""
    if last:
        return END_PAUSE_MS.get(end, 0)
    return PAUSE_MS.get(boundary or "sentence", PAUSE_MS["sentence"])


async def synthesize(
    text: str, *, verify: bool = False, end: str = "none", mood: str = "calm"
) -> tuple[bytes, int]:
    """Returns (mp3 bytes, duration_ms). `end` adds the pause that should
    follow this text when it is one paragraph or heading of a longer reading
    (see END_PAUSE_MS); `mood` is the default delivery, overridden per
    sentence for questions and exclamations (mood_for)."""
    groups = merge_tiny_parts(split_parts(text))
    if not groups:
        raise ValueError("empty text")
    with tempfile.TemporaryDirectory(prefix="manabi_tts_") as tmp:
        tmpdir = Path(tmp)
        wavs: list[Path] = []

        def add(audio: bytes) -> None:
            p = tmpdir / f"{len(wavs):03d}.wav"
            p.write_bytes(audio)
            wavs.append(p)

        async with httpx.AsyncClient() as client:
            for n, (group, boundary) in enumerate(groups):
                takes = await _fragment_wavs(
                    client, group, verify=verify, mood=mood_for(group, mood)
                )
                for k, (wav, inner) in enumerate(takes):
                    add(wav)
                    last_take = k == len(takes) - 1
                    pause = pause_after(
                        inner or boundary,
                        last=last_take and n == len(groups) - 1,
                        end=end,
                    )
                    if pause:
                        add(_silence_wav(wav, pause))
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
