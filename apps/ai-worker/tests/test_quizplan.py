"""Planning and blind-audit helpers. The regex cases are the real wrong keys
found in the 2026-10-07 audit of stored CSCI 70 questions."""

from manabi_ai.quizplan import (
    allocate,
    answers_agree,
    assign_types,
    executable_check_applies,
    normalize_mix,
    regex_equivalent,
)


def test_allocate_is_proportional_and_exact():
    out = allocate(10, {"a": 3, "b": 1, "c": 1})
    assert sum(out.values()) == 10
    assert out["a"] == 6 and out["b"] == 2 and out["c"] == 2


def test_allocate_respects_a_minimum_when_affordable():
    out = allocate(5, {"big": 100, "s1": 1, "s2": 1}, minimum=1)
    assert out["s1"] >= 1 and out["s2"] >= 1 and sum(out.values()) == 5
    # not affordable -> plain proportional, still exact
    out = allocate(2, {"a": 1, "b": 1, "c": 1}, minimum=1)
    assert sum(out.values()) == 2


def test_normalize_mix_defaults_to_uniform():
    assert normalize_mix(["mcq", "tf"], None) == {"mcq": 1.0, "tf": 1.0}
    assert normalize_mix(["mcq", "output"], {"output": 3, "mcq": 1, "tf": 9}) == {
        "mcq": 1.0,
        "output": 3.0,
    }


def test_output_questions_only_go_to_code_targets():
    flags = [True, False, True, False, False, True]
    types = assign_types(flags, {"output": 1, "mcq": 1})
    assert len(types) == 6
    for f, t in zip(flags, types, strict=True):
        if t == "output":
            assert f


def test_too_few_code_targets_spill_into_other_types():
    types = assign_types([False, False, False, True], {"output": 3, "mcq": 1})
    assert types.count("output") == 1
    assert types.count("mcq") == 3


def test_all_code_only_types_still_fill_every_target():
    types = assign_types([False, True], {"output": 1})
    assert types == ["output", "output"]


def test_mixed_types_are_spread_not_clumped():
    types = assign_types([False] * 6, {"mcq": 1, "tf": 1, "identification": 1})
    assert types[:3] != ["mcq", "mcq", "mcq"]
    assert sorted(types) == sorted(["mcq", "mcq", "tf", "tf", "identification", "identification"])


def test_regex_keys_the_model_got_wrong():
    # "no substring ab" — keyed a*b*, correct b*a*
    assert regex_equivalent("a*b*", "b*a*") is False
    # "zero or one b" — keyed a*|a*b*a*, correct a*|a*ba*
    assert regex_equivalent("a*|a*b*a*", "a*|a*ba*") is False
    # "exactly two b's" — keyed a*ba*a*b*, correct a*ba*ba*
    assert regex_equivalent("a*ba*a*b*", "a*ba*ba*") is False


def test_equivalent_regexes_written_differently_agree():
    assert regex_equivalent("(a|b)*", "(a*b*)*") is True
    assert regex_equivalent("a(ba)*", "(ab)*a") is True
    assert regex_equivalent("a|ε", "(a|ε)") is True


def test_prose_is_not_a_regex():
    assert regex_equivalent("lexical analysis", "scanner") is None


def test_answers_agree_by_type():
    assert answers_agree("mcq", {"kind": "mcq", "correct_option": 2}, {"answer_option": 2})
    assert not answers_agree("mcq", {"kind": "mcq", "correct_option": 2}, {"answer_option": 1})
    assert answers_agree("tf", {"kind": "tf", "value": False}, {"answer_bool": False})
    assert answers_agree(
        "identification", {"kind": "identification", "text": "Lexeme"}, {"answer_text": "a lexeme"}
    )
    assert not answers_agree(
        "short", {"kind": "short", "text": "a*b*"}, {"answer_text": "b*a*"}
    )


def test_code_output_questions_are_left_to_the_compiler():
    code = "```c\nint main(){printf(\"%d\", 1);}\n```"
    assert executable_check_applies("output", "What is printed?\n\n" + code)
    assert executable_check_applies("mcq", "What does the program print?\n\n" + code)
    assert not executable_check_applies("mcq", "Which paradigm uses objects?")
    assert not executable_check_applies("tf", "This program prints 1.\n\n" + code)
