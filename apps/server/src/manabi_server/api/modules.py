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
    # Study-kit status glyphs
    summary_state: str = "none"  # none | current | outdated
    card_count: int = 0
    quiz_count: int = 0


class ModuleDetail(ModuleOut):
    course_code: str
    course_name: str
    course_accent_color: str | None
    page_count: int = 0
    best_quiz_score: float | None = None
    note_updated_at: str | None = None


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


async def _study_kit_stats(db: AsyncSession, module_ids: list[int]) -> dict[int, dict]:
    """Per-module status glyph data: summary state, active cards, quiz count.

    summary_state uses the cheap content_version comparison (no chunk loads);
    the precise fingerprint check stays on the summary endpoint itself."""
    from manabi_core.models import Artifact, ArtifactType, Flashcard, FlashcardStatus

    stats: dict[int, dict] = {
        m: {"summary_state": "none", "card_count": 0, "quiz_count": 0}
        for m in module_ids
    }
    if not module_ids:
        return stats

    versions = dict(
        (
            await db.execute(
                select(Module.id, Module.content_version).where(Module.id.in_(module_ids))
            )
        ).all()
    )
    summaries = (
        await db.execute(
            select(Artifact.module_id, Artifact.module_version_at_gen)
            .where(
                Artifact.module_id.in_(module_ids),
                Artifact.artifact_type == ArtifactType.summary,
            )
            .order_by(Artifact.module_id, Artifact.id.desc())
            .distinct(Artifact.module_id)
        )
    ).all()
    for module_id, gen_version in summaries:
        stats[module_id]["summary_state"] = (
            "current" if gen_version >= versions.get(module_id, 0) else "outdated"
        )

    latest_decks = (
        await db.execute(
            select(Artifact.module_id, Artifact.id)
            .where(
                Artifact.module_id.in_(module_ids),
                Artifact.artifact_type == ArtifactType.flashcard_deck,
            )
            .order_by(Artifact.module_id, Artifact.id.desc())
            .distinct(Artifact.module_id)
        )
    ).all()
    for module_id, artifact_id in latest_decks:
        n = (
            await db.execute(
                select(func.count(Flashcard.id)).where(
                    Flashcard.artifact_id == artifact_id,
                    Flashcard.status == FlashcardStatus.active,
                )
            )
        ).scalar_one()
        stats[module_id]["card_count"] = n

    quizzes = (
        await db.execute(
            select(Artifact.module_id, func.count(Artifact.id))
            .where(
                Artifact.module_id.in_(module_ids),
                Artifact.artifact_type == ArtifactType.quiz,
            )
            .group_by(Artifact.module_id)
        )
    ).all()
    for module_id, n in quizzes:
        stats[module_id]["quiz_count"] = n
    return stats


def _module_out(
    module: Module, doc_counts: dict, noted: set, kit: dict | None = None
) -> ModuleOut:
    return ModuleOut(
        id=module.id,
        course_id=module.course_id,
        title=module.title,
        position=module.position,
        content_version=module.content_version,
        document_count=doc_counts.get(module.id, 0),
        has_note=module.id in noted,
        **(kit or {}),
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
    module_ids = [m.id for m in modules]
    doc_counts, noted = await _counts(db, module_ids)
    kits = await _study_kit_stats(db, module_ids)
    return [_module_out(m, doc_counts, noted, kits.get(m.id)) for m in modules]


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
    from manabi_core.models import Artifact, ArtifactType, DocumentPage, QuizAttempt

    course = (
        await db.execute(select(Course).where(Course.id == module.course_id))
    ).scalar_one()
    doc_counts, noted = await _counts(db, [module.id])
    kits = await _study_kit_stats(db, [module.id])
    base = _module_out(module, doc_counts, noted, kits.get(module.id))

    page_count = (
        await db.execute(
            select(func.count(DocumentPage.id))
            .join(Document, Document.id == DocumentPage.document_id)
            .where(Document.module_id == module.id, Document.deleted_at.is_(None))
        )
    ).scalar_one()
    best_score = (
        await db.execute(
            select(func.max(QuizAttempt.score))
            .join(Artifact, Artifact.id == QuizAttempt.artifact_id)
            .where(
                Artifact.module_id == module.id,
                Artifact.artifact_type == ArtifactType.quiz,
            )
        )
    ).scalar_one_or_none()
    note_updated = (
        await db.execute(select(Note.updated_at).where(Note.module_id == module.id))
    ).scalar_one_or_none()

    return ModuleDetail(
        **base.model_dump(),
        course_code=course.code,
        course_name=course.name,
        course_accent_color=course.accent_color,
        page_count=page_count,
        best_quiz_score=best_score,
        note_updated_at=note_updated.isoformat() if note_updated else None,
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
