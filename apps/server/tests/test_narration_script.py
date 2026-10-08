"""Layout-aware narration script on a synthetic journal-style PDF."""

import pymupdf
import pytest
from manabi_server.processing.narration_script import SKIPPED_KINDS, build_script

W, H = 595, 842  # A4 points
BODY = "helv"  # Helvetica
HEAD = "hebo"  # Helvetica-Bold

LOREM = (
    "Institutions are the rules of the game in a society (North, 1990), the humanly devised "
    "constraints that shape human interaction; organizations are the players. This distinction "
    "matters for growth and poverty reduction because rules do not enforce themselves and "
)
LOREM2 = (
    "because organizations carry the interests that keep rules alive. Where organizations are "
    "weak, formal rules are captured, ignored or quietly re-written by those with power."
)


def _footer(page, n):
    page.insert_text(
        (50, 815),
        "Copyright 2011 Publisher. J. Test. 1, 1-20 (2011) DOI: 10.1/x",
        fontsize=8,
        fontname=BODY,
    )
    page.insert_text(
        (50, 826),
        f"{n} J. Doe and J. Roe" if n % 2 == 0 else f"Testing Things {n}",
        fontsize=8,
        fontname=BODY,
    )


def _running_head(page, n):
    page.insert_text((50, 40), f"{n + 10} J. Doe and J. Roe", fontsize=10, fontname=BODY)


@pytest.fixture(scope="module")
def paper():
    doc = pymupdf.open()
    # ── page 1: masthead, title, authors, affiliation, abstract, keywords, body
    p = doc.new_page(width=W, height=H)
    p.insert_text(
        (50, 40),
        "Journal of Testing 1 (2011) Published online DOI: 10.1/x",
        fontsize=10,
        fontname=BODY,
    )
    p.insert_text((50, 120), "A STUDY OF RULES AND", fontsize=18, fontname=HEAD)
    p.insert_text((50, 145), "PLAYERS IN TESTVILLE", fontsize=18, fontname=HEAD)
    p.insert_text((50, 175), "JANE DOE 1 and JOHN ROE 2 *", fontsize=9, fontname=BODY)
    p.insert_text(
        (50, 190),
        "1 University of Testing, Testville, UK 2 Institute of Rules",
        fontsize=9,
        fontname=BODY,
    )
    p.insert_textbox(
        pymupdf.Rect(50, 215, 545, 300),
        "Abstract: We study whether rules or players matter more. Both do, in that order.",
        fontsize=9,
        fontname=BODY,
    )
    p.insert_text((50, 320), "Keywords: rules; players; testing", fontsize=9, fontname=BODY)
    p.insert_text((50, 360), "1 INTRODUCTION", fontsize=10, fontname=HEAD)
    p.insert_textbox(pymupdf.Rect(50, 380, 545, 470), LOREM, fontsize=10, fontname=BODY)
    # footnotes sit above the footer band, in small type, numbered
    p.insert_text(
        (50, 690),
        "1 A footnote that a narrator would skip, with a citation (Doe, 2004).",
        fontsize=8,
        fontname=BODY,
    )
    _footer(p, 1)
    # ── page 2: running head, continuation, run-in subheading, body
    p = doc.new_page(width=W, height=H)
    _running_head(p, 2)
    p.insert_textbox(pymupdf.Rect(50, 70, 545, 130), LOREM2, fontsize=10, fontname=BODY)
    y = 160
    for text, font in (
        ("2.1.1", HEAD),
        ("Formal and informal rules", HEAD),
        ("It is common to split rules into", BODY),
        ("written and unwritten kinds, e.g. laws vs. customs.", BODY),
    ):
        p.insert_text((50, y), text, fontsize=10, fontname=font)
        y += 12
    p.insert_textbox(
        pymupdf.Rect(50, 240, 545, 300),
        "Figure 1. Rules and players in a stylised game.",
        fontsize=10,
        fontname=BODY,
    )
    _footer(p, 2)
    # ── pages 3-4: filler body + running heads
    for n in (3, 4):
        p = doc.new_page(width=W, height=H)
        _running_head(p, n)
        p.insert_textbox(
            pymupdf.Rect(50, 70, 545, 200),
            f"Page {n} body text about rules and players. " * 4,
            fontsize=10,
            fontname=BODY,
        )
        _footer(p, n)
    # ── page 5: references heading + citation lines; page 6: more references
    p = doc.new_page(width=W, height=H)
    _running_head(p, 5)
    p.insert_textbox(
        pymupdf.Rect(50, 70, 545, 130),
        "Finally, players matter. This closes the argument.",
        fontsize=10,
        fontname=BODY,
    )
    p.insert_text((50, 160), "REFERENCES", fontsize=10, fontname=HEAD)
    y = 180
    for line in (
        "Doe J. 2004. Rules. Journal of Testing 1(2): 3-4.",
        "North DC. 1990. Institutions. Cambridge University Press: Cambridge.",
        "Roe J, Doe J. 2011. Players. J. Test. 1, 1-20.",
    ):
        p.insert_text((50, y), line, fontsize=9, fontname=BODY)
        y += 11
    _footer(p, 5)
    p = doc.new_page(width=W, height=H)
    _running_head(p, 6)
    p.insert_text(
        (50, 90),
        "Williamson O. 1996. The Mechanisms of Governance. Oxford University Press: Oxford.",
        fontsize=9,
        fontname=BODY,
    )
    _footer(p, 6)
    yield doc
    doc.close()


def test_title_authors_and_abstract(paper):
    script = build_script(paper)
    assert script.title == "A STUDY OF RULES AND PLAYERS IN TESTVILLE"
    assert script.authors == "Jane Doe and John Roe"
    kinds = [s.kind for s in script.segments]
    assert kinds[0] == "title" and kinds[1] == "abstract"
    assert script.segments[0].spoken_text == (
        "A Study of Rules and Players in Testville. By Jane Doe and John Roe."
    )
    assert script.segments[1].spoken_text.startswith("Abstract. We study whether rules or players")


def test_skips_headers_footers_footnotes_front_matter_and_references(paper):
    script = build_script(paper)
    spoken = " ".join(s.spoken_text for s in script.segments)
    for forbidden in (
        "Journal of Testing",
        "Copyright",
        "DOI",
        "J. Doe and J. Roe",
        "Testing Things",
        "footnote",
        "Keywords",
        "University of Testing",
        "Institute of Rules",
        "Doe J. 2004",
        "Cambridge University Press",
        "Williamson",
        "REFERENCES",
    ):
        assert forbidden not in spoken, forbidden
    counts = script.counts()
    # the heading, the block of citation lines on page 5, the page-6 line
    assert counts.get("reference", 0) >= 3
    assert counts.get("footnote", 0) == 1
    assert counts.get("header", 0) >= 5  # masthead + running heads
    assert counts.get("footer", 0) + counts.get("boilerplate", 0) >= 6


def test_runin_heading_is_split_and_announced(paper):
    script = build_script(paper)
    headings = [s for s in script.segments if s.kind == "heading"]
    assert [h.spoken_text for h in headings] == ["Introduction.", "Formal and informal rules."]
    after = script.segments[script.segments.index(headings[1]) + 1]
    assert after.kind == "paragraph"
    assert after.spoken_text.startswith(
        "It is common to split rules into written and unwritten kinds"
    )
    assert "for example, laws versus customs" in after.spoken_text


def test_paragraph_continues_across_the_page_break_and_citations_are_dropped(paper):
    script = build_script(paper)
    intro = next(s for s in script.segments if s.text.startswith("Institutions are the rules"))
    assert intro.page_no == 1
    assert "keep rules alive" in intro.text  # page-2 continuation folded in
    assert "(North, 1990)" in intro.text and "North" not in intro.spoken_text
    assert not any(s.text.startswith("because organizations") for s in script.segments)


def test_captions_are_read_and_nothing_skipped_leaks(paper):
    script = build_script(paper)
    caption = next(s for s in script.segments if s.kind == "caption")
    assert caption.spoken_text.startswith("Figure 1. Rules and players")
    kept_kinds = {s.kind for s in script.segments}
    assert not (kept_kinds & set(SKIPPED_KINDS))


def test_code_lines_and_notation_are_not_read_aloud():
    from manabi_server.processing.spoken import speakable

    # From an NLP deck whose narration failed on exactly these.
    assert not speakable("processed_text = re.sub(r'[^\x00-\x7f]', r\", raw_text).")
    assert not speakable("[x1…xn] [x1…xn] [x1…xn] [x1…xn] [x1…xn].")
    assert speakable("Basic tier : $100/month for up to 10,000 tweets")
    assert speakable("■bandwidth.")
    assert speakable("Most resistance is of the subdued, subtle, and surreptitious type.")


def test_a_short_heading_is_read_with_its_paragraph():
    from manabi_server.processing.narration_script import Script, Segment
    from manabi_server.services.narration import segment_rows

    segs = [
        Segment(0, 1, "heading", "Noise", "Noise."),
        Segment(
            1, 1, "paragraph", "Noise is any unwanted signal.", "Noise is any unwanted signal."
        ),
        Segment(2, 2, "heading", "Twisted Pair Wires", "Twisted Pair Wires."),
        Segment(3, 3, "paragraph", "On the next page.", "On the next page."),
        Segment(4, 3, "heading", "Long Haul Transmission Media", "Long Haul Transmission Media."),
        Segment(5, 3, "paragraph", "Body text here.", "Body text here."),
    ]
    rows = segment_rows(Script(segs, [], 10.0, "", None, None))
    assert rows[0]["spoken_text"] == "Noise. Noise is any unwanted signal."
    assert rows[0]["kind"] == "paragraph"
    # a heading whose paragraph is on another page, or a long heading, stays alone
    assert rows[1]["spoken_text"] == "Twisted Pair Wires."
    assert rows[3]["spoken_text"] == "Long Haul Transmission Media."
    assert [r["ord"] for r in rows] == list(range(len(rows)))
