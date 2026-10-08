"""Grammar / regex / DFA answers are judged by the language they describe."""

from manabi_server.processing.formal import (
    all_words,
    build_tests,
    check,
    grammar_accepts,
    parse_dfa,
    parse_grammar,
)

ANBN = "S -> a S b | ε"


def test_grammar_membership_with_epsilon_and_left_recursion():
    g = parse_grammar(ANBN)
    assert grammar_accepts(g, ())
    assert grammar_accepts(g, tuple("aabb"))
    assert not grammar_accepts(g, tuple("aab"))
    left = parse_grammar("E -> E + T | T\nT -> T * F | F\nF -> ( E ) | i")
    assert grammar_accepts(left, tuple("i+i*i"))
    assert not grammar_accepts(left, tuple("i+*i"))


def test_compact_rules_without_spaces_are_read_per_symbol():
    g = parse_grammar("S → aSb | ab")
    assert grammar_accepts(g, tuple("aaabbb"))
    assert not grammar_accepts(g, ())


def test_a_different_but_equivalent_grammar_is_accepted():
    tests, problem = build_tests("grammar", ANBN, ["a", "b"])
    assert problem == ""
    other = "S -> A | ε\nA -> a A b | a b"
    assert check("grammar", other, tests).verdict == "accepted"


def test_a_wrong_grammar_gets_the_shortest_counterexample():
    tests, _ = build_tests("grammar", ANBN, ["a", "b"])
    v = check("grammar", "S -> a S b | a b", tests)  # forgot ε
    assert v.verdict == "wrong"
    assert v.mismatches[0] == {"string": "ε", "expected": True}


def test_regex_and_dfa_answers_against_a_regex_reference():
    # even number of a's over {a, b}
    tests, problem = build_tests("regex", "(b*ab*a)*b*", ["a", "b"])
    assert problem == ""
    assert check("regex", "b*(ab*ab*)*", tests).verdict == "accepted"
    dfa = "start: E\naccept: E\nE a O\nE b E\nO a E\nO b O"
    assert check("dfa", dfa, tests).verdict == "accepted"
    wrong = check("dfa", "start: E\naccept: O\nE a O\nE b E\nO a E\nO b O", tests)
    assert wrong.verdict == "wrong" and wrong.mismatches[0]["string"] == "ε"


def test_unreadable_answers_explain_themselves():
    assert check("grammar", "S a S b", []).verdict == "format_error"
    assert "deterministic" in check("dfa", "start: p\naccept: p\np a p\np a q", []).error
    assert check("regex", "a.b", []).verdict == "format_error"


def test_a_trivial_reference_is_refused():
    assert build_tests("regex", "(a|b)*", ["a", "b"])[1]  # accepts everything
    assert build_tests("grammar", "S -> c", ["a", "b"])[1]  # outside the alphabet


def test_the_length_bound_keeps_the_check_quick():
    assert len(all_words(["a", "b"])) <= 4000
    assert max(len(w) for w in all_words(["a", "b"])) >= 10
    assert max(len(w) for w in all_words(["a", "b", "c"])) >= 7


def test_dfa_arrow_notation():
    d = parse_dfa("start: q0\naccept: q1\nq0 -a-> q1\nq1 --b--> q0")
    assert d.delta[("q0", "a")] == "q1" and d.delta[("q1", "b")] == "q0"
