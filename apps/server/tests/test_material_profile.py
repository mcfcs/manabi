"""Suggesting question types from the material itself.

Calibrated against the owner's real documents. The two cases that matter most:
a pointer lecture must offer `output`, and a politics reading must never.
"""

from manabi_core.material_profile import profile_material

# Shaped like the real CSCI70-L6-C-Pointers.pdf: a slide deck, so very few
# lines parse as "code", but dense with pointer and index expressions.
POINTERS_SLIDES = """
Pointers and Arrays
A pointer holds an address. *p dereferences it, &x takes the address of x.
char *sentence = "the quick brown fox";
ptrs[0] = sentence + 5;
ptrs[1] = sentence + 1;
arr[0], arr[1], arr[2] are contiguous.
*ptr = 10; &value; ptr->field;
p + 1 advances by one element, not one byte.
printf("%s", ptrs[0]);
int *q = &n; *q = *q + 3;
name[i] is the same as *(name + i).
buffer[0], buffer[1], buffer[2], buffer[3]
"""

# Shaped like the SocSc 14 readings: argumentative prose, plus bracketed
# citations that must not be mistaken for array indexing.
POLITICS_READING = """
Everyday politics involves people embracing, complying with, adjusting to and
contesting norms about the control of resources. Kerkvliet [1] argues that this
differs from official politics, whereas Scott [2] emphasises resistance.
However, the implications are contested; in contrast, Barnett [3] frames power
through a different theoretical framework. This debate has clear implications
for how we understand institutions, and critique of either perspective must
account for the trade-offs involved.
"""

DEFINITIONS_DECK = """
Lexical analysis is the process of converting characters into tokens.
A token is defined as a categorised sequence of characters.
A lexeme is known as the actual character sequence matched.
Parsing is referred to as syntax analysis.
The following stages: scanning, parsing, semantic analysis.
- scanning
- parsing
- semantic analysis
- optimisation
- code generation
1. read the source
2. produce tokens
"""


def test_the_pointer_lecture_offers_output_questions():
    p = profile_material([POINTERS_SLIDES])
    assert "output" in p.recommended_types
    assert "coding" in p.recommended_types
    assert p.language == "c"


def test_a_politics_reading_never_offers_code_questions():
    p = profile_material([POLITICS_READING])
    assert "output" not in p.recommended_types
    assert "coding" not in p.recommended_types


def test_bracketed_citations_are_not_array_indexing():
    # "Kerkvliet [1]" must not read as an index expression — this is what would
    # otherwise make every academic paper look like code.
    p = profile_material([POLITICS_READING])
    assert p.pointer_hits == 0


def test_argumentative_prose_offers_an_essay():
    assert "essay" in profile_material([POLITICS_READING]).recommended_types


def test_a_definition_heavy_deck_offers_identification_and_enumeration():
    p = profile_material([DEFINITIONS_DECK])
    assert "identification" in p.recommended_types
    assert "enumeration" in p.recommended_types


def test_recall_types_are_always_available():
    for text in (POINTERS_SLIDES, POLITICS_READING, DEFINITIONS_DECK, ""):
        rec = profile_material([text]).recommended_types
        assert "mcq" in rec and "short" in rec


def test_empty_material_recommends_nothing_specific():
    p = profile_material([])
    assert p.recommended_types == ["mcq", "short", "tf"]


def test_every_suggestion_carries_a_reason():
    for s in profile_material([POINTERS_SLIDES]).suggestions:
        assert s.reason.strip()


def test_python_material_is_detected_as_python():
    src = """
def shift(s):
    return s[5:]
for i in range(len(s)):
    print(s[i])
import sys
from os import path
data[0], data[1], data[2]
"""
    assert profile_material([src]).language == "python"


def test_every_quiz_type_has_a_suggestion_verdict():
    """The repo already guards its type lists against drift (test_quiz_types).
    This is the fourth list, so it gets the same guard: a new question type must
    be given a recommendation rule, not silently omitted from the chooser."""
    from manabi_server.api.artifacts import QUIZ_TYPES

    covered = {s.qtype for s in profile_material(["anything"]).suggestions}
    assert covered == set(QUIZ_TYPES), covered.symmetric_difference(set(QUIZ_TYPES))
