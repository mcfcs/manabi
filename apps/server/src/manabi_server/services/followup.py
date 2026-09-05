"""Deterministic follow-up handling for chat retrieval queries (no model call).

A bare follow-up ("explain that more", "why?", "and the second one?") embeds
poorly on its own, so it should carry the previous user turn and the salient
terms of the last answer into retrieval. A topic change ("what is a monad")
should NOT drag the previous topic along — until now every message folded in
the last two user turns, which polluted retrieval after a switch.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence

# Openers that only make sense relative to what was just said.
_CUES = (
    "and ",
    "and?",
    "but ",
    "so ",
    "then ",
    "what about",
    "how about",
    "why",
    "how so",
    "how come",
    "explain",
    "elaborate",
    "expand",
    "more ",
    "again",
    "also",
    "same ",
    "example",
    "for example",
    "e.g",
    "in other words",
    "simpler",
    "simplify",
    "eli5",
    "can you",
    "could you",
    "what does that",
    "what do you mean",
    "which one",
    "the first",
    "the second",
    "the last",
    "the other",
)

_ANAPHORA = re.compile(
    r"\b(it|its|that|this|these|those|they|them|their|he|she|his|her|there|one|ones)\b",
    re.IGNORECASE,
)

_STOP = frozenset(
    """
    a an the and or but if then so of to in on at by for from with without into onto
    over under about as is are was were be been being am do does did done have has had
    having will would shall should can could may might must not no nor yes what which
    who whom whose where when why how all any both each few more most other some such
    than too very just also only own same very s t can will don should now i me my we
    our you your he him his she her it its they them their this that these those there
    here again further once explain elaborate expand tell give show describe mean means
    please thanks thank ok okay hmm um like really actually basically say said says
    """.split()  # noqa: SIM905 — readable word list
)

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'+#-]*")
# straight single quotes are apostrophes far more often than quotes ("don't")
_QUOTED = re.compile(r"[\"“‘]([^\"”’]{3,60})[\"”’]")
_CAPITALIZED = re.compile(r"\b([A-Z][A-Za-z0-9+#-]+(?:[ -][A-Z][A-Za-z0-9+#-]+){0,3})\b")


def content_words(text: str) -> list[str]:
    return [w for w in _WORD.findall(text) if w.lower() not in _STOP]


def is_followup(text: str) -> bool:
    """Surface-cue test: short, pronoun-heavy, or opening with a relative cue."""
    t = text.strip().lower()
    if not t:
        return False
    words = content_words(t)
    if len(words) < 6:
        return True
    if _ANAPHORA.search(t) and len(words) < 12:
        return True
    return any(t.startswith(c) for c in _CUES)


def salient_terms(text: str, limit: int = 12) -> list[str]:
    """Terms worth carrying from the last answer: quoted phrases first, then
    Capitalized phrases (names, defined terms), then the most frequent
    non-stopword tokens — deduped, first appearance wins, capped."""
    seen: set[str] = set()
    out: list[str] = []

    def add(term: str) -> None:
        term = term.strip(" .,;:")
        key = term.lower()
        if len(term) >= 3 and key not in seen and key not in _STOP and len(out) < limit:
            seen.add(key)
            out.append(term)

    for m in _QUOTED.finditer(text):
        add(m.group(1))
    for m in _CAPITALIZED.finditer(text):
        add(m.group(1))
    counts = Counter(w.lower() for w in content_words(text) if len(w) > 3)
    for word, _ in counts.most_common():
        add(word)
    return out


def build_retrieval_query(
    current: str,
    prev_user_turns: Sequence[str],
    last_assistant: str | None,
    *,
    max_prev: int = 2,
    max_chars: int = 2000,
) -> str:
    """The text to embed for retrieval. Topic change → the message alone;
    follow-up → message + previous user turns + salient terms of the last
    answer, newline-joined, capped."""
    current = current.strip()
    if not is_followup(current):
        return current[:max_chars]
    parts = [current]
    for turn in prev_user_turns[:max_prev]:
        turn = (turn or "").strip()
        if turn and turn not in parts:
            parts.append(turn)
    if last_assistant:
        terms = salient_terms(last_assistant)
        if terms:
            parts.append(" ".join(terms))
    return "\n".join(parts)[:max_chars]
