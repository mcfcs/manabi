"""Increment 12.1 tests: reader cross-page merge, column-reorder gating,
per-document normalized path, chat_autovoice settings shape."""

import sys
from pathlib import Path

from manabi_server.processing import pipeline
from manabi_server.processing.text_html import merge_pages_html
from manabi_server.storage import files

# ── Reader cross-page paragraph merge ─────────────────────────────────────


def test_reader_joins_paragraph_split_across_pages():
    pages = [
        "<p>The villagers were united only when</p>",
        "<p>threatened by outsiders.</p>",
    ]
    html = merge_pages_html(pages)
    # the continuation ('threatened', lowercase, prev has no terminal punct) merges
    assert html == "<p>The villagers were united only when threatened by outsiders.</p>"


def test_reader_keeps_real_paragraph_break():
    pages = [
        "<p>He finished his point completely.</p>",
        "<p>A new idea began here.</p>",
    ]
    html = merge_pages_html(pages)
    assert html.count("<p>") == 2  # terminal punctuation + capital start → no merge


def test_reader_dehyphenates_across_pages():
    pages = ["<p>an inter-</p>", "<p>national movement</p>"]
    assert merge_pages_html(pages) == "<p>an international movement</p>"


def test_reader_non_paragraph_blocks_not_merged():
    pages = ["<p>see the data</p>", "<table><tr><td>x</td></tr></table>"]
    html = merge_pages_html(pages)
    assert "<table>" in html and html.count("<p>") == 1


# ── Column-reorder gating (native PDFs untouched) ─────────────────────────


def _two_col_ordered():
    # left column (x≈70) top→bottom, then right column (x≈360) — already correct
    els = []
    for t in (560, 440, 320):  # left col, descending t (top to bottom)
        els.append({"type": "paragraph", "text": f"L{t}", "page_no": 1,
                    "bbox": {"t": t, "l": 70, "r": 210, "b": t - 10}})
    for t in (560, 440, 320):  # right col
        els.append({"type": "paragraph", "text": f"R{t}", "page_no": 1,
                    "bbox": {"t": t, "l": 360, "r": 500, "b": t - 10}})
    return els


def test_native_two_column_untouched_without_aggressive():
    els = _two_col_ordered()
    before = [e["text"] for e in els]
    after = [e["text"] for e in pipeline._fix_reading_order(els, aggressive_columns=False)]
    assert after == before  # docling's correct order preserved


def test_spread_two_column_reordered_with_aggressive():
    # interleaved input (as scrambled OCR would give): L,R,L,R…
    els = []
    for t in (560, 440, 320):
        els.append({"type": "paragraph", "text": f"L{t}", "page_no": 1,
                    "bbox": {"t": t, "l": 70, "r": 210, "b": t - 10}})
        els.append({"type": "paragraph", "text": f"R{t}", "page_no": 1,
                    "bbox": {"t": t, "l": 360, "r": 500, "b": t - 10}})
    after = [e["text"] for e in pipeline._fix_reading_order(els, aggressive_columns=True)]
    # left column fully, then right column
    assert after == ["L560", "L440", "L320", "R560", "R440", "R320"]


# ── Per-document normalized path ──────────────────────────────────────────


def test_normalized_path_is_per_document():
    assert files.normalized_path(42) == "normalized/42.pdf"
    assert files.normalized_path(7) != files.normalized_path(8)


# ── chat_autovoice settings shape ─────────────────────────────────────────


def test_settings_patch_accepts_chat_autovoice():
    from manabi_server.api.settings import SettingsPatch

    p = SettingsPatch.model_validate({"chat_autovoice": True})
    assert p.chat_autovoice is True
    assert SettingsPatch().chat_autovoice is None  # absent = unchanged


# ── Rotation-safe split ───────────────────────────────────────────────────


def test_split_bakes_rotation_into_upright_halves():
    import pymupdf
    from manabi_server.processing import layout

    # A landscape page carrying rotation=90 (pages that display sideways).
    doc = pymupdf.open()
    for _ in range(4):
        page = doc.new_page(width=792, height=612)
        page.insert_textbox(pymupdf.Rect(40, 60, 340, 560), "Left. " * 60, fontsize=11)
        page.insert_textbox(pymupdf.Rect(452, 60, 752, 560), "Right. " * 60, fontsize=11)
        page.set_rotation(90)
    gutters = [p.rect.width / 2 for p in doc]
    out = layout.split_spread_pdf(doc, gutters)
    assert out.page_count == doc.page_count * 2
    # halves are un-rotated (upright) so downstream render/clip stays sane
    assert all(p.rotation == 0 for p in out)


def test_normalize_rotation_bakes_upright_same_page_count():
    import pymupdf
    from manabi_server.processing import layout

    doc = pymupdf.open()
    for _ in range(3):
        page = doc.new_page(width=612, height=792)
        page.insert_textbox(pymupdf.Rect(40, 60, 560, 740), "Body. " * 80, fontsize=11)
        page.set_rotation(90)
    baked = layout.normalize_rotation(doc)
    assert baked is not None
    assert baked.page_count == doc.page_count  # no split — 1:1 pages
    assert all(p.rotation == 0 for p in baked)  # upright coordinate space
    # native text survives the bake (parse still reads real characters)
    assert "Body." in baked[0].get_text()


def test_normalize_rotation_none_when_upright():
    import pymupdf
    from manabi_server.processing import layout

    doc = pymupdf.open()
    doc.new_page(width=612, height=792)  # rotation 0
    assert layout.normalize_rotation(doc) is None  # caller keeps the original


# ── Extracted-text spacing collapse ───────────────────────────────────────


def test_native_pdf_html_collapses_multiple_spaces():
    import pymupdf
    from manabi_server.processing.text_html import _pdf_page_html

    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    # tabs/padding as justified PDF text often extracts
    page.insert_text((72, 100), "The   villagers\twere    united")
    html = _pdf_page_html(page)
    assert html is not None
    assert "  " not in html  # no run of two-plus spaces survives
    assert "\t" not in html
    assert "villagers were united" in html


def test_collapse_hspace_preserves_newlines():
    from manabi_server.processing.text_html import collapse_hspace

    assert collapse_hspace("a   b\tc") == "a b c"
    assert collapse_hspace("line1  \n  line2") == "line1 \n line2"  # newline kept


# keep worker importable for any downstream collection
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "ai-worker" / "src"))
