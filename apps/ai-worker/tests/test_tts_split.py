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


def test_section_label_stays_with_its_sentence():
    text = "Section 1. The executive power shall be vested in the President of the Philippines."
    assert split_sentences(text) == [text]


def test_uppercase_numbered_labels_are_words_but_acronyms_stay_intact():
    assert split_sentences("SECTION 22. The UN and IMF may attend.") == [
        "Section 22. The UN and IMF may attend."
    ]
    for label in ("ARTICLE VII", "CHAPTER 2", "PART IV"):
        word, number = label.split()
        assert split_sentences(f"{label}. These provisions apply to the UN.") == [
            f"{word.capitalize()} {number}. These provisions apply to the UN."
        ]


def test_abbreviations_and_decimal_numbers_are_not_sentence_breaks():
    text = "Dr. Reyes paid 3.50 in the U.S. today. Next sentence."
    assert split_sentences(text) == ["Dr. Reyes paid 3.50 in the U.S. today.", "Next sentence."]


def test_long_legal_sentence_prefers_clauses_and_preserves_every_word():
    text = (
        "Section 3. No person shall be a Senator unless he is a natural-born citizen "
        "of the Philippines and, on the day of the election, is at least thirty-five "
        "years of age, able to read and write, a registered voter, and a resident "
        "of the Philippines for not less than two years immediately preceding "
        "the day of the election."
    )
    parts = split_sentences(text)
    assert " ".join(parts) == text
    assert all(len(p) <= 200 for p in parts)
    assert parts[0].endswith(",")
