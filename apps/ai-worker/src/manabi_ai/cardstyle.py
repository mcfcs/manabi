"""Flashcard styles: what each style asks of a card, the mix the AI picks
when the student leaves the style blank, and the deterministic checks a card
must pass for its style. Pure; unit-tested.

Before styles existed, CSCI 70's 73 cards had a median back of 24 words —
mini-essays, not recall. A term-recall back is now the term alone.
"""

import re

from manabi_ai import quizplan

STYLES = ("term", "definition", "short", "code")

# Code-heavy material: recall the name, answer briefly, trace programs.
CODE_MIX = {"term": 4.0, "short": 3.0, "code": 3.0}
# Readings: definitions may be sentences; short answers and term recall too.
READING_MIX = {"definition": 4.0, "short": 3.0, "term": 3.0}

TERM_MAX_WORDS = 6
DEFINITION_FRONT_MAX_WORDS = 8
SHORT_MAX_WORDS = 15
LIST_ITEM_MAX_WORDS = 5

RULES = {
    "term": """Card style — TERM RECALL:
- Front: a precise description, clue or definition taken from the sources.
  It must NOT contain the answer word(s) or an obvious form of them.
- Back: ONLY the exact term or name as the sources write it (1-6 words).
  No sentence, no explanation, no "It is...".""",
    "definition": """Card style — DEFINITION:
- Front: one term or concept name exactly as the sources write it (a few
  words, no question sentence).
- Back: its definition as the sources give it, self-contained, one to three
  sentences.
- ENUMERATIONS: when a source lists N items (types, steps, layers), a card
  may name the group on the front and list all N items on the back.""",
    "short": """Card style — SHORT ANSWER:
- Front: a why / how / what / compare question about one testable idea.
- Back: the answer in AT MOST 15 words — a phrase, not an essay.
- ENUMERATIONS: ask to name all N listed items; the back is just the items,
  comma-separated.
- COMPARISONS: when the sources contrast two concepts, ask for the key
  difference in one short line.""",
    "code": """Card style — CODE OUTPUT:
- Front: "What does this print?" followed by a SHORT complete program in a
  fenced code block (```c or ```cpp) using constructs the sources teach.
  Deterministic: no input, no randomness, no addresses, no undefined
  behaviour.
- Exam level: each program turns on ONE rule a student can get wrong —
  integer division and %, pre/post increment, operator precedence, scope and
  shadowing, pointer arithmetic, pass by value vs reference, constructor or
  destructor order. Never a program that just prints a literal or a + b.
- Back: exactly what the program prints, character for character, nothing
  else.""",
}

_FENCE = re.compile(r"```[A-Za-z0-9_+#-]*[ \t]*\n.*?\S.*?```", re.DOTALL)
_NON_DETERMINISTIC = re.compile(r"<[^>\n]*address[^>\n]*>|garbage|undefined|random", re.I)


def plan(styles: list[str] | None, is_code: bool, count: int) -> dict[str, int]:
    """How many cards of each style. Chosen styles share the count evenly;
    none chosen → the AI's mix for this kind of material. Code-output cards
    only make sense for code material and fall back to short answers."""
    chosen = [s for s in (styles or []) if s in STYLES]
    if not is_code:
        chosen = [s for s in chosen if s != "code"] or (["short"] if chosen else [])
    mix = {s: 1.0 for s in chosen} if chosen else dict(CODE_MIX if is_code else READING_MIX)
    counts = quizplan.allocate(count, mix)
    return {s: n for s, n in counts.items() if n > 0}


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", text or "")


def _norm(text: str) -> str:
    return " ".join(w.lower() for w in _words(text))


def _is_short_list(back: str) -> bool:
    items = [s.strip() for s in re.split(r"[,;\n]|\band\b", back) if s.strip()]
    return len(items) >= 2 and all(len(_words(s)) <= LIST_ITEM_MAX_WORDS for s in items)


def tidy_front(front: str) -> str:
    """Close a code fence the model opened and never closed. Every C++ card
    for an OOP module came back that way and was thrown out as "no code"."""
    front = (front or "").rstrip()
    if front.count("```") % 2 == 1:
        front += "\n```"
    return front


def problem(style: str, front: str, back: str) -> str | None:
    """Why this card does not fit its style, or None when it does."""
    front, back = (front or "").strip(), (back or "").strip()
    if not front or not back:
        return "empty side"
    if style == "term":
        if len(_words(back)) > TERM_MAX_WORDS:
            return "term back is a sentence"
        nb = _norm(back)
        if nb and f" {nb} " in f" {_norm(front)} ":  # whole words: "C" ≠ "procedural"
            return "front gives the answer away"
        return None
    if style == "definition":
        if len(_words(front)) > DEFINITION_FRONT_MAX_WORDS:
            return "definition front is not a term"
        return None
    if style == "short":
        if len(_words(back)) > SHORT_MAX_WORDS and not _is_short_list(back):
            return "short-answer back is too long"
        return None
    if style == "code":
        if not _FENCE.search(front):
            return "code card shows no code"
        if _NON_DETERMINISTIC.search(back):
            return "code output is not deterministic"
        return None
    return None
