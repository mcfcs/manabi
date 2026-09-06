"""Spoken normalisation for narration (pure)."""

from manabi_server.processing.spoken import (
    ensure_stop,
    expand_abbreviations,
    speak_numbers,
    strip_citations,
    to_spoken,
    unshout,
)


def test_parenthetical_citations_are_dropped_but_prose_parentheses_stay():
    s = strip_citations(
        "Institutions are the 'rules of the game' (North, 1990) which shape behaviour "
        "(see Knight, 1992; Acemoglu et al., 2004: 12–14) and (IMF, 2005: 126–127) "
        "matter (as most economists agree)."
    )
    assert "North" not in s and "Knight" not in s and "IMF" not in s
    assert "(as most economists agree)" in s
    assert "()" not in s


def test_inline_year_and_bracket_citations():
    assert strip_citations("North (1990) argues that rules [12] and norms [3, 4] differ.") == (
        "North argues that rules and norms differ."
    )


def test_abbreviations_read_like_a_lecturer():
    s = expand_abbreviations(
        "Formal rules, e.g. statutes, differ from norms, i.e. habits, cf. North et al."
    )
    assert "for example, statutes" in s and "that is, habits" in s
    assert "compare North and colleagues" in s
    assert (
        expand_abbreviations("about 12% of firms & 3 banks")
        == "about 12 percent of firms and 3 banks"
    )
    assert expand_abbreviations("see Fig. 2 and pp. 12–14") == "see Figure 2 and pages 12–14"


def test_number_ranges_are_spoken_as_to():
    assert speak_numbers("J. Int. Dev. 23, 319–337 (2011)") == "J. Int. Dev. 23, 319 to 337 (2011)"
    assert (
        speak_numbers("a well-known poverty-reduction plan")
        == "a well-known poverty-reduction plan"
    )


def test_all_caps_headings_are_unshouted_but_acronyms_survive():
    assert (
        unshout("WHAT ARE INSTITUTIONS AND ORGANISATIONS?")
        == "What Are Institutions and Organisations?"
    )
    assert unshout("funded by DFID and the IMF") == "funded by DFID and the IMF"


def test_to_spoken_for_headings_drops_numbering_and_ends_with_a_stop():
    assert to_spoken("2.1.1 Formal and informal institutions", "heading") == (
        "Formal and informal institutions."
    )
    assert to_spoken("1 INTRODUCTION", "heading") == "Introduction."
    assert to_spoken("REFERENCES", "heading") == "References."


def test_display_title_drops_stray_marks_but_keeps_casing():
    from manabi_server.processing.spoken import clean_display_title

    assert clean_display_title("‘‘DON’T MOURN; ORGANIZE’’y INSTITUTIONS AND") == (
        '"DON\'T MOURN; ORGANIZE" INSTITUTIONS AND'
    )


def test_to_spoken_paragraph_end_to_end():
    text = (
        "Understood as ‘rules of the game’ (North, 1990), institutions shape—but do not "
        "determine—behaviour; see http://www.ippg.org.uk/papers/dp14.pdf and e.g. the "
        "IPPG ﬁndings (Leftwich, 2007: 5–6)"
    )
    spoken = to_spoken(text)
    assert spoken == (
        "Understood as 'rules of the game', institutions shape—but do not determine—behaviour; "
        "see and for example, the IPPG findings."
    )
    assert ensure_stop("done") == "done." and ensure_stop("why?") == "why?"
