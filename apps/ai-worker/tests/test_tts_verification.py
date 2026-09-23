from manabi_ai.tts_verification import transcript_problem


def test_detects_a_fluent_but_missing_vice_president_clause():
    expected = (
        "The Congress shall provide for the manner in which one who is to act as President "
        "shall be selected until a President or a Vice-President shall have qualified."
    )
    assert transcript_problem(expected, expected.replace("or a Vice-President ", ""))


def test_detects_speech_followed_by_unintelligible_sound():
    assert transcript_problem(
        "of his office, and until he transmits to them a written declaration to the contrary, "
        "such powers and duties shall be discharged by the Vice-President as Acting President.",
        "I",
    )


def test_does_not_treat_numeric_formatting_as_an_omitted_phrase():
    assert (
        transcript_problem(
            "The legislature has one hundred ninety five thousand members in this example.",
            "The legislature has 195,000 members in this example.",
        )
        is None
    )


def test_tolerates_isolated_recognition_errors_for_uncommon_legal_terms():
    assert (
        transcript_problem(
            "Charitable institutions, churches and parsonages or convents appurtenant thereto, "
            "mosques, non-profit cemeteries shall be exempt from taxation.",
            "Charitable institutions, churches and personages are convinced of pertinent thereto, "
            "mosques, non-profit cemeteries shall be exempt from taxation.",
        )
        is None
    )


def test_tolerates_short_labels_and_punctuation_differences():
    assert transcript_problem("Article VI.", "Article six") is None
    assert (
        transcript_problem(
            "The President, or Acting President, shall appoint the members.",
            "The president or acting president shall appoint the members!",
        )
        is None
    )
