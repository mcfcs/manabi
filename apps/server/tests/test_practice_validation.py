"""A practice task is only offered when its own examples agree with its key."""

from manabi_server.services.practice import validate


def test_listed_examples_must_agree_with_the_reference():
    spec = {
        "alphabet": ["a", "b"],
        "reference_kind": "grammar",
        "examples_accepted": ["ab", "aabb"],
        "examples_rejected": ["abab"],  # the real mistake: balanced, so it IS accepted
    }
    v = validate("grammar", None, "S -> a S b S | ε", spec, 2000)
    assert not v.ok and "abab" in v.problem


def test_a_consistent_task_gets_samples_and_hidden_tests():
    spec = {
        "alphabet": ["a", "b"],
        "reference_kind": "grammar",
        "examples_accepted": ["ε", "abab"],
        "examples_rejected": ["ba", "a"],
    }
    v = validate("grammar", None, "S -> a S b S | ε", spec, 2000)
    assert v.ok
    assert {"s": "ε", "accept": True} in v.samples
    assert len(v.tests) > 1000
