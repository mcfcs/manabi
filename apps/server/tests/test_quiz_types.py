"""New quiz question types (enumeration / identification / essay / coding /
output): answer-shape validation, schema forks, server allowlist, and the
chat precision rule added alongside."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "ai-worker" / "src"))

from manabi_ai import prompts  # noqa: E402
from manabi_ai.tasks_gen import _question_answer  # noqa: E402
from manabi_server.api.artifacts import QUIZ_TYPES  # noqa: E402

ALL_TYPES = (
    "mcq", "tf", "short", "enumeration", "identification",
    "essay", "coding", "output",
)


# ── _question_answer per type ─────────────────────────────────────────────


def test_enumeration_answer_shape_and_discards():
    ok = _question_answer(
        {"qtype": "enumeration", "correct_items": [" OSI ", "TCP/IP", "", 3]}
    )
    assert ok == {"kind": "enumeration", "items": ["OSI", "TCP/IP"]}
    # fewer than 2 usable items → discarded
    assert _question_answer({"qtype": "enumeration", "correct_items": ["one"]}) is None
    assert _question_answer({"qtype": "enumeration"}) is None


def test_identification_answer():
    assert _question_answer(
        {"qtype": "identification", "correct_text": "encapsulation"}
    ) == {"kind": "identification", "text": "encapsulation"}
    assert _question_answer({"qtype": "identification"}) is None


def test_essay_answer_with_key_points():
    ok = _question_answer(
        {
            "qtype": "essay",
            "correct_text": "A model answer.",
            "key_points": ["mentions X", "  ", "explains Y"],
        }
    )
    assert ok == {
        "kind": "essay",
        "model_answer": "A model answer.",
        "key_points": ["mentions X", "explains Y"],
    }
    # key_points optional
    assert _question_answer({"qtype": "essay", "correct_text": "m"})["key_points"] == []
    assert _question_answer({"qtype": "essay"}) is None


def test_coding_and_output_answers():
    assert _question_answer({"qtype": "coding", "correct_text": "```c\nint x;\n```"}) == {
        "kind": "coding",
        "solution": "```c\nint x;\n```",
    }
    assert _question_answer({"qtype": "output", "correct_text": "5 4 6"}) == {
        "kind": "output",
        "text": "5 4 6",
    }
    assert _question_answer({"qtype": "coding"}) is None
    assert _question_answer({"qtype": "output"}) is None


def test_legacy_types_unchanged():
    assert _question_answer(
        {"qtype": "mcq", "options": ["a", "b", "c", "d"], "correct_option": 2}
    ) == {"kind": "mcq", "correct_option": 2}
    assert _question_answer({"qtype": "tf", "correct_bool": False}) == {
        "kind": "tf",
        "value": False,
    }
    assert _question_answer({"qtype": "short", "correct_text": "ans"}) == {
        "kind": "short",
        "text": "ans",
    }


# ── Schemas ───────────────────────────────────────────────────────────────


def test_quiz_schemas_cover_all_types_with_optional_fields():
    for schema in (prompts.QUIZ_SCHEMA, prompts.QUIZ_EXERCISE_SCHEMA):
        item = schema["properties"]["questions"]["items"]
        assert set(item["properties"]["qtype"]["enum"]) == set(ALL_TYPES)
        # new answer fields exist but are OPTIONAL (grammar-safety: required
        # nested structures broke Ollama constrained decoding before)
        assert "correct_items" in item["properties"]
        assert "key_points" in item["properties"]
        assert "correct_items" not in item["required"]
        assert "key_points" not in item["required"]
    # exercise fork still relaxes source_ids only
    ex_item = prompts.QUIZ_EXERCISE_SCHEMA["properties"]["questions"]["items"]
    assert "source_ids" not in ex_item["required"]


def test_qtype_strings_fit_varchar16():
    assert all(len(t) <= 16 for t in ALL_TYPES)


def test_server_allowlist_matches():
    assert set(QUIZ_TYPES) == set(ALL_TYPES)
    kept = [t for t in ["enumeration", "bogus", "coding"] if t in QUIZ_TYPES]
    assert kept == ["enumeration", "coding"]


def test_prompt_version_bumped_to_v8():
    assert prompts.PROMPT_VERSION == "v8"


def test_quiz_prompts_describe_new_types():
    for p in (prompts.QUIZ_PROMPT, prompts.EXERCISE_QUIZ_PROMPT):
        for t in ("enumeration", "identification", "essay", "coding", "output"):
            assert f'"{t}"' in p


# ── Chat precision rule (shipped alongside) ───────────────────────────────


def test_chat_prompts_have_person_statement_precision_rule():
    needle = "When asked what a PERSON said"
    for p in (
        prompts.CHAT_PROMPT,
        prompts.REASONING_CHAT_PROMPT,
        prompts.GENERAL_ASSISTANT_PROMPT,
    ):
        assert needle in p
