from manabi_ai import cardstyle


def test_blank_styles_follow_the_material():
    code = cardstyle.plan(None, is_code=True, count=10)
    assert set(code) == {"term", "short", "code"} and sum(code.values()) == 10
    reading = cardstyle.plan(None, is_code=False, count=10)
    assert set(reading) == {"definition", "short", "term"} and "code" not in reading


def test_chosen_styles_share_the_count_and_code_needs_code_material():
    assert cardstyle.plan(["term", "code"], is_code=True, count=12) == {"term": 6, "code": 6}
    assert cardstyle.plan(["code"], is_code=False, count=8) == {"short": 8}
    assert cardstyle.plan(["definition", "code"], is_code=False, count=6) == {"definition": 6}


def test_term_backs_are_terms_and_fronts_do_not_give_them_away():
    ok = "Binding a name to a value before the program runs."
    assert cardstyle.problem("term", ok, "static binding") is None
    # The real CSCI 70 shape this replaces: a 24-word paragraph on the back.
    assert cardstyle.problem(
        "term",
        "Procedural programming",
        "The focus is on processing and algorithms needed for computation, supported by "
        "functions and selection statements.",
    )
    assert cardstyle.problem("term", "Static binding happens at compile time.", "static binding")


def test_short_answers_are_capped_but_lists_are_allowed():
    assert (
        cardstyle.problem("short", "Why use RAG?", "It grounds answers in retrieved documents.")
        is None
    )
    assert (
        cardstyle.problem("short", "Name the LSTM gates.", "forget gate, input gate, output gate")
        is None
    )
    long = " ".join(["word"] * 20)
    assert cardstyle.problem("short", "Why?", long)


def test_definition_cards_may_have_sentence_backs():
    back = (
        "Politics consists of the debates, conflicts, decisions, and co-operation among "
        "individuals, groups, and organizations regarding the control of resources."
    )
    assert cardstyle.problem("definition", "Everyday politics", back) is None
    assert cardstyle.problem(
        "definition", "What is the meaning of everyday politics in the reading?", back
    )


def test_code_cards_need_code_and_a_deterministic_output():
    front = 'What does this print?\n\n```c\nint x = 3;\nprintf("%d", x++ + 1);\n```'
    assert cardstyle.problem("code", front, "4") is None
    assert cardstyle.problem("code", "What does x++ print?", "4")
    assert cardstyle.problem("code", front, "<some address>")


def test_a_one_letter_term_is_not_found_inside_other_words():
    assert (
        cardstyle.problem("term", "The procedural language Ritchie designed at Bell Labs.", "C")
        is None
    )
