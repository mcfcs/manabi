"""Per-page extracted rich text (<b>/<i>/<p>/<br> only).

Native text layer (PyMuPDF spans / python-pptx runs) when it exists —
preserving bold/italic. For scanned pages with no text layer, falls back to
the stored Docling-OCR elements, so scanned PDFs finally become selectable
and searchable. Everything is HTML-escaped before tagging.
"""

import html
import re

from manabi_core.models import DocElement, Document, DocumentKind, DocumentPage
from sqlalchemy import select
from sqlalchemy.orm import Session

from manabi_server.storage import files

BOLD_FLAG = 1 << 4  # PyMuPDF span flag bit for bold
ITALIC_FLAG = 1 << 1


# Postgres text columns reject NUL; some PDF fonts leak NUL/control chars
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def sanitize(text: str) -> str:
    return _CONTROL_CHARS.sub("", text)


def _span_html(text: str, bold: bool, italic: bool) -> str:
    out = html.escape(sanitize(text))
    if bold:
        out = f"<b>{out}</b>"
    if italic:
        out = f"<i>{out}</i>"
    return out


INDENT_STEP_PTS = 18  # one indent level ≈ 18pt of left offset
MAX_INDENT = 4


def _pdf_page_html(page) -> str | None:
    """Styled HTML from the native text layer; None when the page is scanned.
    Preserves bold/italic and approximates indentation from span x-origins."""
    data = page.get_text("dict")
    text_blocks = [b for b in data.get("blocks", []) if b.get("type") == 0]

    # Base left margin for indent bucketing
    x_origins = [
        line["bbox"][0]
        for block in text_blocks
        for line in block.get("lines", [])
        if line.get("spans")
    ]
    base_x = min(x_origins) if x_origins else 0.0

    parts: list[str] = []
    for block in text_blocks:
        lines: list[str] = []
        block_x = None
        for line in block.get("lines", []):
            spans = []
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text.strip():
                    continue
                flags = span.get("flags", 0)
                font = span.get("font", "")
                bold = bool(flags & BOLD_FLAG) or "bold" in font.lower()
                italic = bool(flags & ITALIC_FLAG) or "italic" in font.lower()
                spans.append(_span_html(text, bold, italic))
            if spans:
                if block_x is None:
                    block_x = line["bbox"][0]
                lines.append("".join(spans))
        if lines:
            indent = 0
            if block_x is not None:
                indent = min(MAX_INDENT, int((block_x - base_x) / INDENT_STEP_PTS))
            style = f' style="margin-left:{indent}em"' if indent > 0 else ""
            parts.append(f"<p{style}>{'<br>'.join(lines)}</p>")
    joined = "".join(parts)
    return joined if joined.strip() else None


def _figure_markers(elements: list[DocElement]) -> str:
    """Placeholder lines so readers know visuals exist on the page."""
    markers = []
    for el in elements:
        if el.element_type == "figure":
            markers.append("<p><i>[Figure — see rendered page]</i></p>")
        elif el.element_type == "table" and not (el.text_content or "").strip():
            markers.append("<p><i>[Table — see rendered page]</i></p>")
    return "".join(markers)


def _elements_page_html(elements: list[DocElement]) -> str | None:
    """OCR fallback: build from stored extraction (headings bold)."""
    parts: list[str] = []
    for el in elements:
        text = sanitize(el.text_content or "").strip()
        if not text:
            continue
        escaped = html.escape(text).replace("\n", "<br>")
        if el.element_type == "heading":
            parts.append(f"<p><b>{escaped}</b></p>")
        else:
            parts.append(f"<p>{escaped}</p>")
    joined = "".join(parts)
    return joined if joined.strip() else None


def _pptx_pages_html(source_path) -> dict[int, str]:
    from pptx import Presentation

    out: dict[int, str] = {}
    prs = Presentation(str(source_path))
    for idx, slide in enumerate(prs.slides, start=1):
        parts: list[str] = []
        for shape in slide.shapes:
            if not getattr(shape, "has_text_frame", False):
                continue
            for para in shape.text_frame.paragraphs:
                spans = [
                    _span_html(run.text, bool(run.font.bold), bool(run.font.italic))
                    for run in para.runs
                    if run.text.strip()
                ]
                if spans:
                    parts.append(f"<p>{''.join(spans)}</p>")
        if parts:
            out[idx] = "".join(parts)
    return out


def build_text_html(db: Session, document_id: int) -> int:
    """Populate document_pages.text_html for one document. Idempotent."""
    doc = db.get(Document, document_id)
    if doc is None:
        return 0
    pages = (
        db.execute(
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .order_by(DocumentPage.page_no)
        )
        .scalars()
        .all()
    )
    elements_by_page: dict[int, list[DocElement]] = {}
    for el in (
        db.execute(
            select(DocElement)
            .where(DocElement.document_id == document_id)
            .order_by(DocElement.order_index)
        )
        .scalars()
        .all()
    ):
        elements_by_page.setdefault(el.page_id, []).append(el)

    updated = 0
    if doc.kind == DocumentKind.pptx:
        by_no = _pptx_pages_html(files.resolve(doc.storage_path))
        for page in pages:
            html_text = by_no.get(page.page_no) or _elements_page_html(
                elements_by_page.get(page.id, [])
            )
            if html_text:
                page.text_html = html_text
                updated += 1
    else:
        import fitz

        with fitz.open(files.resolve(doc.storage_path)) as pdf:
            for page in pages:
                page_elements = elements_by_page.get(page.id, [])
                native = None
                if 1 <= page.page_no <= pdf.page_count:
                    native = _pdf_page_html(pdf[page.page_no - 1])
                html_text = native or _elements_page_html(page_elements)
                if html_text:
                    page.text_html = html_text + _figure_markers(page_elements)
                    updated += 1
    db.commit()
    return updated
