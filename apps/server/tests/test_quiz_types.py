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
    "mcq",
    "tf",
    "short",
    "enumeration",
    "identification",
    "essay",
    "coding",
    "output",
)


# ── _question_answer per type ─────────────────────────────────────────────


def test_enumeration_answer_shape_and_discards():
    ok = _question_answer({"qtype": "enumeration", "correct_items": [" OSI ", "TCP/IP", "", 3]})
    assert ok == {"kind": "enumeration", "items": ["OSI", "TCP/IP"]}
    # fewer than 2 usable items → discarded
    assert _question_answer({"qtype": "enumeration", "correct_items": ["one"]}) is None
    assert _question_answer({"qtype": "enumeration"}) is None


def test_identification_answer():
    assert _question_answer({"qtype": "identification", "correct_text": "encapsulation"}) == {
        "kind": "identification",
        "text": "encapsulation",
    }
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


def test_prompt_version_current():
    assert prompts.PROMPT_VERSION == "v10"


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


# ── Dispute (verify_question) + per-question regenerate ───────────────────


def test_verify_schema_is_flat_all_required():
    """The grammar-safe shape: flat object, every field required."""
    s = prompts.VERIFY_QUESTION_SCHEMA
    assert set(s["required"]) == set(s["properties"].keys())
    assert all(v["type"] in ("boolean", "string") for v in s["properties"].values())


def test_answer_display_per_kind():
    from manabi_ai.tasks_gen import _answer_display

    assert (
        _answer_display({"kind": "mcq", "correct_option": 1}, ["a", "b", "c", "d"]) == "option 1: b"
    )
    assert _answer_display({"kind": "tf", "value": True}, None) == "true"
    assert _answer_display({"kind": "enumeration", "items": ["x", "y"]}, None) == "x; y"
    assert _answer_display({"kind": "essay", "model_answer": "m", "key_points": []}, None) == "m"
    assert _answer_display({"kind": "coding", "solution": "s"}, None) == "s"
    assert _answer_display({"kind": "output", "text": "5 4"}, None) == "5 4"
    assert _answer_display({"kind": "short", "text": "t"}, None) == "t"
    assert _answer_display(None, None) == "(none)"
    # out-of-range option index never crashes the prompt build
    assert _answer_display({"kind": "mcq", "correct_option": 9}, ["a"]) == "option 9: ?"


def test_task_name_contracts():
    from manabi_ai import tasks_gen
    from manabi_server.jobs.queue import (
        REGENERATE_QUESTION_TASK,
        VERIFY_QUESTION_TASK,
    )

    assert VERIFY_QUESTION_TASK == "manabi_ai.tasks.verify_question"
    assert REGENERATE_QUESTION_TASK == "manabi_ai.tasks.regenerate_question"
    assert hasattr(tasks_gen, "verify_question")
    assert hasattr(tasks_gen, "regenerate_question")


class _Scalars:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def all(self):
        return self._rows


class _Result:
    def __init__(self, *, scalars=(), scalar_one=None):
        self._scalars = scalars
        self._scalar_one = scalar_one

    def scalars(self):
        return _Scalars(self._scalars)

    def scalar_one(self):
        return self._scalar_one


class _FakeDB:
    def __init__(self, results=()):
        self.results = list(results)
        self.added = []

    async def execute(self, *a, **k):
        return self.results.pop(0) if self.results else _Result()

    def add(self, obj):
        self.added.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = 100 + len(self.added)

    async def flush(self):
        pass

    async def commit(self):
        pass


class _User:
    id = 1


def _question_db():
    import types

    return (
        _FakeDB(
            [
                _Result(scalar_one=types.SimpleNamespace(id=3, module_id=6)),
                _Result(scalars=[]),  # no in-flight jobs
            ]
        ),
        types.SimpleNamespace(id=9, artifact_id=3),
    )


async def test_challenge_endpoint_defers_with_user_answer(monkeypatch):
    from manabi_server.api import artifacts

    captured: dict = {}

    async def fake_defer(task, queue, **kwargs):
        captured.update({"task": task, **kwargs})
        return 999

    monkeypatch.setattr(artifacts, "defer_task", fake_defer)
    db, question = _question_db()
    ref = await artifacts.challenge_question(
        artifacts.ChallengeIn(user_answer="  b*(ba)*a*  "),
        question=question,
        user=_User(),
        db=db,
    )
    assert ref.job_id is not None
    assert captured["task"] == "manabi_ai.tasks.verify_question"
    assert captured["question_id"] == 9
    assert captured["user_answer"] == "b*(ba)*a*"  # stripped


async def test_regenerate_endpoint_defers(monkeypatch):
    from manabi_server.api import artifacts

    captured: dict = {}

    async def fake_defer(task, queue, **kwargs):
        captured.update({"task": task, **kwargs})
        return 999

    monkeypatch.setattr(artifacts, "defer_task", fake_defer)
    db, question = _question_db()
    await artifacts.regenerate_quiz_question(question=question, user=_User(), db=db)
    assert captured["task"] == "manabi_ai.tasks.regenerate_question"
    assert captured["question_id"] == 9
