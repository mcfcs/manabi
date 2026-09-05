"""Context assembly for generation.

Sources are numbered [1..N] in-context; the model cites those short indices
and the worker remaps them to real chunk ids (raw DB ids drift under
constrained decoding — master plan §F). Student notes are a separately
labeled block that carries no citable index: notes can bias emphasis but can
never be cited as a factual source.
"""

import re
from dataclasses import dataclass

from manabi_core.retrieval import ScopedChunk

CONTEXT_BUDGET_TOKENS = 14_000


@dataclass
class BuiltContext:
    source_text: str
    index_map: dict[int, ScopedChunk]  # in-context index -> chunk


def build_context(chunks: list[ScopedChunk], notes_text: str | None) -> BuiltContext:
    lines: list[str] = []
    index_map: dict[int, ScopedChunk] = {}
    for i, chunk in enumerate(chunks, start=1):
        index_map[i] = chunk
        pages = (
            f"p.{chunk.page_start}"
            if chunk.page_start == chunk.page_end
            else f"p.{chunk.page_start}-{chunk.page_end}"
        )
        header = f"[{i}] ({chunk.document_title}, {pages})"
        lines.append(f"{header}\n{chunk.text}")
    source_text = "SOURCE MATERIAL (the only factual authority):\n\n" + "\n\n".join(lines)
    if notes_text and notes_text.strip():
        source_text += (
            "\n\nSTUDENT NOTES — emphasis and context only, NOT a factual "
            "source, never cite them:\n" + notes_text.strip()[:4000]
        )
    return BuiltContext(source_text=source_text, index_map=index_map)


_ACRONYM_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,5}s?\b")
_COMMON_NON_ACRONYMS = {
    "THE",
    "AND",
    "FOR",
    "NOT",
    "ARE",
    "BUT",
    "ALL",
    "ANY",
    "CAN",
    "ITS",
    "THIS",
    "THAT",
    "WITH",
    "FROM",
    "NOTE",
    "PART",
    "UNIT",
    "PAGE",
    "II",
    "III",
    "IV",
    "VI",
    "VII",
    "USA",
    "OK",
}


def scan_acronym_candidates(chunks: list[ScopedChunk], limit: int = 40) -> list[str]:
    """Deterministic acronym candidates: uppercase tokens that either recur
    or appear with a parenthesized expansion. Guarantees the model at least
    CONSIDERS every acronym present in the sources."""
    counts: dict[str, int] = {}
    for chunk in chunks:
        for m in _ACRONYM_RE.findall(chunk.text):
            token = m.rstrip("s")
            if len(token) < 2 or token in _COMMON_NON_ACRONYMS:
                continue
            counts[token] = counts.get(token, 0) + 1
    candidates = sorted(
        (t for t, n in counts.items() if n >= 2 or len(t) >= 3),
        key=lambda t: -counts[t],
    )
    return candidates[:limit]


def batch_chunks(
    chunks: list[ScopedChunk], budget: int = CONTEXT_BUDGET_TOKENS
) -> list[list[ScopedChunk]]:
    """Split an oversized scope into document/page-ordered batches."""
    batches: list[list[ScopedChunk]] = []
    current: list[ScopedChunk] = []
    used = 0
    for chunk in chunks:
        if current and used + chunk.token_count > budget:
            batches.append(current)
            current, used = [], 0
        current.append(chunk)
        used += chunk.token_count
    if current:
        batches.append(current)
    return batches


# ── Key-term candidates ─────────────────────────────────────────────────────
# Phrases the sources DEFINE: "X is defined as …", "X refers to …", "X means …",
# and glossary lines "X: …". Injected into the summary prompt next to the
# acronym candidates so the model at least CONSIDERS every term the material
# itself defines (the prompt already asks for "every term", but a concrete
# list is what actually moves recall).
_DEF_CUE_RE = re.compile(
    r"(?<![\w-])([A-Z][\w+#-]*(?:[ -][A-Za-z][\w+#-]*){0,4})\s+"
    r"(?:is defined as|are defined as|refers? to|is called|are called|means|"
    r"is an? (?:type|kind|form|set|way|process|technique|method|principle|concept|"
    r"model|measure|approach|language|paradigm|property|function|structure|system)\b)"
)
_GLOSSARY_RE = re.compile(r"^\s*([A-Z][\w+#-]*(?:[ -][\w+#-]+){0,4})\s*[:—–]\s+\S", re.MULTILINE)
_NON_TERM_STARTS = {
    "the",
    "a",
    "an",
    "this",
    "that",
    "these",
    "those",
    "it",
    "its",
    "there",
    "here",
    "which",
    "what",
    "who",
    "each",
    "every",
    "such",
    "one",
    "he",
    "she",
    "they",
    "we",
    "you",
    "i",
    "also",
    "another",
    "some",
    "any",
    "all",
    "both",
    "in",
    "on",
    "at",
    "for",
    "as",
    "if",
    "when",
    "where",
    "how",
    "why",
    "term",
    "word",
    "note",
    "example",
    "figure",
    "table",
    "chapter",
    "section",
    "page",
    "step",
    "part",
    "lecture",
    "slide",
}


def _clean_term(raw: str) -> str | None:
    words = raw.strip(" .,;:-—–").split()
    while words and words[0].lower() in ("the", "a", "an", "term"):
        words = words[1:]  # "The term polymorphism" -> "polymorphism"
    if not words or words[0].lower() in _NON_TERM_STARTS:
        return None
    term = " ".join(words)
    if len(term) < 3 or len(term) > 60:
        return None
    if re.fullmatch(r"[A-Z0-9+#-]+s?", term):
        return None  # acronyms are scan_acronym_candidates' job
    return term


def scan_definition_candidates(chunks: list[ScopedChunk], limit: int = 40) -> list[str]:
    """Deterministic key-term candidates from definitional cues, most frequent
    first (ties by first appearance), deduped case-insensitively, keeping the
    casing of the first appearance."""
    counts: dict[str, int] = {}
    first: dict[str, str] = {}
    order: list[str] = []
    for chunk in chunks:
        for regex in (_DEF_CUE_RE, _GLOSSARY_RE):
            for m in regex.finditer(chunk.text):
                term = _clean_term(m.group(1))
                if term is None:
                    continue
                key = term.lower()
                if key not in counts:
                    counts[key] = 0
                    first[key] = term
                    order.append(key)
                counts[key] += 1
    ranked = sorted(order, key=lambda k: (-counts[k], order.index(k)))
    return [first[k] for k in ranked[:limit]]


def count_defined(candidates: list[str], key_terms: list[dict]) -> int:
    """How many candidates the produced key_terms cover (case-insensitive;
    a key term that contains the candidate, or vice versa, counts)."""
    produced = [str(t.get("term", "")).strip().lower() for t in key_terms]
    hit = 0
    for cand in candidates:
        c = cand.lower()
        if any(c == p or c in p or (p and p in c) for p in produced):
            hit += 1
    return hit
