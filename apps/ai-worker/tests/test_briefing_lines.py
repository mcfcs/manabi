"""Each briefing field is an optional paragraph, and models do not reliably
return "" for one they have nothing to say in. Two real briefings shipped junk
straight into the letter, so the assembly filters rather than trusting it."""

from manabi_ai.tasks_gen import _briefing_line


def test_the_emoticon_that_shipped_on_sep_14_is_dropped():
    assert _briefing_line(":[") is False


def test_stray_punctuation_is_dropped():
    for junk in ("", "   ", "-", "—", "...", ":)", "n/a".replace("n/a", "—"), "!"):
        assert _briefing_line(junk) is False, junk


def test_real_sentences_survive():
    assert _briefing_line("CSCI 199.2 Model is due today.") is True
    assert _briefing_line("Submit the CSCI 199.2 Model now, before 08:00.") is True


def test_a_short_closing_survives():
    # "Proceed." is Steven's habitual sign-off and must not be mistaken for junk.
    assert _briefing_line("Proceed.") is True


def test_a_bare_shouted_title_still_passes_the_filter():
    # Sep 12 shipped "GUIDANCE TREST" as a paragraph. It IS words, so the filter
    # cannot catch it — the prompt now forbids bare titles instead. Documented
    # here so the division of responsibility is explicit.
    assert _briefing_line("GUIDANCE TREST") is True


def test_a_single_letter_is_not_a_word():
    assert _briefing_line("x") is False
