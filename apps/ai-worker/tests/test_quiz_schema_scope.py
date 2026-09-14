"""Two fixes for the same measured failure.

Asked for `output` questions only, the model returned mcq, output,
identification, enumeration, short, mcq — five of six were discarded by the
type filter and the shortfall was refilled with extra generation calls. The
enum permitted all eight types regardless of the request, so the grammar was
never actually constraining anything.

And the one `output` question it did return said "Analyze the following C code
snippet" while showing no snippet at all.
"""

from manabi_ai import prompts
from manabi_ai.tasks_gen import fold_code_into_prompt


def _enum(schema: dict) -> list[str]:
    return schema["properties"]["questions"]["items"]["properties"]["qtype"]["enum"]


def test_a_single_requested_type_is_the_only_one_the_grammar_permits():
    assert _enum(prompts.quiz_schema_for(["output"])) == ["output"]


def test_several_requested_types_are_all_permitted():
    assert set(_enum(prompts.quiz_schema_for(["mcq", "tf"]))) == {"mcq", "tf"}


def test_unknown_types_are_ignored():
    assert _enum(prompts.quiz_schema_for(["output", "bogus"])) == ["output"]


def test_an_empty_request_falls_back_to_every_type():
    assert set(_enum(prompts.quiz_schema_for([]))) == set(prompts.ALL_QUIZ_TYPES)


def test_narrowing_does_not_mutate_the_shared_schema():
    prompts.quiz_schema_for(["output"])
    assert set(_enum(prompts.QUIZ_SCHEMA)) == set(prompts.ALL_QUIZ_TYPES)


def test_the_exercise_fork_narrows_too_and_keeps_its_relaxed_sources():
    schema = prompts.quiz_schema_for(["coding"], exercise=True)
    assert _enum(schema) == ["coding"]
    assert "source_ids" not in schema["properties"]["questions"]["items"]["required"]


def test_the_code_field_exists_and_is_optional():
    item = prompts.QUIZ_SCHEMA["properties"]["questions"]["items"]
    assert "code" in item["properties"]
    assert "code" not in item["required"]  # grammar brittleness rule


# ── folding code into the prompt ──────────────────────────────────────────


def test_a_code_field_becomes_a_fenced_block_in_the_prompt():
    item = {"qtype": "output", "prompt": "What does this print?", "code": 'printf("hi");'}
    fold_code_into_prompt(item)
    assert "```c" in item["prompt"]
    assert 'printf("hi");' in item["prompt"]
    assert item["prompt"].startswith("What does this print?")


def test_code_already_fenced_is_not_double_wrapped():
    item = {"qtype": "output", "prompt": "Output?", "code": '```c\nint x = 1;\n```'}
    fold_code_into_prompt(item)
    assert item["prompt"].count("```") == 2


def test_a_prompt_that_already_inlines_code_is_left_alone():
    inline = "Output?\n\n```c\nint a;\n```"
    item = {"qtype": "output", "prompt": inline, "code": "int b;"}
    fold_code_into_prompt(item)
    assert item["prompt"] == inline


def test_no_code_field_changes_nothing():
    item = {"qtype": "short", "prompt": "Define a pointer."}
    fold_code_into_prompt(item)
    assert item["prompt"] == "Define a pointer."


def test_an_empty_code_field_changes_nothing():
    item = {"qtype": "output", "prompt": "Output?", "code": "   "}
    fold_code_into_prompt(item)
    assert item["prompt"] == "Output?"
