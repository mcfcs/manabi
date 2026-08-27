"""Citation validation — the structural anti-hallucination layer.

Every generated item carries source_ids (short in-context indices). They must
resolve through the index map AND land inside the job's module scope. Items
whose citations don't resolve are DROPPED — unsupported content is never
persisted with invented provenance. Each generation doubles as a live
module-isolation audit.
"""

import logging
import re
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
    *,
    require_sources: bool = True,
) -> tuple[list[ResolvedItem], int]:
    """Returns (kept items with resolved chunks, dropped count).

    require_sources=False (exercise mode): synthesized items are legitimate —
    an item is kept even with zero resolvable citations; unresolvable ids are
    stripped rather than sinking the item. Module isolation still holds: an
    out-of-scope chunk is never attached either way.
    """
    kept: list[ResolvedItem] = []
    dropped = 0
    for item in items:
        chunks: list[ScopedChunk] = []
        valid = True
        for sid in item.get("source_ids", []):
            # The grammar constrains source_ids to integers, but never crash the
            # whole answer on a malformed id (schema bypass / re-ask garbage) —
            # treat it as unresolvable.
            try:
                idx = int(sid)
            except (TypeError, ValueError):
                valid = False
                continue
            chunk = index_map.get(idx)
            if chunk is None or chunk.module_id not in allowed_module_ids:
                valid = False
                continue
            chunks.append(chunk)
        if not require_sources:
            if not valid:
                log.info("exercise item kept, invalid citations stripped: %.80s",
                         str(item.get("front") or item.get("prompt") or item.get("text")))
            kept.append(ResolvedItem(item=item, chunks=chunks))
        elif valid and chunks:
            kept.append(ResolvedItem(item=item, chunks=chunks))
        else:
            dropped += 1
            log.warning("dropped item with unresolvable/out-of-scope citations: %.80s",
                        str(item.get("front") or item.get("prompt") or item.get("text")))
    return kept, dropped


def match_element_ids(
    claim_text: str,
    elements: list[tuple[int, str]],
    threshold: float = 0.15,
) -> list[int]:
    """Pick the elements within a cited chunk that actually support the claim
    (precise highlight targets). elements: (element_id, text). Token-overlap
    scoring; always returns at least the best match when any text exists."""
    import re

    def tokens(text: str) -> set[str]:
        return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}

    claim = tokens(claim_text)
    if not claim:
        return []
    scored: list[tuple[float, int]] = []
    for el_id, el_text in elements:
        el_tokens = tokens(el_text)
        if not el_tokens:
            continue
        overlap = len(claim & el_tokens) / len(claim)
        scored.append((overlap, el_id))
    if not scored:
        return []
    scored.sort(reverse=True)
    picked = [el_id for score, el_id in scored if score >= threshold]
    return picked or [scored[0][1]]


# Formulaic openings ("According to the source material, …") inflate difflib
# similarity between genuinely different questions — strip them before
# comparing, or half a quiz gets discarded as "duplicates".
_BOILERPLATE_PREFIX = re.compile(
    r"^(?:according to|based on|per|as stated in|as described in)\s+"
    r"(?:the\s+)?(?:source(?:\s+material)?|text|reading|module|lecture)s?\s*,?\s*"
)


def _dedup_stem(text: str) -> str:
    return _BOILERPLATE_PREFIX.sub("", (text or "").lower().strip())


def _numeric_fingerprint(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"\d+(?:\.\d+)?", text or ""))


def _near_duplicate(a: str, b: str, threshold: float) -> bool:
    from difflib import SequenceMatcher

    sa, sb = _dedup_stem(a), _dedup_stem(b)
    if SequenceMatcher(None, sa, sb).ratio() <= threshold:
        return False
    # Same wording but different numbers = a legitimate drill variant
    # (math / code-tracing practice), not a duplicate.
    na, nb = _numeric_fingerprint(sa), _numeric_fingerprint(sb)
    if na and nb and na != nb:
        return False
    return True


def dedup_cards(
    new_items: list[ResolvedItem],
    existing_fronts: list[str],
    threshold: float = 0.85,
) -> list[ResolvedItem]:
    """Drop cards whose fronts near-duplicate existing ones (or each other)."""
    kept: list[ResolvedItem] = []
    fronts = list(existing_fronts)
    for item in new_items:
        front = item.item.get("front") or ""
        if any(_near_duplicate(front, f, threshold) for f in fronts):
            continue
        kept.append(item)
        fronts.append(front)
    return kept


def dedup_questions(items: list[ResolvedItem], threshold: float = 0.8) -> list[ResolvedItem]:
    """Drop near-duplicate question stems (difflib ratio)."""
    kept: list[ResolvedItem] = []
    for candidate in items:
        stem = candidate.item.get("prompt") or ""
        if any(
            _near_duplicate(stem, k.item.get("prompt") or "", threshold)
            for k in kept
        ):
            continue
        kept.append(candidate)
    return kept
