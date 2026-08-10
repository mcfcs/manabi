"""Prepare Steven Starphase voice-clone material from dub audio + subtitles.

Run ON the machine with the media (phillmyeol):

    python scripts/prep_steven_voice.py "C:/Users/grego/OneDrive/Documents/StevenSound" ^
        --out C:/manabi-voices

What it does:
1. Pairs every media file (mkv/mp4/wav/mp3/flac) with a matching .srt in the
   folder (same stem, or a single .srt for a single media file).
2. Cuts one wav per subtitle line (mono 32 kHz — GPT-SoVITS's native rate),
   trimming 100 ms off each end to avoid neighboring dialogue bleed.
3. Writes gpt_sovits_dataset.list ("path|steven|en|text") — the training
   manifest, transcripts straight from the subtitles (no ASR needed).
4. Prints the best REFERENCE candidates: clean single lines 3–10 s long,
   longest first. Listen to a few, pick the clearest one, and note its text.

Filtering: subtitles contain every character's lines. Either pre-cut the
media so it's Steven-only, or use --contains to keep only subtitle lines
matching a phrase, or (simplest) delete non-Steven wavs from the output
folder afterwards and re-run with --relist to rebuild the manifest.

After picking, if the audio has music/SFX under the voice, run the clips
through UVR5 (bundled in GPT-SoVITS WebUI) before training.

Requires ffmpeg + ffprobe on PATH.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

MEDIA_EXTS = {".mkv", ".mp4", ".m4a", ".wav", ".mp3", ".flac", ".aac", ".webm"}
TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def parse_srt(path: Path) -> list[tuple[float, float, str]]:
    """[(start_s, end_s, text)] — tags stripped, multi-line joined."""
    entries = []
    blocks = re.split(r"\n\s*\n", path.read_text(encoding="utf-8", errors="replace"))
    for block in blocks:
        m = TS.search(block)
        if not m:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, m.groups())
        start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000
        end = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000
        text_lines = block[m.end() :].strip().split("\n")
        text = " ".join(t.strip() for t in text_lines if t.strip())
        text = re.sub(r"<[^>]+>|\{[^}]+\}", "", text)  # <i> tags / ass overrides
        text = re.sub(r"\s+", " ", text).strip()
        if text and end > start:
            entries.append((start, end, text))
    return entries


def cut(media: Path, start: float, end: float, out: Path) -> bool:
    start, end = start + 0.1, end - 0.1  # avoid neighboring-line bleed
    if end - start < 0.5:
        return False
    r = subprocess.run(
        [
            "ffmpeg", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
            "-i", str(media), "-vn", "-ac", "1", "-ar", "32000",
            "-c:a", "pcm_s16le", str(out),
        ],
        capture_output=True,
    )
    return r.returncode == 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="folder with media + .srt files")
    ap.add_argument("--out", default="C:/manabi-voices", help="output folder")
    ap.add_argument("--contains", help="keep only subtitle lines containing this text")
    ap.add_argument(
        "--relist", action="store_true",
        help="only rebuild the .list from wavs already in --out (after you "
        "deleted non-Steven clips)",
    )
    args = ap.parse_args()

    src = Path(args.source)
    out = Path(args.out)
    clips_dir = out / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    manifest = out / "gpt_sovits_dataset.list"

    if args.relist:
        kept = []
        index = {}
        if (out / "transcripts.txt").exists():
            for line in (out / "transcripts.txt").read_text(encoding="utf-8").splitlines():
                name, _, text = line.partition("\t")
                index[name] = text
        for wav in sorted(clips_dir.glob("*.wav")):
            text = index.get(wav.name, "")
            if text:
                kept.append(f"{wav}|steven|en|{text}")
        manifest.write_text("\n".join(kept), encoding="utf-8")
        print(f"rebuilt {manifest} with {len(kept)} clips")
        return

    media_files = sorted(p for p in src.iterdir() if p.suffix.lower() in MEDIA_EXTS)
    srt_files = sorted(src.glob("*.srt"))
    if not media_files or not srt_files:
        sys.exit(f"need media + .srt in {src} (found {len(media_files)} media, {len(srt_files)} srt)")

    pairs = []
    for media in media_files:
        exact = src / (media.stem + ".srt")
        if exact.exists():
            pairs.append((media, exact))
        elif len(media_files) == 1 and len(srt_files) == 1:
            pairs.append((media, srt_files[0]))
    if not pairs:
        sys.exit("no media/.srt stem matches — rename them to share filenames")

    rows = []
    transcript_index = []
    candidates = []
    n = 0
    for media, srt in pairs:
        entries = parse_srt(srt)
        print(f"{media.name}: {len(entries)} subtitle lines")
        for start, end, text in entries:
            if args.contains and args.contains.lower() not in text.lower():
                continue
            n += 1
            wav = clips_dir / f"{media.stem}_{n:04d}.wav"
            if not cut(media, start, end, wav):
                continue
            rows.append(f"{wav}|steven|en|{text}")
            transcript_index.append(f"{wav.name}\t{text}")
            dur = end - start - 0.2
            if 3.0 <= dur <= 10.0 and text[-1] in ".!?":
                candidates.append((dur, wav.name, text))

    manifest.write_text("\n".join(rows), encoding="utf-8")
    (out / "transcripts.txt").write_text("\n".join(transcript_index), encoding="utf-8")

    print(f"\n{len(rows)} clips → {clips_dir}")
    print(f"manifest → {manifest}")
    print("\nREFERENCE candidates (3–10 s, complete sentences — listen and pick ONE):")
    for dur, name, text in sorted(candidates, reverse=True)[:12]:
        print(f"  {dur:4.1f}s  {name}  “{text[:70]}”")
    print(
        "\nNext: 1) delete clips that aren't Steven, re-run with --relist"
        "\n      2) UVR5 the kept clips if music/SFX is audible"
        "\n      3) copy your chosen reference to C:/manabi-voices/steven_ref.wav"
        "\n      4) set TTS_REF_AUDIO + TTS_REF_TEXT (its exact text) in the worker .env"
    )


if __name__ == "__main__":
    main()
