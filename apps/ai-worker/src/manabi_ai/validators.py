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


_CARD_ASK = re.compile(r"^(?:define|what (?:is|are|does)|explain)\b[:\s]*", re.IGNORECASE)
CARD_KEY_MAX_WORDS = 8


def card_key(front: str, back: str) -> str | None:
    """The concept a term/definition card is about: its short side (the
    term), whichever way round the card asks. None when neither side is a
    term."""
    asked = _CARD_ASK.sub("", (front or "").strip()).rstrip("?:. ")
    sides = [s for s in (asked, (back or "").strip()) if 0 < len(s.split()) <= CARD_KEY_MAX_WORDS]
    return min(sides, key=lambda s: len(s.split())).lower() if sides else None


_KEY_STOP = frozenset(("a", "an", "the", "of", "in", "on", "for", "to", "and", "its", "their"))


def _same_concept(a: str, b: str, threshold: float) -> bool:
    """Card keys name one concept when they near-match, or when the shorter
    one (two or more words) is how the longer begins: "instrumental role" vs
    "instrumental role of political freedoms" scored 0.61 and a Sen deck asked
    five concepts both ways. A prefix, not any subset: "economic needs" and
    "conceptualization of economic needs" stay two concepts."""
    if _near_duplicate(a, b, threshold):
        return True
    wa, wb = (
        [w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in _KEY_STOP] for s in (a, b)
    )
    short, long_ = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    return len(short) >= 2 and long_[: len(short)] == short


def dedup_cards(
    new_items: list[ResolvedItem],
    existing_fronts: list[str],
    threshold: float = 0.85,
    existing_keys: list[str] | None = None,
) -> list[ResolvedItem]:
    """Drop cards whose fronts near-duplicate existing ones (or each other).
    With `existing_keys` (term/definition decks) also drop a card about a
    concept that already has one: a 20-card deck came back as 10 concepts,
    each once as term → definition and once as definition → term."""
    kept: list[ResolvedItem] = []
    fronts = list(existing_fronts)
    keys = list(existing_keys) if existing_keys is not None else None
    for item in new_items:
        front = item.item.get("front") or ""
        if any(_near_duplicate(front, f, threshold) for f in fronts):
            continue
        if keys is not None:
            key = card_key(front, item.item.get("back") or "")
            if key and any(_same_concept(key, k, threshold) for k in keys):
                continue
            if key:
                keys.append(key)
        kept.append(item)
        fronts.append(front)
    return kept


# A quiz is taken with the slides closed, so a question that points at the
# material ("the sample dataset provided in the source material", "the process
# described,") cannot be answered: the student never sees what it points at.
# The blind audit can't catch these — it is handed the sources.
_UNSEEN_MATERIAL = re.compile(
    r"\bsource\s+materials?\b"
    r"|\b(?:the|these|those)\s+sources\b"
    r"|\baccording\s+to\s+(?:the\s+)?sources?\b"
    r"|\b(?:in|from|on)\s+the\s+(?:slides?|lecture|readings?|handouts?)\b"
    r"|\b(?:described|shown|given|provided|presented|discussed|defined|mentioned)\s+in\s+"
    r"the\s+(?:sources?|slides?|lecture|material|readings?)\b"
    r"|\b(?:described|mentioned|shown)\s*(?:above|earlier)?\s*[,;:?]",
    re.IGNORECASE,
)
# "The sample dataset" is fine only when the question carries that dataset.
_UNSEEN_DATA = re.compile(
    r"\b(?:sample|example|given|provided)\s+(?:dataset|data\s+set|table)\b", re.IGNORECASE
)
_MARKDOWN_TABLE = re.compile(r"^\s*\|.*\|\s*$\n^\s*\|?\s*:?-{3,}", re.MULTILINE)


def references_unseen_material(item: dict) -> bool:
    """True when a question's prompt or options lean on material the student
    can't see while answering it."""
    prompt = item.get("prompt") or ""
    texts = [prompt, *[o for o in item.get("options") or [] if isinstance(o, str)]]
    if any(_UNSEEN_MATERIAL.search(t) for t in texts):
        return True
    return bool(_UNSEEN_DATA.search(prompt)) and not _MARKDOWN_TABLE.search(prompt)


# An essay that only asks for a list is an enumeration in disguise ("List the
# specific 'helpful policies'…" — Sen quiz): it tests recall, not synthesis.
_LIST_ASK = re.compile(r"^\s*(?:list|enumerate|name (?:all|the|each|every))\b", re.IGNORECASE)


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def item_writing_flaw(item: dict) -> str | None:
    """A defect code can see: the key printed in its own stem ("…against
    'Asian values'… is known as the ______ argument." → "Asian values"), or an
    essay that is really a list. None when the item is clean."""
    qtype = item.get("qtype")
    prompt = item.get("prompt") or ""
    if qtype in ("identification", "short"):
        answer = _norm(item.get("correct_text") or "")
        if answer and re.search(rf"(?<!\w){re.escape(answer)}(?!\w)", _norm(prompt)):
            return "answer in stem"
    if qtype == "essay" and _LIST_ASK.match(prompt):
        return "essay asks for a list"
    return None


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
