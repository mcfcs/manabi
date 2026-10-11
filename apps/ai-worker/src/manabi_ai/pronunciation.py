"""Learn how Steven should say a reading's unfamiliar words, before it is
recorded, and keep them in the course's pronunciation list.

1. Words the voice's dictionary does not know (g2p probe) and the course has
   no entry for yet.
2. The model says what each one is and how it should sound (ARPAbet), with
   three space-separated respellings.
3. Each respelling is run through the voice's own front end; the one whose
   real sounds come closest to the intended ones is kept, with that score as
   `match` so a poor one can be found and corrected.
"""

import logging
import re

from manabi_core import pronounce
from manabi_core.models import Course, Document, Module, Pronunciation
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_ai import g2p, prompts
from manabi_ai.ollama_client import GenerationError, generate_structured

log = logging.getLogger("manabi_ai.pronunciation")

MAX_NEW_TERMS = 40  # per reading: the most frequent first
TERMS_PER_CALL = 20
CONTEXT_CHARS = 160


async def course_entries(db: AsyncSession, course_id: int | None) -> list[pronounce.Entry]:
    if course_id is None:
        return []
    rows = await db.execute(
        select(Pronunciation.term, Pronunciation.say).where(Pronunciation.course_id == course_id)
    )
    return [pronounce.Entry(term=t, say=s) for t, s in rows.all()]


async def course_of_document(db: AsyncSession, document_id: int) -> Course | None:
    return (
        await db.execute(
            select(Course)
            .join(Module, Module.course_id == Course.id)
            .join(Document, Document.module_id == Module.id)
            .where(Document.id == document_id)
        )
    ).scalar_one_or_none()


async def course_of_module(db: AsyncSession, module_id: int) -> Course | None:
    return (
        await db.execute(
            select(Course).join(Module, Module.course_id == Course.id).where(Module.id == module_id)
        )
    ).scalar_one_or_none()


def _context(word: str, texts: list[str]) -> str:
    for t in texts:
        m = re.search(rf"[^.!?]*\b{re.escape(word)}\b[^.!?]*[.!?]?", t)
        if m:
            return m.group(0).strip()[:CONTEXT_CHARS]
    return ""


def pick(arpabet: str, candidates: list[str], sounds: dict[str, dict]) -> tuple[str, float | None]:
    """The candidate whose actual phonemes are closest to `arpabet`, with its
    match (1 - distance). Unverifiable (no probe) → the first candidate."""
    target = arpabet.split()
    scored = [
        (pronounce.phone_distance(sounds[c]["phones"], target), c)
        for c in candidates
        if c in sounds and target
    ]
    if not scored:
        return (candidates[0], None) if candidates else ("", None)
    distance, best = min(scored)
    return best, round(1 - distance, 2)


def _clean_candidate(c: str) -> str:
    # The voice spells out short pieces of a hyphenated respelling.
    return re.sub(r"\s+", " ", c.replace("-", " ")).strip()


async def learn(db: AsyncSession, course: Course | None, texts: list[str]) -> int:
    """Add entries for this reading's unfamiliar words; returns how many."""
    if course is None:
        return 0
    have = {e.term.lower() for e in await course_entries(db, course.id)}
    counts: dict[str, int] = {}
    spelled: dict[str, str] = {}
    for t in texts:
        for w in pronounce.words(t):
            key = w.lower()
            if key in have:
                continue
            counts[key] = counts.get(key, 0) + 1
            spelled.setdefault(key, w)
    if not counts:
        return 0
    found = await g2p.probe(list(spelled.values()))
    if found is None:
        log.info("pronunciation: voice front end not available, nothing learned")
        return 0
    unknown = [
        spelled[k]
        for k in sorted(counts, key=lambda k: -counts[k])
        if pronounce.needs_respelling(spelled[k], found.get(spelled[k], {}).get("known", True))
    ][:MAX_NEW_TERMS]
    if not unknown:
        return 0

    decided: list[dict] = []
    label = f"{course.code} — {course.name}"
    for start in range(0, len(unknown), TERMS_PER_CALL):
        batch = unknown[start : start + TERMS_PER_CALL]
        listing = "\n".join(f"TERM: {w}\nLINE: {_context(w, texts)}" for w in batch)
        try:
            out = await generate_structured(
                prompts.PRONOUNCE_PROMPT.replace("{course}", label),
                listing,
                prompts.PRONOUNCE_SCHEMA,
                response_headroom=2048,
            )
        except GenerationError as exc:
            log.warning("pronunciation batch failed: %s", exc)
            continue
        wanted = {w.lower(): w for w in batch}
        for item in out.get("terms", []):
            term = wanted.get(str(item.get("term", "")).strip().lower())
            if term:
                decided.append({**item, "term": term})

    candidates = [
        _clean_candidate(c)
        for d in decided
        if d.get("kind") == "word"
        for c in d.get("candidates") or []
        if c.strip()
    ]
    sounds = await g2p.probe(candidates) or {}
    rows = []
    for d in decided:
        kind, term = d.get("kind"), d["term"]
        if kind == "letters":
            say, match = pronounce.letters(term), None
        elif kind == "word":
            say, match = pick(
                d.get("arpabet") or "",
                [_clean_candidate(c) for c in d.get("candidates") or [] if c.strip()],
                sounds,
            )
        else:
            say, match = term, None  # keep: remembered so it is not asked again
        if say:
            rows.append(
                {
                    "course_id": course.id,
                    "term": term[:80],
                    "say": say[:160],
                    "source": "auto",
                    "match": match,
                }
            )
    if rows:
        await db.execute(
            insert(Pronunciation)
            .values(rows)
            .on_conflict_do_nothing(constraint="uq_pronunciations_course_term")
        )
        await db.commit()
    log.info("pronunciation: %d new terms for course %s", len(rows), course.id)
    return len(rows)
