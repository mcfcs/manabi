"""Deterministic follow-up detection for retrieval queries."""

from manabi_server.services.followup import (
    build_retrieval_query,
    is_followup,
    salient_terms,
)

ANSWER = (
    "The **Zero-Overhead Principle** says \"what you don't use, you don't pay for\". "
    "Stroustrup introduced it for C++; templates and inline functions are the usual "
    "examples, and virtual dispatch is the usual counter-example [1]."
)


def test_short_or_relative_messages_are_followups():
    for text in (
        "explain that more",
        "why?",
        "and the second one?",
        "what about templates",
        "can you give an example",
        "ELI5",
        "so it means the compiler removes it?",
    ):
        assert is_followup(text), text


def test_self_contained_questions_are_not_followups():
    for text in (
        "What is the difference between a compiler and an interpreter in language design",
        "Describe how TCP congestion control avoids collapse under heavy network load",
        "List the four pillars of object-oriented programming with definitions",
    ):
        assert not is_followup(text), text


def test_salient_terms_prefer_quotes_then_capitalized_then_frequency():
    terms = salient_terms(ANSWER)
    assert terms[0] == "what you don't use, you don't pay for"
    assert "Zero-Overhead Principle" in terms
    assert "Stroustrup" in terms
    assert len(terms) <= 12
    assert len({t.lower() for t in terms}) == len(terms)  # deduped


def test_topic_change_embeds_alone():
    q = build_retrieval_query(
        "What is the difference between a compiler and an interpreter in language design",
        ["explain that more", "what is the zero-overhead principle"],
        ANSWER,
    )
    assert q == "What is the difference between a compiler and an interpreter in language design"


def test_followup_carries_previous_turn_and_answer_terms():
    q = build_retrieval_query("explain that more", ["what is the zero-overhead principle"], ANSWER)
    lines = q.split("\n")
    assert lines[0] == "explain that more"
    assert lines[1] == "what is the zero-overhead principle"
    assert "Zero-Overhead Principle" in lines[2] and "Stroustrup" in lines[2]


def test_followup_without_answer_dedupes_and_caps():
    q = build_retrieval_query("why?", ["why?", "what is photosynthesis", "older"], None, max_prev=2)
    assert q == "why?\nwhat is photosynthesis"
    long_prev = "x" * 5000
    assert len(build_retrieval_query("why?", [long_prev], None)) == 2000
