"""A reading's narration as one downloadable MP3.

Steven's audio is stored per paragraph (narration_segments.audio, mono 96 kbps
MP3). The download joins them with the Listen bar's pauses, without
re-encoding (`-c copy`), and writes a fresh length header for the whole file:
gluing the MP3 bytes together would keep the first clip's header, and an
iPhone then shows a 109-minute reading as a few seconds long.

Built on first request and cached under storage/narration-downloads/, keyed
by the segments' ids and audio sizes, so a re-recording builds a new file."""

import asyncio
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from glob import glob
from pathlib import Path

from manabi_core.models import NarrationSegment
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.storage.files import NARRATION_DOWNLOADS, storage_root

# The Listen bar's pauses (NarrationBar.tsx GAP_MS / GAP_HEADING_MS): the
# download should sound like listening in the app.
GAP_MS = 250
GAP_HEADING_MS = 500

_ffmpeg_dir: str | None = None


def tool(name: str) -> str:
    """Resolve ffmpeg/ffprobe: PATH first, then the winget install dir (the
    same lookup as the GPU worker's tts_client)."""
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
    raise RuntimeError(f"{name} not found — install ffmpeg (winget install Gyan.FFmpeg)")


class NarrationNotReady(Exception):
    def __init__(self, missing: int) -> None:
        super().__init__(f"{missing} paragraphs not recorded yet")
        self.missing = missing


def concat_plan(kinds: list[str]) -> list[tuple[str, int]]:
    """("segment", index) and ("silence", ms) in playing order."""
    plan: list[tuple[str, int]] = []
    for i, kind in enumerate(kinds):
        if i:
            plan.append(("silence", GAP_HEADING_MS if kind in ("heading", "title") else GAP_MS))
        plan.append(("segment", i))
    return plan


def export_key(rows: list[tuple[int, int]]) -> str:
    """(segment id, audio size) per paragraph → a short stable hash."""
    h = hashlib.sha1(",".join(f"{i}:{n}" for i, n in rows).encode())
    return h.hexdigest()[:12]


_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def download_filename(filename: str) -> str:
    """The reading's own name with .mp3 — minus characters Windows, iOS Files
    or Android refuse in a file name."""
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    stem = _UNSAFE.sub(" ", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" .")
    return f"{stem or 'reading'}.mp3"


def _probe_rate(path: Path) -> str:
    out = subprocess.run(
        [tool("ffprobe"), "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    return out.stdout.strip() or "32000"


def build_mp3(
    clips: list[Path], kinds: list[str], out: Path, *, title: str, album: str | None
) -> None:
    """Join the clips with the plan's silences into `out` (ffmpeg, no
    re-encode of the speech). The silences are encoded once in the clips'
    own format so the concat demuxer can copy every packet."""
    ffmpeg = tool("ffmpeg")
    work = out.parent
    rate = _probe_rate(clips[0])
    silences: dict[int, Path] = {}
    for ms in {ms for kind, ms in concat_plan(kinds) if kind == "silence"}:
        silences[ms] = work / f"silence-{ms}.mp3"
        subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-f", "lavfi",
             "-i", f"anullsrc=r={rate}:cl=mono", "-t", f"{ms / 1000:.3f}",
             "-ac", "1", "-b:a", "96k", str(silences[ms])],
            check=True, capture_output=True,
        )
    files = [clips[v] if kind == "segment" else silences[v] for kind, v in concat_plan(kinds)]
    listing = work / "concat.txt"
    listing.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in files), encoding="utf-8"
    )
    meta = ["-metadata", f"title={title}", "-metadata", "artist=Steven"]
    if album:
        meta += ["-metadata", f"album={album}"]
    subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c", "copy", "-map_metadata", "-1", *meta,
         "-id3v2_version", "3", "-write_xing", "1", str(out)],
        check=True, capture_output=True,
    )


_locks: dict[int, asyncio.Lock] = {}


async def ensure_mp3(
    db: AsyncSession, *, narration_id: int, document_id: int, title: str, album: str | None
) -> Path:
    """The cached MP3 for this narration, built first if needed. Raises
    NarrationNotReady while paragraphs are still unrecorded."""
    # (id, kind, audio size) — size NULL = not recorded yet; no audio loaded
    rows = (
        await db.execute(
            select(NarrationSegment.id, NarrationSegment.kind, func.length(NarrationSegment.audio))
            .where(NarrationSegment.narration_id == narration_id)
            .order_by(NarrationSegment.ord)
        )
    ).all()
    missing = sum(1 for _id, _kind, size in rows if size is None)
    if not rows or missing:
        raise NarrationNotReady(missing or 1)

    folder = storage_root() / NARRATION_DOWNLOADS
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{document_id}-{export_key([(i, n) for i, _k, n in rows])}.mp3"
    if out.exists():
        return out
    async with _locks.setdefault(document_id, asyncio.Lock()):
        if out.exists():  # a second tap while the first one was building
            return out
        with tempfile.TemporaryDirectory(dir=folder) as tmp:
            work = Path(tmp)
            clips = []
            # one paragraph at a time: a whole reading is ~75 MB, and RAM on
            # this PC is tight
            for n, (seg_id, _kind, _size) in enumerate(rows):
                audio = await db.scalar(
                    select(NarrationSegment.audio).where(NarrationSegment.id == seg_id)
                )
                clip = work / f"{n:05d}.mp3"
                clip.write_bytes(audio)
                clips.append(clip)
            built = work / out.name
            await asyncio.to_thread(
                build_mp3, clips, [k for _i, k, _n in rows], built, title=title, album=album
            )
            os.replace(built, out)
        for old in folder.glob(f"{document_id}-*.mp3"):
            if old != out:
                old.unlink(missing_ok=True)
    return out
