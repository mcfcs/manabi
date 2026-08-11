"""Two-page-spread detection and splitting for scanned PDFs.

Some scanned books are digitized as landscape pages where each PDF page holds
two facing book pages side by side. Docling then reads the two halves
interleaved — scrambled text, dropped lines, and content landing on the wrong
logical page. We detect that layout and, before parsing, split each spread
page down the middle into two portrait pages. Every downstream stage keeps its
1:1 page_no↔page assumption because the file it reads *is* the split file.

Detection is content-aware: a two-page spread has a bright vertical gutter in
the middle with text massed on either side, so the central column carries far
less ink than the page's typical text column. Pure aspect ratio is unreliable
(scanned books sit inside wide margins), so we measure the ink valley directly
and take a document-level majority vote.
"""

from __future__ import annotations

import logging

log = logging.getLogger("manabi.layout")

# Detection tuning — validated on real scans.
_RENDER_SCALE = 0.25         # low-res is plenty for a projection profile
_INK_THRESHOLD = 160         # grayscale < this counts as ink
# The book fold sits near the page centre — search a tight band around it so a
# near-blank facing page or a drop-cap gap can't masquerade as the gutter.
_FOLD_BAND = (0.45, 0.60)    # fraction of page width to search for the gutter
_GUTTER_LOW_FRAC = 0.10      # a column is "gutter" if ink < 10% of the peak column
_GUTTER_MIN_PT = 12          # the low-ink run must be this wide (points) to count
_SPREAD_DOC_VOTE = 0.50      # ≥ half the pages show a gutter → split the doc

# Native-text gate: only scanned PDFs are spread candidates.
_NATIVE_SAMPLE_PAGES = 8
_NATIVE_MIN_CHARS_PER_PAGE = 40


def _page_gutter(page) -> float | None:
    """If this landscape page reads as a two-page spread, return the x (in PDF
    points) of the fold between the two book pages: the WIDEST run of near-blank
    columns in a tight band around the page centre. Cutting at the fold (not a
    stray valley elsewhere) is what keeps each book page's text on one side."""
    import numpy as np
    import pymupdf

    if page.rect.width <= page.rect.height:
        return None  # portrait pages are never two-up spreads
    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(_RENDER_SCALE, _RENDER_SCALE), colorspace=pymupdf.csGRAY
    )
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    col = (arr < _INK_THRESHOLD).sum(axis=0).astype(np.float64)
    w = pix.width
    if col.max() < 1:
        return None
    thr = col.max() * _GUTTER_LOW_FRAC
    c0, c1 = int(w * _FOLD_BAND[0]), int(w * _FOLD_BAND[1])
    min_run = _GUTTER_MIN_PT * _RENDER_SCALE  # points → pixels
    best_w, best_mid, start = 0.0, None, None
    for x in range(c0, c1 + 1):
        low = x < c1 and col[x] < thr
        if low and start is None:
            start = x
        elif not low and start is not None:
            if x - start > best_w:
                best_w, best_mid = x - start, (start + x) / 2
            start = None
    if best_mid is None or best_w < min_run:
        return None  # central band is full of text → not a spread
    return best_mid / _RENDER_SCALE


def detect_spread(fitz_doc) -> tuple[bool, list[float | None]]:
    """Return (doc_is_spread, per_page_gutter_x). A document is a spread when a
    majority of its pages show a clean central gutter valley."""
    gutters = [_page_gutter(pg) for pg in fitz_doc]
    votes = sum(1 for g in gutters if g is not None)
    doc_is_spread = bool(gutters) and (votes / len(gutters)) >= _SPREAD_DOC_VOTE
    return doc_is_spread, gutters


def normalize_rotation(fitz_doc):
    """Return a NEW upright PDF with every page's /Rotate baked in — each source
    page drawn upright via show_pdf_page (preserves the native text layer AND
    image content; page_count unchanged). Returns None when no page is rotated
    (caller keeps the original). Reused by the split and no-split normalization
    paths so parse/render/bbox share one upright coordinate space — clipping or
    OCRing a rotated source otherwise yields sideways/mis-mapped output."""
    import pymupdf

    if not any(page.rotation for page in fitz_doc):
        return None
    baked = pymupdf.open()
    for i, page in enumerate(fitz_doc):
        r = page.rect  # visible rect: rotation already applied
        np = baked.new_page(width=r.width, height=r.height)
        np.show_pdf_page(np.rect, fitz_doc, i)  # draws the page upright
    return baked


def split_spread_pdf(fitz_doc, gutters: list[float | None]):
    """Build a new PDF where each spread page becomes two portrait halves
    (left then right), cut at its detected gutter. When the doc is a spread but
    a given page lacks a clean gutter (e.g. a near-blank facing page), fall back
    to the geometric centre so page numbering stays a predictable 2× the source.
    Works on scanned/image PDFs because show_pdf_page re-renders the region."""
    import pymupdf

    for_split = any(g is not None for g in gutters)
    # Bake any page rotation into an upright intermediate first — clipping a
    # rotated source maps the clip in the wrong coordinate space.
    baked = normalize_rotation(fitz_doc)
    src = baked if baked is not None else fitz_doc

    out = pymupdf.open()
    for i, page in enumerate(src):
        g = gutters[i] if i < len(gutters) else None
        if not for_split:
            out.insert_pdf(src, from_page=i, to_page=i)
            continue
        r = page.rect
        cut = g if g is not None else (r.x0 + r.x1) / 2
        for half in (
            pymupdf.Rect(r.x0, r.y0, cut, r.y1),
            pymupdf.Rect(cut, r.y0, r.x1, r.y1),
        ):
            p = out.new_page(width=half.width, height=half.height)
            p.show_pdf_page(p.rect, src, i, clip=half)
    # NB: don't close `baked` here — show_pdf_page keeps a reference to it until
    # the caller saves `out`. It's freed when this function's frame is GC'd.
    return out


def has_native_text(fitz_doc) -> bool:
    """True if the PDF carries a real text layer (not a pure scan). Only
    text-less scans are spread candidates under 'auto'."""
    n = min(_NATIVE_SAMPLE_PAGES, fitz_doc.page_count)
    if n == 0:
        return False
    total = sum(len(fitz_doc[i].get_text("text").strip()) for i in range(n))
    return total >= _NATIVE_MIN_CHARS_PER_PAGE * n
