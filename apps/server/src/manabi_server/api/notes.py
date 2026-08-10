"""Notes: multiple user-authored notes per module (Google-Docs-style
sections), ProseMirror JSON + derived plain text, snapshot versioning, and
per-note image assets stored on disk under FILE_STORAGE_ROOT."""

import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from manabi_core.models import Course, Module, Note, NoteSnapshot, User
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.api.modules import get_owned_module
from manabi_server.db import get_db
from manabi_server.security import get_default_user, require_csrf
from manabi_server.storage import files

router = APIRouter(prefix="/api", tags=["notes"])

SNAPSHOT_INTERVAL = timedelta(minutes=10)
MAX_IMAGE_BYTES = 10 * 1024 * 1024

EMPTY_DOC = {"type": "doc", "content": [{"type": "paragraph"}]}

# Extension is decided by magic bytes — the client filename is never trusted.
IMAGE_MAGIC: list[tuple[bytes, str]] = [
    (b"\x89PNG", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF8", "gif"),
]
ASSET_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|gif|webp)$")

IMAGE_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}


def sniff_image_ext(data: bytes) -> str | None:
    for magic, ext in IMAGE_MAGIC:
        if data.startswith(magic):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


class NoteListItem(BaseModel):
    id: int
    title: str
    position: int
    updated_at: datetime


class NoteOut(BaseModel):
    id: int
    module_id: int
    title: str
    position: int
    pm_json: dict
    updated_at: datetime


class NoteCreate(BaseModel):
    title: str | None = None


class NoteContentIn(BaseModel):
    pm_json: dict


class NotePatch(BaseModel):
    title: str | None = None
    position: int | None = None


def derive_plain_text(node: dict) -> str:
    """Walk ProseMirror JSON server-side so retrieval text can't drift."""
    parts: list[str] = []

    def walk(n: dict) -> None:
        if n.get("type") == "text":
            parts.append(n.get("text", ""))
        for child in n.get("content", []) or []:
            walk(child)
        if n.get("type") in ("paragraph", "heading", "listItem", "tableRow", "codeBlock"):
            parts.append("\n")

    walk(node)
    return "".join(parts).strip()


async def _get_owned_note(
    note_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> Note:
    note = (
        await db.execute(
            select(Note)
            .join(Module, Module.id == Note.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(Note.id == note_id, Course.user_id == user.id)
        )
    ).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


def _out(note: Note) -> NoteOut:
    return NoteOut(
        id=note.id,
        module_id=note.module_id,
        title=note.title,
        position=note.position,
        pm_json=note.pm_json,
        updated_at=note.updated_at,
    )


@router.get("/modules/{module_id}/notes")
async def list_notes(
    module: Module = Depends(get_owned_module), db: AsyncSession = Depends(get_db)
) -> list[NoteListItem]:
    rows = (
        (
            await db.execute(
                select(Note)
                .where(Note.module_id == module.id)
                .order_by(Note.position, Note.id)
            )
        )
        .scalars()
        .all()
    )
    return [
        NoteListItem(id=n.id, title=n.title, position=n.position, updated_at=n.updated_at)
        for n in rows
    ]


@router.post("/modules/{module_id}/notes", dependencies=[Depends(require_csrf)])
async def create_note(
    data: NoteCreate,
    module: Module = Depends(get_owned_module),
    db: AsyncSession = Depends(get_db),
) -> NoteOut:
    max_pos = (
        await db.execute(
            select(func.max(Note.position)).where(Note.module_id == module.id)
        )
    ).scalar_one()
    note = Note(
        module_id=module.id,
        title=(data.title or "").strip()[:255] or "Untitled",
        position=(max_pos if max_pos is not None else -1) + 1,
        pm_json=EMPTY_DOC,
        plain_text="",
    )
    db.add(note)
    await db.commit()
    await db.refresh(note, ["updated_at"])
    return _out(note)


@router.get("/notes/{note_id}")
async def get_note(note: Note = Depends(_get_owned_note)) -> NoteOut:
    return _out(note)


@router.put("/notes/{note_id}", dependencies=[Depends(require_csrf)])
async def save_note(
    data: NoteContentIn,
    note: Note = Depends(_get_owned_note),
    db: AsyncSession = Depends(get_db),
) -> NoteOut:
    now = datetime.now(UTC)
    last_snapshot = (
        await db.execute(
            select(NoteSnapshot.created_at)
            .where(NoteSnapshot.note_id == note.id)
            .order_by(NoteSnapshot.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last_snapshot is None or now - last_snapshot > SNAPSHOT_INTERVAL:
        db.add(NoteSnapshot(note_id=note.id, pm_json=note.pm_json))
    note.pm_json = data.pm_json
    note.plain_text = derive_plain_text(data.pm_json)

    module = await db.get(Module, note.module_id)
    if module is not None:
        module.content_version += 1  # notes influence AI-artifact staleness
    await db.commit()
    # updated_at is server-generated (onupdate=now()); refresh to avoid sync
    # lazy-load in async context.
    await db.refresh(note, ["updated_at"])
    return _out(note)


@router.patch("/notes/{note_id}", dependencies=[Depends(require_csrf)])
async def patch_note(
    data: NotePatch,
    note: Note = Depends(_get_owned_note),
    db: AsyncSession = Depends(get_db),
) -> NoteOut:
    if data.title is not None:
        note.title = data.title.strip()[:255] or "Untitled"
    if data.position is not None:
        note.position = max(0, data.position)
    await db.commit()
    await db.refresh(note, ["updated_at"])
    return _out(note)


@router.delete("/notes/{note_id}", dependencies=[Depends(require_csrf)])
async def delete_note(
    note: Note = Depends(_get_owned_note), db: AsyncSession = Depends(get_db)
) -> dict:
    module = await db.get(Module, note.module_id)
    if module is not None:
        module.content_version += 1
    await db.delete(note)  # snapshots cascade via FK
    await db.commit()
    files.delete_note_files(note.id)  # best-effort disk cleanup
    return {"ok": True}


@router.get("/notes/{note_id}/export")
async def export_note(
    note: Note = Depends(_get_owned_note), db: AsyncSession = Depends(get_db)
) -> Response:
    from manabi_server.export.docx_export import pm_to_docx

    module = await db.get(Module, note.module_id)
    module_title = module.title if module is not None else "Module"
    data = pm_to_docx(note.pm_json, title=f"{module_title} — {note.title}")
    safe_name = re.sub(r"[^\w\- ]", "", f"{module_title} - {note.title}").strip() or "notes"
    return Response(
        content=data,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.docx"'},
    )


# ── Images ────────────────────────────────────────────────────────────────


@router.post("/notes/{note_id}/images", dependencies=[Depends(require_csrf)])
async def upload_note_image(
    file: UploadFile,
    note: Note = Depends(_get_owned_note),
) -> dict:
    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 10 MB)")
    ext = sniff_image_ext(data)
    if ext is None:
        raise HTTPException(
            status_code=422, detail="Only PNG, JPEG, GIF, or WebP images"
        )
    rel = files.note_asset_path(note.id, ext)
    files.write_atomic(rel, data)
    name = rel.rsplit("/", 1)[-1]
    return {"url": f"/api/notes/{note.id}/images/{name}"}


@router.get("/notes/{note_id}/images/{name}")
async def get_note_image(
    name: str,
    note: Note = Depends(_get_owned_note),
) -> FileResponse:
    if not ASSET_NAME_RE.fullmatch(name):
        raise HTTPException(status_code=404, detail="Image not found")
    path = files.resolve(f"note_assets/{note.id}/{name}")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    # uuid filenames never change content → immutable caching is safe here
    return FileResponse(
        path,
        media_type=IMAGE_MIME[name.rsplit(".", 1)[-1]],
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )
