"""A practice task is only offered when its key describes its statement:
the listed examples and an independent membership test must both agree."""

from manabi_server.services.practice import validate

BALANCED_PARENS = """def member(w):
    depth = 0
    for ch in w:
        depth += 1 if ch == "a" else -1
        if depth < 0:
            return False
    return depth == 0
"""


def _spec(test, accepted=(), rejected=()):
    return {
        "alphabet": ["a", "b"],
        "reference_kind": "grammar",
        "membership_test": test,
        "examples_accepted": list(accepted),
        "examples_rejected": list(rejected),
    }


def test_a_wrong_listed_example_is_dropped_not_fatal():
    # The real one: "abab is invalid" — but it is balanced. The key and the
    # membership test agree, so the example is the mistake: it is not shown.
    spec = _spec(BALANCED_PARENS, ["ab", "aabb"], ["abab"])
    v = validate("grammar", None, "S -> a S b S | ε", spec, 2000)
    assert v.ok, v.problem
    assert {"s": "abab", "accept": False} not in v.samples
    assert {"s": "ab", "accept": True} in v.samples


def test_a_key_narrower_than_the_statement_is_caught():
    # The real one: "equal numbers of a's and b's" with a grammar that misses
    # aabbba and 89 more — a correct student answer would have been failed.
    equal = "def member(w):\n    return w.count('a') == w.count('b')\n"
    key = "S -> a S b | b S a | a b S | b a S | ε"
    v = validate("grammar", None, key, _spec(equal, ["ab"], ["a"]), 2000)
    assert not v.ok and "membership test" in v.problem
    good = validate(
        "grammar", None, "S -> a S b S | b S a S | ε", _spec(equal, ["ab"], ["a"]), 2000
    )
    assert good.ok, good.problem


def test_a_consistent_task_gets_samples_and_hidden_tests():
    spec = _spec(BALANCED_PARENS, ["ε", "abab"], ["ba", "a"])
    v = validate("grammar", None, "S -> a S b S | ε", spec, 2000)
    assert v.ok, v.problem
    assert {"s": "ε", "accept": True} in v.samples
    assert len(v.tests) > 1000


def test_a_broken_membership_test_is_reported_not_trusted():
    v = validate(
        "grammar", None, "S -> a S b S | ε", _spec("def member(w):\n    return 1/0\n"), 2000
    )
    assert not v.ok and "fails" in v.problem
    assert not validate("grammar", None, "S -> a S b S | ε", _spec(""), 2000).ok
