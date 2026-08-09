"""Canvas LMS importer — the server proxies the Canvas REST API (the access
token never reaches the browser) and imported files enter the exact same
validation + ingestion path as manual uploads."""

import hashlib

import httpx
from fastapi import APIRouter, Depends, HTTPException
from manabi_core.models import Document, DocumentKind, Module, User
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.api.documents import MAGIC, MAX_UPLOAD_BYTES, _enqueue_processing
from manabi_server.api.modules import get_owned_module
from manabi_server.config import get_settings
from manabi_server.db import get_db
from manabi_server.security import get_default_user, require_csrf
from manabi_server.storage import files

router = APIRouter(prefix="/api/canvas", tags=["canvas"])


class CanvasCourse(BaseModel):
    id: int
    name: str
    course_code: str | None


class CanvasFile(BaseModel):
    id: int
    filename: str
    size: int
    updated_at: str | None
    content_type: str | None


class ImportIn(BaseModel):
    file_id: int
    ai_included: bool = True
    # False → store + render pages only; no text extraction, chunking, or AI
    extract_text: bool = True


def _canvas_config() -> tuple[str, str]:
    settings = get_settings()
    if not settings.canvas_base_url or not settings.canvas_access_token:
        raise HTTPException(
            status_code=409,
            detail="Canvas is not configured — set CANVAS_BASE_URL and "
            "CANVAS_ACCESS_TOKEN in .env",
        )
    return settings.canvas_base_url.rstrip("/"), settings.canvas_access_token


async def _canvas_get(path: str, params: dict | None = None) -> list | dict:
    base, token = _canvas_config()
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"{base}/api/v1{path}",
            params={"per_page": 100, **(params or {})},
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code == 401:
        raise HTTPException(
            status_code=502, detail="Canvas rejected the token — it may have expired"
        )
    if r.status_code >= 400:
        raise HTTPException(
            status_code=502, detail=f"Canvas error {r.status_code}: {r.text[:150]}"
        )
    return r.json()


@router.get("/courses")
async def canvas_courses() -> list[CanvasCourse]:
    data = await _canvas_get(
        "/courses", {"enrollment_state": "active", "state[]": "available"}
    )
    return [
        CanvasCourse(
            id=c["id"], name=c.get("name") or "Untitled", course_code=c.get("course_code")
        )
        for c in data
        if isinstance(c, dict) and "id" in c and c.get("name")
    ]


IMPORTABLE_TYPES = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
)


@router.get("/courses/{canvas_course_id}/files")
async def canvas_files(canvas_course_id: int) -> list[CanvasFile]:
    data = await _canvas_get(
        f"/courses/{canvas_course_id}/files",
        {"sort": "updated_at", "order": "desc"},
    )
    out = []
    for f in data:
        if not isinstance(f, dict):
            continue
        name = (f.get("display_name") or f.get("filename") or "").lower()
        if f.get("content-type") in IMPORTABLE_TYPES or name.endswith((".pdf", ".pptx")):
            out.append(
                CanvasFile(
                    id=f["id"],
                    filename=f.get("display_name") or f.get("filename") or f"file-{f['id']}",
                    size=f.get("size") or 0,
                    updated_at=f.get("updated_at"),
                    content_type=f.get("content-type"),
                )
            )
    return out


@router.post(
    "/modules/{module_id}/import", dependencies=[Depends(require_csrf)]
)
async def canvas_import(
    data: ImportIn,
    module: Module = Depends(get_owned_module),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
):
    from manabi_server.api.documents import _doc_out

    # File metadata (incl. the authenticated download URL)
    meta = await _canvas_get(f"/files/{data.file_id}")
    if not isinstance(meta, dict) or "url" not in meta:
        raise HTTPException(status_code=502, detail="Canvas file metadata unavailable")
    filename = meta.get("display_name") or meta.get("filename") or f"canvas-{data.file_id}"
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in ("pdf", "pptx"):
        raise HTTPException(status_code=422, detail="Only PDF and PPTX can be imported")

    _, token = _canvas_config()
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        r = await client.get(
            meta["url"], headers={"Authorization": f"Bearer {token}"}
        )
    if r.status_code >= 400:
        raise HTTPException(
            status_code=502, detail=f"Canvas download failed ({r.status_code})"
        )
    content = r.content

    # Same validation + ingestion as manual uploads
    kind = DocumentKind(ext)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 100 MB limit")
    if not content.startswith(MAGIC[kind]):
        raise HTTPException(
            status_code=422, detail=f"Downloaded file does not look like a {ext.upper()}"
        )
    content_hash = hashlib.sha256(content).hexdigest()
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
    files.write_atomic(rel_path, content)
    doc = Document(
        module_id=module.id,
        kind=kind,
        filename=filename,
        storage_path=rel_path,
        content_hash=content_hash,
        byte_size=len(content),
        ai_included=data.ai_included and data.extract_text,
        processing_mode="full" if data.extract_text else "render_only",
    )
    db.add(doc)
    await db.flush()
    job = await _enqueue_processing(db, user.id, doc)
    await db.commit()
    return _doc_out(doc, job.id)
