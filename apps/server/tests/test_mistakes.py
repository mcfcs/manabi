"""Mistakes deck: a wrongly answered question becomes a card that asks it the
same way and answers it with the key and the explanation."""

from types import SimpleNamespace

from manabi_server.services.mistakes import card_sides, response_is_wrong


def _q(**kw):
    base = {
        "id": 1,
        "ord": 0,
        "qtype": "mcq",
        "prompt": "Q?",
        "options": None,
        "answer": {},
        "explanation": None,
        "module_id": 2,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_only_graded_wrong_answers_count():
    assert response_is_wrong({"response": "B", "grade": "wrong"})
    assert not response_is_wrong({"response": "B", "grade": "right"})
    assert not response_is_wrong({"response": "", "grade": "skip"})
    assert not response_is_wrong("B")  # older attempts stored the bare answer


def test_an_mcq_card_keeps_its_lettered_options_and_names_the_key():
    q = _q(
        prompt="Which power works through institutions?",
        options=["Compulsory", "Institutional"],
        answer={"kind": "mcq", "correct_option": 1},
        explanation="Indirect control through rules and procedures.",
    )
    front, back = card_sides(q)
    assert front.endswith("A. Compulsory\nB. Institutional")
    assert back.startswith("B. Institutional")
    assert "Indirect control" in back


def test_output_and_enumeration_answers_read_naturally():
    out = _q(
        qtype="output",
        prompt='What prints?\n\n```c\nputs("hi");\n```',
        answer={"kind": "output", "text": "hi"},
    )
    assert card_sides(out) == (out.prompt, "hi")
    enum = _q(
        qtype="enumeration",
        prompt="Name the gates.",
        answer={"kind": "enumeration", "items": ["forget", "input", "output"]},
    )
    assert card_sides(enum)[1] == "forget, input, output"


def test_a_question_without_a_usable_key_makes_no_card():
    assert card_sides(_q(answer={"kind": "mcq", "correct_option": 5}, options=["a"])) is None
