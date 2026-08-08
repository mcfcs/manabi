from fastapi import APIRouter, Depends, HTTPException
from manabi_core.models import Course, Document, Module, Note, User
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.db import get_db
from manabi_server.security import get_default_user, require_csrf

router = APIRouter(prefix="/api", tags=["modules"])


class ModuleIn(BaseModel):
    title: str


class ModuleOut(BaseModel):
    id: int
    course_id: int
    title: str
    position: int
    content_version: int
    document_count: int
    has_note: bool


class ModuleDetail(ModuleOut):
    course_code: str
    course_name: str
    course_accent_color: str | None


class ReorderIn(BaseModel):
    ids: list[int]


async def get_owned_module(
    module_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> Module:
    row = (
        await db.execute(
            select(Module)
            .join(Course, Course.id == Module.course_id)
            .where(Module.id == module_id, Course.user_id == user.id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Module not found")
    return row


async def _counts(db: AsyncSession, module_ids: list[int]) -> tuple[dict, set]:
    if not module_ids:
        return {}, set()
    doc_counts = dict(
        (
            await db.execute(
                select(Document.module_id, func.count(Document.id))
                .where(Document.module_id.in_(module_ids), Document.deleted_at.is_(None))
                .group_by(Document.module_id)
            )
        ).all()
    )
    noted = set(
        (
            await db.execute(select(Note.module_id).where(Note.module_id.in_(module_ids)))
        )
        .scalars()
        .all()
    )
    return doc_counts, noted


def _module_out(module: Module, doc_counts: dict, noted: set) -> ModuleOut:
    return ModuleOut(
        id=module.id,
        course_id=module.course_id,
        title=module.title,
        position=module.position,
        content_version=module.content_version,
        document_count=doc_counts.get(module.id, 0),
        has_note=module.id in noted,
    )


@router.get("/courses/{course_id}/modules")
async def list_modules(
    course_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> list[ModuleOut]:
    modules = (
        (
            await db.execute(
                select(Module)
                .join(Course, Course.id == Module.course_id)
                .where(Module.course_id == course_id, Course.user_id == user.id)
                .order_by(Module.position, Module.id)
            )
        )
        .scalars()
        .all()
    )
    doc_counts, noted = await _counts(db, [m.id for m in modules])
    return [_module_out(m, doc_counts, noted) for m in modules]


@router.post("/courses/{course_id}/modules", dependencies=[Depends(require_csrf)])
async def create_module(
    course_id: int,
    data: ModuleIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> ModuleOut:
    course = (
        await db.execute(
            select(Course).where(Course.id == course_id, Course.user_id == user.id)
        )
    ).scalar_one_or_none()
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    max_pos = (
        await db.execute(
            select(func.coalesce(func.max(Module.position), -1)).where(
                Module.course_id == course_id
            )
        )
    ).scalar_one()
    module = Module(course_id=course_id, title=data.title, position=max_pos + 1)
    db.add(module)
    await db.commit()
    return _module_out(module, {}, set())


@router.get("/modules/{module_id}")
async def module_detail(
    module: Module = Depends(get_owned_module), db: AsyncSession = Depends(get_db)
) -> ModuleDetail:
    course = (
        await db.execute(select(Course).where(Course.id == module.course_id))
    ).scalar_one()
    doc_counts, noted = await _counts(db, [module.id])
    base = _module_out(module, doc_counts, noted)
    return ModuleDetail(
        **base.model_dump(),
        course_code=course.code,
        course_name=course.name,
        course_accent_color=course.accent_color,
    )


@router.patch("/modules/{module_id}", dependencies=[Depends(require_csrf)])
async def rename_module(
    data: ModuleIn,
    module: Module = Depends(get_owned_module),
    db: AsyncSession = Depends(get_db),
) -> dict:
    module.title = data.title
    await db.commit()
    return {"ok": True}


@router.put("/courses/{course_id}/modules/reorder", dependencies=[Depends(require_csrf)])
async def reorder_modules(
    course_id: int,
    data: ReorderIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    modules = (
        (
            await db.execute(
                select(Module)
                .join(Course, Course.id == Module.course_id)
                .where(Module.course_id == course_id, Course.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    by_id = {m.id: m for m in modules}
    for position, module_id in enumerate(data.ids):
        if module_id in by_id:
            by_id[module_id].position = position
    await db.commit()
    return {"ok": True}


@router.delete("/modules/{module_id}", dependencies=[Depends(require_csrf)])
async def delete_module(
    confirm: bool = False,
    module: Module = Depends(get_owned_module),
    db: AsyncSession = Depends(get_db),
) -> dict:
    doc_counts, noted = await _counts(db, [module.id])
    if not confirm:
        raise HTTPException(
            status_code=409,
            detail={
                "requires_confirmation": True,
                "documents": doc_counts.get(module.id, 0),
                "notes": 1 if module.id in noted else 0,
            },
        )
    await db.delete(module)  # documents/chunks/notes cascade via FK
    await db.commit()
    return {"ok": True}
