"""Scanned book spreads — photos of an open book, two printed pages per PDF page,
no text layer — read like the real Nov 18, 2026 upload (Kawanaka, "The Robredo
Style", doc 85): rotated landscape scans, running heads naming the author
(verso) and the chapter title (recto), and the neighbouring chapters' pages at
both ends."""

from types import SimpleNamespace as NS

import pymupdf
import pytest
from manabi_core.models import DocumentKind
from manabi_server.config import get_settings
from manabi_server.processing import pipeline
from manabi_server.storage import files


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "file_storage_root", str(tmp_path / "storage"))
    return tmp_path / "storage"


def _text_spread() -> pymupdf.Document:
    doc = pymupdf.open()
    for _ in range(6):
        page = doc.new_page(width=792, height=612)
        page.insert_textbox(pymupdf.Rect(40, 60, 340, 560), "Left page. " * 80, fontsize=11)
        page.insert_textbox(pymupdf.Rect(452, 60, 752, 560), "Right page. " * 80, fontsize=11)
    return doc


def _as_scan(src: pymupdf.Document, rotate: int = 0) -> pymupdf.Document:
    """Image-only copy (no text layer), optionally stored sideways with /Rotate
    like the real upload (portrait image + Rotate 90 → displays landscape)."""
    out = pymupdf.open()
    for page in src:
        pix = page.get_pixmap(dpi=72)
        if rotate:
            new = out.new_page(width=page.rect.height, height=page.rect.width)
            new.insert_image(new.rect, pixmap=pix, rotate=-rotate)
            new.set_rotation(rotate)
        else:
            new = out.new_page(width=page.rect.width, height=page.rect.height)
            new.insert_image(new.rect, pixmap=pix)
    return out


def _doc(storage, pdf: pymupdf.Document, layout: str = "auto"):
    rel = "originals/test.pdf"
    path = files.resolve(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.save(str(path))
    return NS(
        id=7, kind=DocumentKind.pdf, storage_path=rel, page_layout=layout, detected_layout=None
    )


def _normalized_pages(doc) -> int:
    with pymupdf.open(files.resolve(files.normalized_path(doc.id))) as d:
        return d.page_count


# ── 1. auto-split ─────────────────────────────────────────────────────────


def test_a_scanned_spread_is_split_into_book_pages_without_opting_in(storage):
    doc = _doc(storage, _as_scan(_text_spread(), rotate=90))
    assert pipeline._ensure_normalized_pdf(doc) == "spread"
    # "split" = detected AND cut; older auto docs keep "spread" (detected only)
    assert doc.detected_layout == "split" and doc.page_layout == "auto"
    assert _normalized_pages(doc) == 12  # 6 photos → 12 book pages


def test_opting_in_still_records_spread(storage):
    doc = _doc(storage, _as_scan(_text_spread()), layout="spread")
    assert pipeline._ensure_normalized_pdf(doc) == "spread"
    assert doc.detected_layout == "spread"


def test_a_digital_spread_with_a_text_layer_is_left_whole(storage):
    doc = _doc(storage, _text_spread())
    assert pipeline._ensure_normalized_pdf(doc) == "orig"
    assert doc.detected_layout == "single"


def test_a_portrait_scan_is_not_split(storage):
    src = pymupdf.open()
    for _ in range(4):
        page = src.new_page(width=612, height=792)
        page.insert_textbox(pymupdf.Rect(72, 72, 540, 720), "Body text. " * 120, fontsize=11)
    doc = _doc(storage, _as_scan(src))
    assert pipeline._ensure_normalized_pdf(doc) == "orig"
    assert doc.detected_layout == "single"


def test_choosing_single_still_wins_over_detection(storage):
    doc = _doc(storage, _as_scan(_text_spread()), layout="single")
    assert pipeline._ensure_normalized_pdf(doc) == "orig"
