"""Document processing pipeline — runs SYNC inside the CPU worker's task
thread. Stages checkpoint via documents.extract_stage so a crashed job
resumes at the failed stage instead of redoing everything. Each stage is
wipe-and-redo idempotent for its own artifacts. The original upload is never
touched.

Stages: structure (Docling parse + speaker notes + persist pages/elements)
      → render (PNGs per page; LibreOffice for PPTX, non-fatal on failure)
      → chunk  (structure-aware chunks + FTS via generated tsv column)
"""

import logging
import subprocess
import tempfile
from pathlib import Path

from manabi_core.models import (
    Chunk,
    DocElement,
    Document,
    DocumentKind,
    DocumentPage,
    ExtractStatus,
    Job,
    JobStatus,
    Module,
)
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from manabi_server.config import get_settings
from manabi_server.processing import chunking
from manabi_server.storage import files

log = logging.getLogger("manabi.pipeline")

STAGES = ["structure", "render", "chunk", "embed"]


def _progress(db: Session, job: Job | None, pct: int, note: str) -> None:
    if job is not None:
        job.progress_pct = pct
        job.progress_note = note
        db.commit()


def run_pipeline(db: Session, document_id: int, job_id: int | None) -> None:
    doc = db.get(Document, document_id)
    job = db.get(Job, job_id) if job_id else None
    if doc is None or doc.deleted_at is not None:
        if job is not None:
            job.status = JobStatus.cancelled
            job.progress_note = "document deleted"
            db.commit()
        return

    doc.extract_status = ExtractStatus.processing
    doc.error = None
    if job is not None:
        from datetime import UTC, datetime

        job.status = JobStatus.running
        job.started_at = datetime.now(UTC)
    db.commit()

    done = STAGES.index(doc.extract_stage) + 1 if doc.extract_stage in STAGES else 0
    try:
        if done < 1:
            _progress(db, job, 10, "Parsing document")
            _stage_structure(db, doc)
            doc.extract_stage = "structure"
            db.commit()
        if done < 2:
            _progress(db, job, 45, "Rendering pages")
            _stage_render(db, doc, job)
            from manabi_server.processing.text_html import build_text_html

            build_text_html(db, doc.id)
            doc.extract_stage = "render"
            db.commit()
        if done < 3:
            _progress(db, job, 80, "Creating chunks")
            _stage_chunk(db, doc)
            doc.extract_stage = "chunk"
            db.commit()
        if done < 4:
            _progress(db, job, 92, "Indexing for retrieval")
            from manabi_server.processing.embedding import embed_missing_chunks_sync

            embed_missing_chunks_sync(db)
            doc.extract_stage = "embed"
            db.commit()

        doc.extract_status = ExtractStatus.ready
        module = db.get(Module, doc.module_id)
        if module is not None:
            module.content_version += 1
        if job is not None:
            job.status = JobStatus.succeeded
            job.progress_pct = 100
            job.progress_note = "Ready"
        db.commit()
    except Exception as exc:
        db.rollback()
        log.exception("pipeline failed for document %s", document_id)
        doc.extract_status = ExtractStatus.failed
        doc.error = f"{type(exc).__name__}: {str(exc)[:500]}"
        if job is not None:
            job.status = JobStatus.failed
            job.error = doc.error
        db.commit()
        raise


# ── Stage 1: structure ────────────────────────────────────────────────────


def _stage_structure(db: Session, doc: Document) -> None:
    # wipe-and-redo (also removes dependent chunks via cascade-by-hand)
    db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    db.execute(delete(DocElement).where(DocElement.document_id == doc.id))
    db.execute(delete(DocumentPage).where(DocumentPage.document_id == doc.id))
    db.commit()

    source = files.resolve(doc.storage_path)
    parsed = _docling_parse(source)
    parsed["elements"] = _fix_reading_order(parsed["elements"])

    notes_by_page: dict[int, str] = {}
    titles_by_page: dict[int, str] = {}
    if doc.kind == DocumentKind.pptx:
        notes_by_page, titles_by_page = _pptx_notes_and_titles(source)

    page_count = max(
        [p for p in parsed["pages"]] + list(notes_by_page) + list(titles_by_page),
        default=1,
    )
    pages: dict[int, DocumentPage] = {}
    for page_no in range(1, page_count + 1):
        page = DocumentPage(
            document_id=doc.id,
            page_no=page_no,
            title=titles_by_page.get(page_no) or parsed["titles"].get(page_no),
            speaker_notes=notes_by_page.get(page_no),
        )
        db.add(page)
        pages[page_no] = page
    db.flush()

    for order_index, item in enumerate(parsed["elements"]):
        db.add(
            DocElement(
                document_id=doc.id,
                page_id=pages[item["page_no"]].id if item["page_no"] in pages else None,
                order_index=order_index,
                element_type=item["type"],
                text_content=item["text"] or None,
                table_json=item.get("table"),
                bbox=item.get("bbox"),
            )
        )
    doc.page_count = page_count
    db.commit()


INVERSION_TOLERANCE_PTS = 5
# Scrambled OCR pages measure ~20%+; genuine multi-column pages have one
# inversion per column break (a few % with realistic element counts).
INVERSION_RATE_THRESHOLD = 0.15


def _fix_reading_order(elements: list[dict]) -> list[dict]:
    """Docling occasionally scrambles OCR-page element order. Detect pages
    whose element sequence inverts vertically too often and re-sort those
    pages by physical position (top-to-bottom, left-to-right). Correctly
    ordered pages — including multi-column native parses — are untouched."""
    by_page: dict[int, list[dict]] = {}
    for el in elements:
        by_page.setdefault(el["page_no"], []).append(el)

    fixed: list[dict] = []
    for page_no in sorted(by_page):
        items = by_page[page_no]
        boxed = [el for el in items if el.get("bbox")]
        if len(boxed) >= 4:
            inversions = 0
            pairs = 0
            for prev, nxt in zip(boxed, boxed[1:], strict=False):
                pairs += 1
                # bottom-left origin: larger t = higher on the page
                if nxt["bbox"]["t"] > prev["bbox"]["t"] + INVERSION_TOLERANCE_PTS:
                    inversions += 1
            if pairs and inversions / pairs > INVERSION_RATE_THRESHOLD:
                items = sorted(
                    items,
                    key=lambda el: (
                        -(el["bbox"]["t"] if el.get("bbox") else 0),
                        el["bbox"]["l"] if el.get("bbox") else 0,
                    ),
                )
                log.info(
                    "re-sorted scrambled page %s (%d/%d inversions)",
                    page_no, inversions, pairs,
                )
        fixed.extend(items)
    return fixed


_converter = None


def _get_converter():
    """Docling converter singleton — model initialization is expensive (tens of
    seconds); pay it once per worker process, not once per document."""
    global _converter
    if _converter is None:
        from docling.document_converter import DocumentConverter

        _converter = DocumentConverter()
    return _converter


def _docling_parse(source: Path) -> dict:
    result = _get_converter().convert(str(source))
    dl_doc = result.document

    elements: list[dict] = []
    titles: dict[int, str] = {}
    pages_seen: set[int] = set()

    for item, _level in dl_doc.iterate_items():
        label = str(getattr(item, "label", "") or "").lower()
        page_no = 1
        bbox = None
        prov = getattr(item, "prov", None)
        if prov:
            page_no = getattr(prov[0], "page_no", 1) or 1
            bb = getattr(prov[0], "bbox", None)
            if bb is not None:
                bbox = {"l": bb.l, "t": bb.t, "r": bb.r, "b": bb.b}
        pages_seen.add(page_no)

        from manabi_server.processing.text_html import sanitize

        text = sanitize(getattr(item, "text", "") or "").strip()
        table = None
        if "table" in label:
            element_type = "table"
            try:
                table = item.export_to_dataframe(dl_doc).to_dict(orient="split")
                text = text or _linearize_table(table)
            except Exception:  # noqa: BLE001 — table extraction is best-effort
                pass
        elif "picture" in label or "figure" in label:
            element_type = "figure"
        elif "section_header" in label or "title" in label or "heading" in label:
            # Demote pseudo-headings (lead-in lines Docling misclassifies,
            # e.g. "can be defined like this:") back to paragraphs.
            if text.endswith(":") or (text and text[0].islower()):
                element_type = "paragraph"
            else:
                element_type = "heading"
                if page_no not in titles and text:
                    titles[page_no] = text[:512]
        elif "list" in label:
            element_type = "list"
        elif "caption" in label:
            element_type = "caption"
        elif "formula" in label:
            element_type = "formula"
        else:
            element_type = "paragraph"

        if not text and element_type not in ("figure",):
            continue
        elements.append(
            {"type": element_type, "text": text, "page_no": page_no, "bbox": bbox, "table": table}
        )

    return {"elements": elements, "titles": titles, "pages": pages_seen}


def _linearize_table(table: dict) -> str:
    try:
        header = " | ".join(str(c) for c in table.get("columns", []))
        rows = "\n".join(" | ".join(str(v) for v in row) for row in table.get("data", []))
        return f"{header}\n{rows}".strip()
    except Exception:  # noqa: BLE001
        return ""


def _pptx_notes_and_titles(source: Path) -> tuple[dict[int, str], dict[int, str]]:
    from pptx import Presentation

    from manabi_server.processing.text_html import sanitize

    notes: dict[int, str] = {}
    titles: dict[int, str] = {}
    prs = Presentation(str(source))
    for idx, slide in enumerate(prs.slides, start=1):
        try:
            if slide.shapes.title is not None and slide.shapes.title.text.strip():
                titles[idx] = sanitize(slide.shapes.title.text).strip()[:512]
        except Exception:  # noqa: BLE001
            pass
        if slide.has_notes_slide:
            text = sanitize(slide.notes_slide.notes_text_frame.text).strip()
            if text:
                notes[idx] = text
    return notes, titles


# ── Stage 2: render ───────────────────────────────────────────────────────


def _stage_render(db: Session, doc: Document, job: Job | None) -> None:
    source = files.resolve(doc.storage_path)
    pdf_path = source

    if doc.kind == DocumentKind.pptx:
        converted = _pptx_to_pdf(source)
        if converted is None:
            log.warning("LibreOffice conversion failed for doc %s — text-only viewer", doc.id)
            return  # non-fatal: pages keep render_path NULL
        pdf_path = converted

    import fitz  # PyMuPDF

    pages = (
        db.execute(
            select(DocumentPage)
            .where(DocumentPage.document_id == doc.id)
            .order_by(DocumentPage.page_no)
        )
        .scalars()
        .all()
    )
    by_no = {p.page_no: p for p in pages}

    with fitz.open(pdf_path) as pdf:
        total = pdf.page_count
        for i, pdf_page in enumerate(pdf):
            page_no = i + 1
            row = by_no.get(page_no)
            if row is None:
                row = DocumentPage(document_id=doc.id, page_no=page_no)
                db.add(row)
                db.flush()
                by_no[page_no] = row
            pix = pdf_page.get_pixmap(matrix=fitz.Matrix(2, 2))
            rel = files.render_path(doc.id, page_no)
            files.write_atomic(rel, pix.tobytes("png"))
            thumb = pdf_page.get_pixmap(matrix=fitz.Matrix(0.35, 0.35))
            rel_thumb = files.thumb_path(doc.id, page_no)
            files.write_atomic(rel_thumb, thumb.tobytes("png"))
            row.render_path = rel
            row.thumb_path = rel_thumb
            row.width = pix.width
            row.height = pix.height
            if page_no % 5 == 0 or page_no == total:
                pct = 45 + int(40 * page_no / total)
                _progress(db, job, pct, f"Rendering pages {page_no}/{total}")
        doc.page_count = max(doc.page_count or 0, total)
    if pdf_path != source:
        pdf_path.unlink(missing_ok=True)
    db.commit()


def _pptx_to_pdf(source: Path) -> Path | None:
    settings = get_settings()
    outdir = Path(tempfile.mkdtemp(prefix="manabi_soffice_"))
    try:
        subprocess.run(
            [
                settings.soffice_path,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(outdir),
                str(source),
            ],
            check=True,
            capture_output=True,
            timeout=300,
        )
        produced = list(outdir.glob("*.pdf"))
        return produced[0] if produced else None
    except Exception:  # noqa: BLE001 — render fallback handles it
        log.exception("soffice conversion failed")
        return None


# ── Stage 3: chunk ────────────────────────────────────────────────────────


def _stage_chunk(db: Session, doc: Document) -> None:
    db.execute(delete(Chunk).where(Chunk.document_id == doc.id))

    page_rows = (
        db.execute(select(DocumentPage).where(DocumentPage.document_id == doc.id))
        .scalars()
        .all()
    )
    element_rows = (
        db.execute(
            select(DocElement)
            .where(DocElement.document_id == doc.id)
            .order_by(DocElement.order_index)
        )
        .scalars()
        .all()
    )
    page_no_by_id = {p.id: p.page_no for p in page_rows}
    elements = [
        chunking.ElementIn(
            id=e.id,
            page_no=page_no_by_id.get(e.page_id, 1),
            element_type=e.element_type,
            text=e.text_content or "",
        )
        for e in element_rows
    ]

    if doc.kind == DocumentKind.pptx:
        pages = [
            chunking.PageIn(page_no=p.page_no, title=p.title, speaker_notes=p.speaker_notes)
            for p in page_rows
        ]
        results = chunking.chunk_pptx(pages, elements)
    else:
        results = chunking.chunk_pdf(elements)

    for c in results:
        db.add(
            Chunk(
                module_id=doc.module_id,
                document_id=doc.id,
                page_start=c.page_start,
                page_end=c.page_end,
                element_ids=c.element_ids,
                heading_path=c.heading_path,
                text=c.text,
                token_count=c.token_count,
                content_hash=c.content_hash,
            )
        )
    db.commit()
