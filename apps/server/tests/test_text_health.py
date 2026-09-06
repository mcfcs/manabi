"""Text-layer healing: ligatures, glued-word detection, bbox re-read."""

from manabi_server.processing.text_health import (
    glue_ratio,
    glued_tokens,
    heal_elements,
    is_glued_token,
    join_hyphenated,
    join_lines,
    normalize_ligatures,
    page_needs_healing,
)

GLUED = (
    "Itisnowwidelyacceptedthat ‘institutionsmatter’ forgrowthandpovertyreduction,aswell "
    "as for political stability and social inclusion."
)
CLEAN = (
    "It is now widely accepted that ‘institutions matter’ for growth and poverty "
    "reduction, as well as for political stability and social inclusion."
)


def test_ligatures_fold_to_letters():
    assert (
        normalize_ligatures("speciﬁcally efﬁcacy conﬂict oﬀ ﬃ")
        == "specifically efficacy conflict off ffi"
    )
    assert normalize_ligatures("plain") == "plain"


def test_glued_token_detection():
    assert is_glued_token("Itisnowwidelyacceptedthat")
    assert is_glued_token("reduction,aswell")  # letters on both sides of a comma
    assert not is_glued_token("poverty-reduction")  # hyphenated compound
    # length alone flags a genuine long word; acceptable because the PAGE
    # threshold needs several such tokens and 19+ letter words are rare in prose
    assert is_glued_token("antidisestablishmentarianism")
    assert not is_glued_token("characteristics")  # 15 letters: fine
    assert not is_glued_token("http://www.ippg.org.uk/publications.html")
    assert not is_glued_token("kunal.sen@manchester.ac.uk")
    assert not is_glued_token("(2011)")


def test_glue_ratio_separates_glued_from_clean_text():
    assert glue_ratio(CLEAN) == 0.0
    assert glue_ratio(GLUED) >= 0.2
    assert glued_tokens(GLUED) == [
        "Itisnowwidelyacceptedthat",
        "forgrowthandpovertyreduction,aswell",
    ]


def test_page_threshold():
    assert page_needs_healing([GLUED])
    assert not page_needs_healing([CLEAN, CLEAN, CLEAN])
    # one stray long token on an otherwise clean page does not trigger healing
    assert not page_needs_healing([" ".join([CLEAN, "Donaudampfschifffahrt", *([CLEAN] * 5)])])


class _FakePage:
    def __init__(self, blocks):
        self._blocks = blocks

    def get_text(self, _kind):
        return {"blocks": self._blocks}


def _line(*texts, width=350):
    return {
        "bbox": [50, 0, 50 + width, 10],
        "spans": [{"text": t, "size": 10, "flags": 0, "font": "AdvP41153C"} for t in texts],
    }


def test_native_page_html_keeps_space_spans_and_folds_ligatures():
    from manabi_server.processing.text_html import _pdf_page_html

    page = _FakePage(
        [
            {
                "type": 0,
                "lines": [
                    # per-word spans on a full-width (wrapped) line
                    _line("It", " ", "is", " ", "now", " ", "widely"),
                    _line("speciﬁcally ", "so", width=120),  # short: paragraph end
                    _line(" ", "leading", width=90),  # a space span at line start is dropped
                ],
            }
        ]
    )
    html = _pdf_page_html(page)
    assert "It is now widely specifically so" in html  # wrapped line flows on
    assert "<br>leading" in html and "<br> leading" not in html  # short line keeps its break


def test_native_page_html_flows_wrapped_prose_and_dehyphenates():
    from manabi_server.processing.text_html import _pdf_page_html

    page = _FakePage(
        [
            {
                "type": 0,
                "lines": [
                    _line("effective social, political and economic organ-"),
                    _line("izations, across sectors, which can push for a self-"),
                    _line("generating rule. The end of the paragraph."),
                ],
            },
            {
                "type": 0,
                "lines": [  # a list: short lines keep their breaks
                    _line("1. Rules", width=60),
                    _line("2. Players", width=70),
                    _line("3. Outcomes", width=80),
                ],
            },
        ]
    )
    html = _pdf_page_html(page)
    assert "economic organizations, across sectors" in html  # soft hyphen dropped
    assert "a self-generating rule" in html  # real compound kept
    assert "1. Rules<br>2. Players<br>3. Outcomes" in html


def test_join_lines_dehyphenates_soft_breaks_and_keeps_real_hyphens():
    assert join_lines("effective social, political and economic organ-\nizations, which") == (
        "effective social, political and economic organizations, which"
    )
    assert join_hyphenated("the self-", "generating rule") == "the self-generating rule"
    assert (
        join_hyphenated("so-called ‘parch-", "ment institutions’")
        == "so-called ‘parchment institutions’"
    )
    assert join_hyphenated("in the Asia-", "Pacific region") == "in the Asia-Pacific region"
    assert join_lines("one\n\ntwo  three\n") == "one two three"


def test_heal_replaces_only_glued_pages_and_respects_sanity_bounds():
    elements = [
        {
            "type": "paragraph",
            "text": GLUED,
            "page_no": 1,
            "bbox": {"l": 0, "t": 10, "r": 10, "b": 0},
        },
        {
            "type": "paragraph",
            "text": "Thisonetoo,gluedbadly here.",
            "page_no": 1,
            "bbox": {"l": 0, "t": 20, "r": 10, "b": 11},
        },
        {
            "type": "table",
            "text": "a | b",
            "page_no": 1,
            "bbox": {"l": 0, "t": 30, "r": 10, "b": 21},
        },
        {
            "type": "paragraph",
            "text": CLEAN,
            "page_no": 2,
            "bbox": {"l": 0, "t": 10, "r": 10, "b": 0},
        },
        {"type": "paragraph", "text": "speciﬁc", "page_no": 3, "bbox": None},
    ]
    calls: list[tuple[int, dict]] = []

    def fake_clip(page_no, bbox):
        calls.append((page_no, bbox))
        if bbox["t"] == 10:
            return (
                "It is now widely accepted that ‘institutions matter’ for growth and\n"
                "poverty reduction, as well as for political stability and social inclusion."
            )
        return "x"  # far too short → rejected by the letter-ratio check

    healed = heal_elements(elements, fake_clip)
    assert healed[0]["text"] == CLEAN and healed[0].get("healed") is True
    assert healed[1]["text"] == "Thisonetoo,gluedbadly here."  # sanity check refused "x"
    assert healed[2]["text"] == "a | b"  # tables untouched
    assert healed[3]["text"] == CLEAN and "healed" not in healed[3]  # clean page never re-read
    assert healed[4]["text"] == "specific"  # ligatures folded even without a bbox
    assert {p for p, _ in calls} == {1}


def test_heal_without_clip_only_folds_ligatures():
    elements = [{"type": "paragraph", "text": GLUED + " ﬁne", "page_no": 1, "bbox": None}]
    out = heal_elements(elements, None)
    assert out[0]["text"].endswith(" fine") and out[0]["text"].startswith("Itisnow")
