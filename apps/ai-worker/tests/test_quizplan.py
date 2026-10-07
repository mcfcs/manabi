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


def test_selection_follows_the_mix_not_the_generation_order():
    from manabi_ai.quizplan import select_by_quota

    # mcq candidates came first; the mix asks for half output
    items = [(0, "mcq")] * 6 + [(0, "output")] * 4
    picked = select_by_quota(items, {0: 4}, {"output": 1, "mcq": 1}, 4)
    assert [items[i][1] for i in picked].count("output") == 2


def test_selection_fills_a_missing_type_from_the_rest():
    from manabi_ai.quizplan import select_by_quota

    items = [(0, "mcq")] * 5
    assert len(select_by_quota(items, {0: 4}, {"output": 3, "mcq": 1}, 4)) == 4


def test_selection_honours_each_units_share():
    from manabi_ai.quizplan import select_by_quota

    items = [(0, "mcq")] * 5 + [(1, "mcq")] * 5
    picked = select_by_quota(items, {0: 2, 1: 3}, {"mcq": 1}, 5)
    assert [items[i][0] for i in picked].count(1) == 3


def test_shuffle_moves_the_key_with_its_option():
    from manabi_ai.quizplan import shuffle_options

    opts = ["right", "w1", "w2", "w3"]
    new, key = shuffle_options(opts, 0, "q1")
    assert new[key] == "right" and sorted(new) == sorted(opts)
    assert shuffle_options(opts, 0, "q1") == (new, key)  # deterministic


def test_shuffle_spreads_keys_across_positions():
    from manabi_ai.quizplan import shuffle_options

    keys = {shuffle_options(["a", "b", "c", "d"], 0, f"question {i}")[1] for i in range(40)}
    assert len(keys) >= 3


def test_options_that_refer_to_each_other_keep_their_order():
    from manabi_ai.quizplan import shuffle_options

    opts = ["x", "y", "Both A and B", "None of the above"]
    assert shuffle_options(opts, 2, "s") == (opts, 2)


def test_shuffle_mcq_skips_explanations_that_name_a_letter():
    from manabi_ai.tasks_gen import shuffle_mcq

    base = {"qtype": "mcq", "prompt": "p", "options": ["w", "x", "y", "z"], "correct_option": 0}
    named = {**base, "explanation": "Option A is right because..."}
    shuffle_mcq(named)
    assert named["options"] == ["w", "x", "y", "z"]
    code = {**base, "prompt": "q7", "explanation": "max(a) returns the larger value."}
    shuffle_mcq(code)
    assert code["options"][code["correct_option"]] == "w"


def test_assumed_semantics_go_to_the_audit_not_the_compiler():
    p = "Assume call by value-result. What is printed?\n\n```c\nint main(){printf(\"%d\", 1);}\n```"
    assert not executable_check_applies("output", p)


def test_mermaid_is_cleaned_and_kind_checked():
    from manabi_ai.tasks_gen import clean_mermaid

    assert clean_mermaid("```mermaid\nflowchart TD\n  a --> b\n```") == "flowchart TD\n  a --> b"
    assert clean_mermaid("%%{init: {}}%%\nstateDiagram-v2\n[*] --> q0").startswith("stateDiagram")
    assert clean_mermaid("pie title x") is None
    assert clean_mermaid("") is None


def test_light_types_still_get_slots_when_the_quiz_is_split_into_small_units():
    # The SocSc final: 20 questions over seven batches owing 2-3 each, with
    # essay and enumeration at ~0.8 in 10. Rounded per batch, neither appeared.
    from manabi_ai.quizplan import allocate, unit_mixes

    mix = {"mcq": 4.17, "identification": 2.5, "tf": 1.67, "essay": 0.83, "enumeration": 0.83}
    owed = {0: 3, 1: 3, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2}
    assert all(allocate(n, mix)["essay"] == 0 for n in owed.values())  # the old starvation

    per_unit = unit_mixes(owed, mix)
    totals: dict[str, float] = {}
    for u, n in owed.items():
        assert sum(per_unit[u].values()) == n
        for t, w in per_unit[u].items():
            totals[t] = totals.get(t, 0) + w
    assert totals == {t: float(q) for t, q in allocate(20, mix).items()}
    assert totals["essay"] == 2 and totals["enumeration"] == 2
    # spread out, not bunched into one unit
    assert sum(1 for m in per_unit.values() if m.get("essay")) == 2


def test_selection_follows_each_units_own_mix():
    from manabi_ai.quizplan import select_by_quota

    items = [(0, "mcq"), (0, "mcq"), (0, "essay"), (1, "mcq"), (1, "mcq")]
    per_unit = {0: {"mcq": 1.0, "essay": 1.0}, 1: {"mcq": 2.0}}
    picked = select_by_quota(items, {0: 2, 1: 2}, {"mcq": 9, "essay": 1}, 4, per_unit)
    assert 2 in picked and len(picked) == 4
