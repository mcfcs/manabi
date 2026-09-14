"""What kind of quiz does this material actually support?

Choosing question types blind is guesswork: asking for `output` questions from
a prose reading yields nothing useful, and asking only for `mcq` from a
pointer-arithmetic lecture wastes the most valuable thing in it. The material
itself says which types fit — a C lecture full of `printf` and `*ptr` supports
tracing execution; a theory chapter full of "X is defined as" supports
identification.

Deliberately deterministic: this is pattern counting over chunk text, in the
same spirit as `context.scan_acronym_candidates`. It costs no GPU time, runs
instantly while the generate dialog is opening, and cannot hallucinate a
recommendation the material does not support.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

# ── Signals ────────────────────────────────────────────────────────────────

_FENCE = re.compile(r"```", re.MULTILINE)

# Statement shapes that only appear in code, kept deliberately narrow so prose
# about programming ("the printf function is used to…") does not trip them.
_CODE_LINE = re.compile(
    r"""(?x)
    ^\s*(?:
        \#include\s*[<"]            # C preprocessor
      | (?:int|char|float|double|void|long|short|unsigned)\s+\*?\w+\s*(?:\[|=|\()
      | (?:printf|scanf|malloc|free|strcpy|strlen|fprintf|puts)\s*\(
      | (?:def|class)\s+\w+\s*[(:]  # Python
      | (?:import|from)\s+\w+\s+import\b
      | print\s*\(
      | (?:for|while|if)\s*\(.*\)\s*\{?\s*$
      | \w+\s*=\s*\w+\s*[+\-*/]\s*\w+\s*;   # arithmetic assignment, C-style
      | return\s+[\w*&(].*;
    )""",
    re.MULTILINE,
)

# No space allowed before "[", so a citation like "Barnett [1]" is not an index.
_POINTER = re.compile(r"(\*\s*\w+|\w+\[\s*\w*\s*\]|&\w+|->\s*\w+|\w+\s*\+\s*\d+)")
_C_HINT = re.compile(r"\b(?:printf|scanf|malloc|char\s*\*|null[- ]terminat|pointer)\b", re.I)
_PY_HINT = re.compile(r"\b(?:def\s|elif\b|self\.|len\(|range\()", re.I)

# "X is defined as", "X refers to", "X is the process of" → identification/short
_DEFINITION = re.compile(
    r"\b\w[\w\s-]{2,40}?\s+(?:is|are)\s+(?:defined as|called|known as|referred to as|the\s+"
    r"(?:process|practice|study|term|name)\b)",
    re.I,
)
# Enumerable structure: "three kinds of", "the following steps", numbered lists
_LIST_LEAD = re.compile(
    r"\b(?:two|three|four|five|six|seven|eight|the following|these)\s+"
    r"(?:main\s+|key\s+|basic\s+|primary\s+)?"
    r"(?:types?|kinds?|categories|steps?|stages?|phases?|components?|principles?|"
    r"properties|characteristics|advantages|disadvantages|layers?|operations?)\b",
    re.I,
)
_BULLET = re.compile(r"^\s*(?:[-•*•]|\(?\d{1,2}[.)])\s+\S", re.MULTILINE)

# Argumentative / comparative prose → essay
_ESSAY = re.compile(
    r"\b(?:however|whereas|in contrast|argues?|critique|implications?|trade[- ]?offs?|"
    r"debate|perspective|framework|theory)\b",
    re.I,
)


@dataclass(frozen=True)
class TypeSuggestion:
    qtype: str
    recommended: bool
    reason: str  # shown to the user, so it must name the evidence


@dataclass(frozen=True)
class MaterialProfile:
    code_lines: int
    pointer_hits: int
    definition_hits: int
    list_hits: int
    essay_hits: int
    language: str | None  # "c" | "python" | None
    suggestions: list[TypeSuggestion]

    @property
    def recommended_types(self) -> list[str]:
        return [s.qtype for s in self.suggestions if s.recommended]


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def profile_material(texts: Iterable[str]) -> MaterialProfile:
    """Count the signals across every chunk in scope, then map them to types."""
    blob = "\n".join(t for t in texts if t)
    code_lines = len(_CODE_LINE.findall(blob)) + blob.count("```") // 2
    pointer_hits = len(_POINTER.findall(blob)) if code_lines else 0
    definition_hits = len(_DEFINITION.findall(blob))
    list_hits = len(_LIST_LEAD.findall(blob)) + len(_BULLET.findall(blob))
    essay_hits = len(_ESSAY.findall(blob))

    language = None
    if code_lines:
        c, py = len(_C_HINT.findall(blob)), len(_PY_HINT.findall(blob))
        if c or py:
            language = "c" if c >= py else "python"

    # Slide decks are the common case and they extract badly: the pointers
    # lecture yields only 2 recognisable "code lines" but 64 pointer and index
    # expressions. Density of value manipulation is the real signal that code
    # is present and worth tracing — code_lines alone misses it entirely.
    code_heavy = code_lines >= 4 or pointer_hits >= 8
    traceable = pointer_hits >= 8 or (code_lines >= 4 and pointer_hits >= 4)

    s: list[TypeSuggestion] = [
        TypeSuggestion(
            "output",
            traceable,
            (
                # Cite the signal that actually fired: on a slide deck it is the
                # density of pointer/index expressions, not the line count.
                f"{_plural(pointer_hits, 'pointer or index expression')} to trace — "
                "the sharpest thing to test here, and the answer is checked by "
                "running the code"
                if traceable
                else "needs code with values to trace; this material has little or none"
            ),
        ),
        TypeSuggestion(
            "coding",
            code_heavy,
            (
                f"{_plural(code_lines, 'code line')} and "
                f"{_plural(pointer_hits, 'code expression')} in the material"
                if code_heavy
                else "needs code-oriented material"
            ),
        ),
        TypeSuggestion(
            "identification",
            definition_hits >= 3,
            (
                f"{_plural(definition_hits, 'definition')} stated outright"
                if definition_hits >= 3
                else "few explicit definitions found"
            ),
        ),
        TypeSuggestion(
            "enumeration",
            list_hits >= 6,
            (
                f"{_plural(list_hits, 'list')} of related items"
                if list_hits >= 6
                else "little enumerable structure"
            ),
        ),
        TypeSuggestion(
            "essay",
            essay_hits >= 8 and not code_heavy,
            (
                "argumentative and comparative prose to synthesise"
                if essay_hits >= 8 and not code_heavy
                else "better suited to shorter recall here"
            ),
        ),
        # Always available: any material supports recall and recognition.
        TypeSuggestion("mcq", True, "works with any material"),
        TypeSuggestion("short", True, "works with any material"),
        TypeSuggestion(
            "tf",
            not code_heavy,
            (
                "clear factual statements to judge"
                if not code_heavy
                else "weak on code material — prefer tracing output"
            ),
        ),
    ]
    return MaterialProfile(
        code_lines=code_lines,
        pointer_hits=pointer_hits,
        definition_hits=definition_hits,
        list_hits=list_hits,
        essay_hits=essay_hits,
        language=language,
        suggestions=s,
    )
