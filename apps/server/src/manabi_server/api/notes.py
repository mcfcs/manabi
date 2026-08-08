import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from manabi_core.models import Module, Note, NoteSnapshot
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.api.modules import get_owned_module
from manabi_server.db import get_db
from manabi_server.security import require_csrf

router = APIRouter(prefix="/api", tags=["notes"])

SNAPSHOT_INTERVAL = timedelta(minutes=10)

EMPTY_DOC = {"type": "doc", "content": [{"type": "paragraph"}]}


class NoteIn(BaseModel):
    pm_json: dict


class NoteOut(BaseModel):
    pm_json: dict
    updated_at: datetime | None


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


@router.get("/modules/{module_id}/note")
async def get_note(
    module: Module = Depends(get_owned_module), db: AsyncSession = Depends(get_db)
) -> NoteOut:
    note = (
        await db.execute(select(Note).where(Note.module_id == module.id))
    ).scalar_one_or_none()
    if note is None:
        return NoteOut(pm_json=EMPTY_DOC, updated_at=None)
    return NoteOut(pm_json=note.pm_json, updated_at=note.updated_at)


@router.get("/modules/{module_id}/note/export")
async def export_note(
    module: Module = Depends(get_owned_module), db: AsyncSession = Depends(get_db)
) -> Response:
    from manabi_server.export.docx_export import pm_to_docx

    note = (
        await db.execute(select(Note).where(Note.module_id == module.id))
    ).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="No notes to export yet")

    data = pm_to_docx(note.pm_json, title=f"{module.title} — Notes")
    safe_name = re.sub(r"[^\w\- ]", "", module.title).strip() or "notes"
    return Response(
        content=data,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name} - notes.docx"'
        },
    )


@router.put("/modules/{module_id}/note", dependencies=[Depends(require_csrf)])
async def save_note(
    data: NoteIn,
    module: Module = Depends(get_owned_module),
    db: AsyncSession = Depends(get_db),
) -> NoteOut:
    note = (
        await db.execute(select(Note).where(Note.module_id == module.id))
    ).scalar_one_or_none()
    now = datetime.now(UTC)

    if note is None:
        note = Note(
            module_id=module.id,
            pm_json=data.pm_json,
            plain_text=derive_plain_text(data.pm_json),
        )
        db.add(note)
        await db.flush()
        db.add(NoteSnapshot(note_id=note.id, pm_json=data.pm_json))
    else:
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

    module.content_version += 1  # notes influence staleness of AI artifacts later
    await db.commit()
    # updated_at is server-generated (onupdate=now()); after an UPDATE it is
    # expired and lazy refresh would be sync IO in async context → refresh here.
    await db.refresh(note, ["updated_at"])
    return NoteOut(pm_json=note.pm_json, updated_at=note.updated_at)
