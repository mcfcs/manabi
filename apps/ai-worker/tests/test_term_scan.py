"""Deterministic key-term candidates from definitional cues in the sources."""

from manabi_ai.context import scan_definition_candidates
from manabi_core.retrieval import ScopedChunk


def _chunk(cid: int, text: str) -> ScopedChunk:
    return ScopedChunk(
        id=cid,
        module_id=1,
        document_id=1,
        document_title="D",
        page_start=1,
        page_end=1,
        heading_path=None,
        text=text,
        token_count=10,
        content_hash=str(cid),
    )


def test_picks_up_definitional_cues_and_glossary_lines():
    chunks = [
        _chunk(
            1,
            "Encapsulation is defined as bundling data with the methods that operate on it. "
            "The term polymorphism refers to one interface with many implementations. "
            "A zero-overhead principle means you don't pay for what you don't use.",
        ),
        _chunk(
            2, "Dynamic dispatch: choosing the method at run time.\nLate binding: the same idea."
        ),
        _chunk(
            3, "Encapsulation is defined as data hiding here too, so it recurs. It is a good idea."
        ),
    ]
    terms = scan_definition_candidates(chunks)
    lowered = [t.lower() for t in terms]
    assert "encapsulation" in lowered
    assert "polymorphism" in lowered
    assert "zero-overhead principle" in lowered
    assert "dynamic dispatch" in lowered and "late binding" in lowered
    # pronoun subjects and bare determiners are never terms
    assert "it" not in lowered and "the term" not in lowered
    # recurring terms sort first; casing of the first appearance is kept
    assert terms[0] == "Encapsulation"


def test_dedupes_case_insensitively_and_respects_limit():
    chunks = [
        _chunk(i, f"Term{i} refers to thing {i}. term{i} refers to it again.") for i in range(60)
    ]
    terms = scan_definition_candidates(chunks, limit=25)
    assert len(terms) == 25
    assert len({t.lower() for t in terms}) == 25


def test_ignores_acronyms_and_short_tokens():
    chunks = [_chunk(1, "TCP is defined as a transport protocol. IO refers to input and output.")]
    assert scan_definition_candidates(chunks) == []  # acronyms are the acronym scan's job


def test_count_defined_matches_case_insensitively_and_by_containment():
    from manabi_ai.context import count_defined

    produced = [{"term": "encapsulation"}, {"term": "Dynamic Dispatch (late binding)"}]
    assert count_defined(["Encapsulation", "Dynamic dispatch", "Polymorphism"], produced) == 2
    assert count_defined([], produced) == 0
