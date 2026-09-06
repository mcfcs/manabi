"""Preview the narration script Steven would read for a PDF — nothing is
synthesised or stored.

    uv run --package manabi-server python scripts/narration_dry_run.py file.pdf \
        [--skipped] [--spoken]

Prints kept segments (ord, page, kind, text) and a tally of skipped blocks by
kind. ``--skipped`` also lists what was dropped; ``--spoken`` shows the
normalised spoken text instead of the source text.
"""

from __future__ import annotations

import sys

from manabi_server.processing.narration_script import SKIPPED_KINDS, build_script_from_path
from manabi_server.processing.spoken import word_count


def main(argv: list[str]) -> None:
    if not argv or argv[0].startswith("-"):
        sys.exit(__doc__)
    show_skipped = "--skipped" in argv
    show_spoken = "--spoken" in argv
    script = build_script_from_path(argv[0])
    print(f"body {script.body_size}pt {script.body_font} | title: {script.title!r}")
    print(f"authors: {script.authors!r}\n")
    words = 0
    for seg in script.segments:
        shown = seg.spoken_text if show_spoken else seg.text
        words += word_count(seg.spoken_text)
        print(f"{seg.ord:3d} p{seg.page_no:<2d} {seg.kind:9} | {shown[:110]}")
    minutes = words / 160
    print(
        f"\n{len(script.segments)} segments, ~{words} spoken words (~{minutes:.0f} min at 160 wpm)"
    )
    print("blocks by kind:", script.counts())
    if show_skipped:
        print("\n--- skipped ---")
        for b in script.blocks:
            if b.kind in SKIPPED_KINDS:
                print(f"    p{b.page_no:<2d} {b.kind:12} | {b.text[:100]}")


if __name__ == "__main__":
    main(sys.argv[1:])
