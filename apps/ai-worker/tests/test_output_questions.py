"""`output` questions are the only type whose answer can be checked by running
the code — but only if the question actually contains code and claims a
deterministic result. Both failures were observed in a real generation run.
"""

from manabi_ai.tasks_gen import _question_answer

CODE = "```c\nint n = 5;\nprintf(\"%d\\n\", n);\n```"


def _q(**kw) -> dict:
    base = {"qtype": "output", "prompt": f"What does this print?\n\n{CODE}"}
    base.update(kw)
    return base


def test_a_normal_output_question_is_accepted():
    assert _question_answer(_q(correct_text="5")) == {"kind": "output", "text": "5"}


def test_a_question_that_shows_no_code_is_rejected():
    # The real failure: the model wrote "Given the following C code snippet…"
    # and omitted the snippet entirely.
    assert _question_answer(
        _q(prompt="Given the following C code snippet, what is the output?", correct_text="5")
    ) is None


def test_an_empty_fence_does_not_count_as_code():
    assert _question_answer(_q(prompt="Look:\n```c\n```", correct_text="5")) is None


def test_a_placeholder_answer_is_rejected():
    # The real failure: "10\n10\n<some address>" for code printing a pointer.
    assert _question_answer(_q(correct_text="10\n10\n<some address>")) is None


def test_non_deterministic_answers_are_rejected():
    for bad in (
        "some address",
        "a memory address",
        "varies by platform",
        "garbage value",
        "undefined",
        "depends on the compiler",
        "implementation-defined",
        "<undefined>",
    ):
        assert _question_answer(_q(correct_text=bad)) is None, bad


def test_a_missing_answer_is_still_rejected():
    assert _question_answer(_q(correct_text="")) is None
    assert _question_answer(_q()) is None


def test_legitimate_answers_containing_those_words_in_context_still_pass():
    # "0" and "-1" are perfectly normal outputs; only the non-determinism
    # vocabulary is rejected, not every short answer.
    assert _question_answer(_q(correct_text="0")) is not None
    assert _question_answer(_q(correct_text="-1")) is not None
    assert _question_answer(_q(correct_text="Address: 0x10")) is not None


def test_other_question_types_are_unaffected_by_the_code_requirement():
    assert _question_answer(
        {"qtype": "short", "prompt": "No code here", "correct_text": "an answer"}
    ) == {"kind": "short", "text": "an answer"}
    assert _question_answer(
        {"qtype": "mcq", "prompt": "No code", "options": ["a", "b"], "correct_option": 1}
    ) == {"kind": "mcq", "correct_option": 1}
