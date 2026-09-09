"""split_sentences feeds every voice in the app — narration, lecture audio and
Steven's spoken chat replies. A fragment with nothing speakable in it is a 400
from GPT-SoVITS, which fails the whole recording, so the splitter must never
emit one."""

from manabi_ai.tts_client import split_sentences


def test_a_paragraph_opening_mid_sentence_does_not_emit_a_bare_period():
    # The real failure: doc 46 segment 58 began with an ellipsis, which
    # normalizes to ". " and split into a lone "." that 400d the recording.
    out = split_sentences("… but for low-resource languages, we need theory.")
    assert out == ["but for low-resource languages, we need theory."]


def test_punctuation_only_input_yields_nothing():
    assert split_sentences("… — ...") == []
    assert split_sentences("") == []
    assert split_sentences("   ") == []


def test_ordinary_sentences_still_split_one_per_fragment():
    assert split_sentences("First one. Second one! Third one?") == [
        "First one.",
        "Second one!",
        "Third one?",
    ]


def test_a_bullet_glyph_alone_is_dropped_but_a_bulleted_line_survives():
    assert split_sentences("•") == []
    assert split_sentences("• Bias and Fairness in LLMs") == ["• Bias and Fairness in LLMs"]


def test_every_fragment_has_something_to_say():
    messy = "…Alpha. — Beta… • Gamma.  ...  Delta."
    assert all(any(c.isalnum() for c in f) for f in split_sentences(messy))


def test_overlong_sentences_hard_wrap_without_emitting_empty_pieces():
    out = split_sentences("word " * 200, group_chars=60)
    assert len(out) > 1
    assert all(f.strip() and any(c.isalnum() for c in f) for f in out)
