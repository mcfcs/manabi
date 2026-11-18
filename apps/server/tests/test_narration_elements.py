"""Steven's script from extracted (OCR) elements: what a scanned PDF is read from."""

from manabi_server.processing.narration_script import build_script_from_elements


def _texts(rows):
    return [s.text for s in build_script_from_elements(rows).segments]


def test_list_items_are_read():
    # Sen ch. 6 p.148: the three considerations are stored as "list" elements
    rows = [
        (3, "paragraph", "There are three different considerations that take us there:"),
        (3, "list", "their direct importance in human living associated with basic capabilities;"),
        (3, "list", "their instrumental role in enhancing the hearing that people get;"),
        (3, "list", "their constructive role in the conceptualization of needs."),
        (3, "paragraph", "These different considerations will be discussed presently."),
    ]
    texts = _texts(rows)
    assert len(texts) == 5
    assert texts[2].startswith("their instrumental role")


def test_a_paragraph_split_by_ocr_is_read_as_one():
    rows = [
        (1, "paragraph", "Throughout his long reel and political life, Estrada had shrewdly"),
        (1, "paragraph", "cultivated the image of a man fighting for the downtrodden."),
        (2, "paragraph", "In a study of the 1987 congressional and 1988 local elections, Eric"),
        (2, "paragraph", "Gutierrez, Ildefonso Torrente, and Noli Narca saw the clans' return."),
    ]
    assert _texts(rows) == [
        "Throughout his long reel and political life, Estrada had shrewdly cultivated the image "
        "of a man fighting for the downtrodden.",
        "In a study of the 1987 congressional and 1988 local elections, Eric Gutierrez, "
        "Ildefonso Torrente, and Noli Narca saw the clans' return.",
    ]


def test_hyphenated_breaks_join_and_lone_numbers_vanish():
    rows = [
        (1, "paragraph", "the leftist parties (espe-"),
        (1, "paragraph", "cially the emergent ones) did battle with elite rule."),
        (2, "paragraph", "the political clans"),
        (2, "paragraph", "1"),
        (2, "paragraph", "had reasserted themselves as the real source of power."),
    ]
    assert _texts(rows) == [
        "the leftist parties (especially the emergent ones) did battle with elite rule.",
        "the political clans had reasserted themselves as the real source of power.",
    ]


def test_a_heading_left_as_a_paragraph_is_not_glued_to_the_next():
    rows = [
        (3, "paragraph", "The Importance of the Study"),
        (3, "paragraph", "This book is about postauthoritarian politics in the Philippines."),
    ]
    assert len(_texts(rows)) == 2


def test_the_bibliography_ends_the_reading():
    rows = [
        (5, "paragraph", "The last argued paragraph of the chapter ends here."),
        (6, "heading", "References"),
        (6, "paragraph", "Abinales, P. 2000. Making Mindanao. Quezon City: Ateneo Press."),
    ]
    assert _texts(rows) == ["The last argued paragraph of the chapter ends here."]


def test_a_rescript_keeps_the_recordings_of_unchanged_paragraphs():
    from types import SimpleNamespace

    from manabi_server.services.narration import keep_recorded

    old = [
        SimpleNamespace(
            spoken_text="Same paragraph.",
            audio=b"mp3",
            mime="audio/mpeg",
            duration_ms=900,
            voice="steven",
            word_times=[0, 300],
        ),
        SimpleNamespace(
            spoken_text="Old wrong order.",
            audio=b"x",
            mime="audio/mpeg",
            duration_ms=1,
            voice="steven",
            word_times=None,
        ),
        SimpleNamespace(
            spoken_text="Never recorded.",
            audio=None,
            mime=None,
            duration_ms=None,
            voice=None,
            word_times=None,
        ),
    ]
    rows = [{"spoken_text": "Same paragraph."}, {"spoken_text": "New right order."}]
    assert keep_recorded(old, rows) == 1
    assert rows[0]["audio"] == b"mp3" and rows[0]["duration_ms"] == 900
    assert rows[0]["word_times"] == [0, 300]  # the word timings travel with the audio
    assert "audio" not in rows[1]


def test_untimed_word_times_stay_sql_null():
    # a carried-over None saved as JSON null hid every paragraph from the backfill
    from manabi_core.models import NarrationSegment

    assert NarrationSegment.__table__.c.word_times.type.none_as_null is True


# ── Scanned book spreads (Kawanaka, "The Robredo Style", Nov 18, 2026) ──────


def test_an_asterisk_footnote_is_not_read_and_does_not_break_the_sentence():
    rows = [
        (1, "paragraph", "It is not so difficult to assume that urbanization transforms "
         "the political pattern as"),
        (1, "paragraph", '* Kawanaka, Takeshi. 1998. "The Robredo Style: Philippine Local '
         'Politics in Transition." Kasarinlan 13 (3): 5–36.'),
        (2, "paragraph", "it does the socioeconomic situation of both constituency and the "
         "political elite."),
    ]
    assert _texts(rows) == [
        "It is not so difficult to assume that urbanization transforms the political "
        "pattern as it does the socioeconomic situation of both constituency and the "
        "political elite."
    ]


def test_garbled_ocr_sentences_are_not_read():
    # Doc 85's narration as first scripted: lines from a curled page corner.
    rows = [
        (12, "paragraph", "Robredo i ften en i ah n t t he et . Past mayors were not as "
         "open to contact."),
        (14, "paragraph", "Iev t Ma Od's ues sn Po Nag C Marc 17, 1998."),
    ]
    assert _texts(rows) == ["Past mayors were not as open to contact."]


def test_clean_prose_with_short_words_and_abbreviations_is_kept():
    rows = [
        (3, "paragraph", "The first organizations were Lakas ng Kababaihan and the "
         "Barangay People's Organization, e.g. in Sabang, i.e. near the river."),
        (3, "paragraph", "Interview with Mr. Aton Nabua, Officer, Lingkod Barangay Office, "
         "Naga City, August 18, 1997."),
        (4, "paragraph", "The LDP and the PDP-Laban fielded candidates in the 1992 elections."),
    ]
    assert len(_texts(rows)) == 3
