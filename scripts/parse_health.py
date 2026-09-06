"""Measure and preview text-layer healing on a cached Docling parse.

    uv run python scripts/parse_health.py storage/parse-cache/v3-<hash>-orig.json <file.pdf>

Prints, per page, the glued-token ratio of the cached Docling text and of the
same elements after ``text_health.heal_elements`` re-reads glued pages from
the PDF. Read-only: nothing is written to the cache or the database.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pymupdf
from manabi_server.processing.text_health import (
    glue_ratio,
    glued_tokens,
    heal_elements,
    pymupdf_clip_text,
)


def main(cache_json: str, pdf_path: str, show: int = 3) -> None:
    raw = json.loads(Path(cache_json).read_text(encoding="utf-8"))
    elements = [dict(e) for e in raw["elements"]]
    before = {}
    for el in elements:
        before.setdefault(int(el["page_no"]), []).append(el.get("text") or "")

    with pymupdf.open(pdf_path) as pdf:
        healed = heal_elements([dict(e) for e in elements], pymupdf_clip_text(pdf))
    after: dict[int, list[str]] = {}
    for el in healed:
        after.setdefault(int(el["page_no"]), []).append(el.get("text") or "")

    total_b = total_a = 0
    print(f"{'page':>4} {'glue before':>11} {'glue after':>10}  healed elements")
    for page_no in sorted(before):
        b = " ".join(before[page_no])
        a = " ".join(after.get(page_no, []))
        nb, na = len(glued_tokens(b)), len(glued_tokens(a))
        total_b += nb
        total_a += na
        n_healed = sum(1 for e in healed if int(e["page_no"]) == page_no and e.get("healed"))
        print(f"{page_no:>4} {glue_ratio(b):>11.3f} {glue_ratio(a):>10.3f}  {n_healed}")
    print(f"\nglued tokens: {total_b} -> {total_a}")
    shown = 0
    for el_b, el_a in zip(elements, healed, strict=True):
        if el_a.get("healed") and shown < show:
            shown += 1
            print(f"\n--- page {el_a['page_no']} ({el_a['type']}) ---")
            print("BEFORE:", (el_b.get("text") or "")[:220])
            print("AFTER: ", (el_a.get("text") or "")[:220])


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
