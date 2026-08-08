"""Citation validation — the structural anti-hallucination layer.

Every generated item carries source_ids (short in-context indices). They must
resolve through the index map AND land inside the job's module scope. Items
whose citations don't resolve are DROPPED — unsupported content is never
persisted with invented provenance. Each generation doubles as a live
module-isolation audit.
"""

import logging
from dataclasses import dataclass

from manabi_core.retrieval import ScopedChunk

log = logging.getLogger("manabi_ai")


@dataclass
class ResolvedItem:
    item: dict
    chunks: list[ScopedChunk]


def resolve_items(
    items: list[dict],
    index_map: dict[int, ScopedChunk],
    allowed_module_ids: set[int],
) -> tuple[list[ResolvedItem], int]:
    """Returns (kept items with resolved chunks, dropped count)."""
    kept: list[ResolvedItem] = []
    dropped = 0
    for item in items:
        chunks: list[ScopedChunk] = []
        valid = True
        for sid in item.get("source_ids", []):
            chunk = index_map.get(int(sid)) if isinstance(sid, int | str) else None
            if chunk is None or chunk.module_id not in allowed_module_ids:
                valid = False
                break
            chunks.append(chunk)
        if valid and chunks:
            kept.append(ResolvedItem(item=item, chunks=chunks))
        else:
            dropped += 1
            log.warning("dropped item with unresolvable/out-of-scope citations: %.80s",
                        str(item.get("front") or item.get("prompt") or item.get("text")))
    return kept, dropped


def dedup_questions(items: list[ResolvedItem], threshold: float = 0.8) -> list[ResolvedItem]:
    """Drop near-duplicate question stems (difflib ratio)."""
    from difflib import SequenceMatcher

    kept: list[ResolvedItem] = []
    for candidate in items:
        stem = (candidate.item.get("prompt") or "").lower()
        if any(
            SequenceMatcher(
                None, stem, (k.item.get("prompt") or "").lower()
            ).ratio()
            > threshold
            for k in kept
        ):
            continue
        kept.append(candidate)
    return kept
