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
    "THE", "AND", "FOR", "NOT", "ARE", "BUT", "ALL", "ANY", "CAN", "ITS",
    "THIS", "THAT", "WITH", "FROM", "NOTE", "PART", "UNIT", "PAGE", "II",
    "III", "IV", "VI", "VII", "USA", "OK",
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
