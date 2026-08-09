import hashlib
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from manabi_core.models import (
    Document,
    DocumentKind,
    DocumentPage,
    ExtractStatus,
    Job,
    JobQueue,
    JobStatus,
    Module,
    User,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.api.modules import get_owned_module
from manabi_server.db import get_db
from manabi_server.jobs.queue import PROCESS_DOCUMENT_TASK, defer_task
from manabi_server.security import get_default_user, require_csrf
from manabi_server.storage import files

router = APIRouter(prefix="/api", tags=["documents"])

MAX_UPLOAD_BYTES = 100 * 1024 * 1024

MAGIC = {
    DocumentKind.pdf: b"%PDF",
    DocumentKind.pptx: b"PK\x03\x04",
}


class PageOut(BaseModel):
    page_no: int
    title: str | None
    speaker_notes: str | None
    has_render: bool
    width: int | None
    height: int | None
    text_html: str | None


class DocumentOut(BaseModel):
    id: int
    module_id: int
    kind: DocumentKind
    filename: str
    byte_size: int
    extract_status: ExtractStatus
    error: str | None
    page_count: int | None
    ai_included: bool
    job_id: int | None = None
    progress_pct: int | None = None
    progress_note: str | None = None


class DocumentDetail(DocumentOut):
    pages: list[PageOut]


def _doc_out(
    doc: Document,
    job_id: int | None = None,
    progress: tuple[int | None, str | None] | None = None,
) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        module_id=doc.module_id,
        kind=doc.kind,
        filename=doc.filename,
        byte_size=doc.byte_size,
        extract_status=doc.extract_status,
        error=doc.error,
        page_count=doc.page_count,
        ai_included=doc.ai_included,
        job_id=job_id,
        progress_pct=progress[0] if progress else None,
        progress_note=progress[1] if progress else None,
    )


async def _get_owned_document(
    document_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> Document:
    from manabi_core.models import Course  # avoid cycle at module import

    doc = (
        await db.execute(
            select(Document)
            .join(Module, Module.id == Document.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(Document.id == document_id, Course.user_id == user.id)
        )
    ).scalar_one_or_none()
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


async def _enqueue_processing(db: AsyncSession, user_id: int, doc: Document) -> Job:
    job = Job(
        user_id=user_id,
        job_type="process_document",
        queue=JobQueue.cpu,
        payload={"document_id": doc.id},
        module_id=doc.module_id,
        document_id=doc.id,
    )
    db.add(job)
    await db.flush()
    job.procrastinate_job_id = await defer_task(
        PROCESS_DOCUMENT_TASK, "cpu", document_id=doc.id, job_id=job.id
    )
    return job


@router.get("/modules/{module_id}/documents")
async def list_documents(
    module: Module = Depends(get_owned_module), db: AsyncSession = Depends(get_db)
) -> list[DocumentOut]:
    docs = (
        (
            await db.execute(
                select(Document)
                .where(Document.module_id == module.id, Document.deleted_at.is_(None))
                .order_by(Document.created_at)
            )
        )
        .scalars()
        .all()
    )
    # Latest job progress for docs still in the pipeline
    in_flight = [
        d.id
        for d in docs
        if d.extract_status in (ExtractStatus.pending, ExtractStatus.processing)
    ]
    progress: dict[int, tuple[int | None, str | None]] = {}
    if in_flight:
        rows = (
            await db.execute(
                select(Job.document_id, Job.progress_pct, Job.progress_note, Job.status)
                .where(Job.document_id.in_(in_flight))
                .order_by(Job.document_id, Job.id.desc())
                .distinct(Job.document_id)
            )
        ).all()
        # queue position for docs still waiting for a worker slot
        queued_ids = (
            (
                await db.execute(
                    select(Job.document_id)
                    .where(
                        Job.job_type == "process_document",
                        Job.status == JobStatus.queued,
                    )
                    .order_by(Job.id)
                )
            )
            .scalars()
            .all()
        )
        position = {doc_id: i for i, doc_id in enumerate(queued_ids)}
        for doc_id, pct, note, status in rows:
            if status == JobStatus.queued:
                ahead = position.get(doc_id, 0)
                note = f"Queued — {ahead} ahead" if ahead else "Queued — next up"
            progress[doc_id] = (pct, note)
    return [_doc_out(d, progress=progress.get(d.id)) for d in docs]


@router.post("/modules/{module_id}/documents", dependencies=[Depends(require_csrf)])
async def upload_document(
    file: UploadFile,
    module: Module = Depends(get_owned_module),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentOut:
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ("pdf", "pptx"):
        raise HTTPException(status_code=422, detail="Only PDF and PPTX files are supported")
    kind = DocumentKind(ext)

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 100 MB limit")
    if not data.startswith(MAGIC[kind]):
        raise HTTPException(
            status_code=422, detail=f"File content does not look like a {ext.upper()}"
        )

    content_hash = hashlib.sha256(data).hexdigest()
    existing = (
        await db.execute(
            select(Document).where(
                Document.module_id == module.id,
                Document.content_hash == content_hash,
                Document.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={"message": "This file is already in the module", "document_id": existing.id},
        )

    rel_path = files.new_original_path(ext)
    files.write_atomic(rel_path, data)

    doc = Document(
        module_id=module.id,
        kind=kind,
        filename=file.filename or f"upload.{ext}",
        storage_path=rel_path,
        content_hash=content_hash,
        byte_size=len(data),
    )
    db.add(doc)
    await db.flush()
    job = await _enqueue_processing(db, user.id, doc)
    await db.commit()
    return _doc_out(doc, job.id)


@router.get("/documents/{document_id}")
async def document_detail(
    doc: Document = Depends(_get_owned_document), db: AsyncSession = Depends(get_db)
) -> DocumentDetail:
    pages = (
        (
            await db.execute(
                select(DocumentPage)
                .where(DocumentPage.document_id == doc.id)
                .order_by(DocumentPage.page_no)
            )
        )
        .scalars()
        .all()
    )
    return DocumentDetail(
        **_doc_out(doc).model_dump(),
        pages=[
            PageOut(
                page_no=p.page_no,
                title=p.title,
                speaker_notes=p.speaker_notes,
                has_render=p.render_path is not None,
                width=p.width,
                height=p.height,
                text_html=p.text_html,
            )
            for p in pages
        ],
    )


async def _page_file(
    db: AsyncSession, doc: Document, page_no: int, thumb: bool
) -> FileResponse:
    page = (
        await db.execute(
            select(DocumentPage).where(
                DocumentPage.document_id == doc.id, DocumentPage.page_no == page_no
            )
        )
    ).scalar_one_or_none()
    rel = (page.thumb_path if thumb else page.render_path) if page else None
    if rel is None:
        raise HTTPException(status_code=404, detail="No render for this page")
    return FileResponse(files.resolve(rel), media_type="image/png")


@router.get("/documents/{document_id}/pages/{page_no}/render")
async def page_render(
    page_no: int,
    doc: Document = Depends(_get_owned_document),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    return await _page_file(db, doc, page_no, thumb=False)


@router.get("/documents/{document_id}/pages/{page_no}/thumb")
async def page_thumb(
    page_no: int,
    doc: Document = Depends(_get_owned_document),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    return await _page_file(db, doc, page_no, thumb=True)


@router.get("/documents/{document_id}/original")
async def download_original(doc: Document = Depends(_get_owned_document)) -> FileResponse:
    media = (
        "application/pdf"
        if doc.kind == DocumentKind.pdf
        else "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )
    return FileResponse(files.resolve(doc.storage_path), media_type=media, filename=doc.filename)


@router.post("/documents/{document_id}/retry", dependencies=[Depends(require_csrf)])
async def retry_processing(
    doc: Document = Depends(_get_owned_document),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentOut:
    if doc.extract_status not in (ExtractStatus.failed, ExtractStatus.ready):
        raise HTTPException(status_code=409, detail="Document is still processing")
    doc.extract_status = ExtractStatus.pending
    doc.extract_stage = None
    doc.error = None
    job = await _enqueue_processing(db, user.id, doc)
    await db.commit()
    return _doc_out(doc, job.id)


class RegionOut(BaseModel):
    page_no: int
    # top-left-origin fractions of the page (0..1), ready to overlay
    left: float
    top: float
    width: float
    height: float


@router.get("/chunks/{chunk_id}/regions")
async def chunk_regions(
    chunk_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> list[RegionOut]:
    """Bounding boxes of the elements a chunk was built from — used by the
    viewer to highlight the cited passage on the rendered page."""
    from manabi_core.models import Chunk, Course, DocElement

    chunk = (
        await db.execute(
            select(Chunk)
            .join(Module, Module.id == Chunk.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(Chunk.id == chunk_id, Course.user_id == user.id)
        )
    ).scalar_one_or_none()
    if chunk is None:
        raise HTTPException(status_code=404, detail="Chunk not found")

    rows = (
        await db.execute(
            select(DocElement, DocumentPage)
            .join(DocumentPage, DocumentPage.id == DocElement.page_id)
            .where(DocElement.id.in_(chunk.element_ids))
        )
    ).all()

    regions: list[RegionOut] = []
    for el, page in rows:
        bbox = el.bbox
        if not bbox or not page.width or not page.height:
            continue
        # Docling bboxes: bottom-left origin, page points; renders are 2× points.
        pts_w = page.width / 2
        pts_h = page.height / 2
        try:
            left = max(0.0, min(1.0, bbox["l"] / pts_w))
            right = max(0.0, min(1.0, bbox["r"] / pts_w))
            y_top = max(bbox["t"], bbox["b"])
            y_bottom = min(bbox["t"], bbox["b"])
            top = max(0.0, min(1.0, (pts_h - y_top) / pts_h))
            bottom = max(0.0, min(1.0, (pts_h - y_bottom) / pts_h))
        except (KeyError, TypeError, ZeroDivisionError):
            continue
        if right - left <= 0 or bottom - top <= 0:
            continue
        regions.append(
            RegionOut(
                page_no=page.page_no,
                left=round(left, 4),
                top=round(top, 4),
                width=round(right - left, 4),
                height=round(bottom - top, 4),
            )
        )
    return regions


class DocumentPatch(BaseModel):
    ai_included: bool


@router.patch("/documents/{document_id}", dependencies=[Depends(require_csrf)])
async def patch_document(
    data: DocumentPatch,
    doc: Document = Depends(_get_owned_document),
    db: AsyncSession = Depends(get_db),
) -> DocumentOut:
    """Toggle whether this material feeds AI generation (summaries/cards/quizzes).

    Enforced at the retrieval SQL layer (manabi_core.retrieval), not in prompts.
    """
    doc.ai_included = data.ai_included
    module = (
        await db.execute(select(Module).where(Module.id == doc.module_id))
    ).scalar_one()
    module.content_version += 1  # existing artifacts become stale/incomplete
    await db.commit()
    return _doc_out(doc)


@router.delete("/documents/{document_id}", dependencies=[Depends(require_csrf)])
async def delete_document(
    doc: Document = Depends(_get_owned_document), db: AsyncSession = Depends(get_db)
) -> dict:
    # Soft delete: recoverable until a future purge job; excluded everywhere now.
    doc.deleted_at = datetime.now(UTC)
    module = (
        await db.execute(select(Module).where(Module.id == doc.module_id))
    ).scalar_one()
    module.content_version += 1
    await db.commit()
    return {"ok": True}
