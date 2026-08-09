from fastapi import APIRouter, Depends, HTTPException
from manabi_core.models import Course, Document, Module, Note, User
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.config import get_settings
from manabi_server.db import get_db
from manabi_server.security import get_default_user, require_csrf

router = APIRouter(prefix="/api/courses", tags=["courses"])


class CourseIn(BaseModel):
    code: str
    name: str
    description: str | None = None
    instructor: str | None = None
    term: str | None = None
    accent_color: str | None = None


class CoursePatch(BaseModel):
    code: str | None = None
    name: str | None = None
    description: str | None = None
    instructor: str | None = None
    term: str | None = None
    accent_color: str | None = None


class CourseOut(BaseModel):
    id: int
    code: str
    name: str
    description: str | None
    instructor: str | None
    term: str | None
    accent_color: str | None
    position: int
    module_count: int
    document_count: int = 0
    card_count: int = 0
    canvas_url: str | None = None


class ReorderIn(BaseModel):
    ids: list[int]


def canvas_course_url(canvas_course_id: int | None) -> str | None:
    base = get_settings().canvas_base_url.rstrip("/")
    if not base or not canvas_course_id:
        return None
    return f"{base}/courses/{canvas_course_id}"


def _course_out(
    course: Course, module_count: int, document_count: int = 0, card_count: int = 0
) -> CourseOut:
    return CourseOut(
        id=course.id,
        code=course.code,
        name=course.name,
        description=course.description,
        instructor=course.instructor,
        term=course.term,
        accent_color=course.accent_color,
        position=course.position,
        module_count=module_count,
        document_count=document_count,
        card_count=card_count,
        canvas_url=canvas_course_url(course.canvas_course_id),
    )


async def _get_course(db: AsyncSession, user: User, course_id: int) -> Course:
    course = (
        await db.execute(
            select(Course).where(Course.id == course_id, Course.user_id == user.id)
        )
    ).scalar_one_or_none()
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


@router.get("")
async def list_courses(
    user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> list[CourseOut]:
    rows = (
        await db.execute(
            select(Course, func.count(Module.id))
            .outerjoin(Module, Module.course_id == Course.id)
            .where(Course.user_id == user.id, Course.archived_at.is_(None))
            .group_by(Course.id)
            .order_by(Course.position, Course.id)
        )
    ).all()
    # per-course document + active-card counts for the home cards
    from manabi_core.models import Artifact, ArtifactType, Flashcard, FlashcardStatus

    doc_counts = dict(
        (
            await db.execute(
                select(Module.course_id, func.count(Document.id))
                .join(Document, Document.module_id == Module.id)
                .where(Document.deleted_at.is_(None))
                .group_by(Module.course_id)
            )
        ).all()
    )
    latest_decks = (
        select(func.max(Artifact.id))
        .where(Artifact.artifact_type == ArtifactType.flashcard_deck)
        .group_by(Artifact.module_id)
        .scalar_subquery()
    )
    card_counts = dict(
        (
            await db.execute(
                select(Module.course_id, func.count(Flashcard.id))
                .join(Artifact, Artifact.module_id == Module.id)
                .join(Flashcard, Flashcard.artifact_id == Artifact.id)
                .where(
                    Artifact.id.in_(latest_decks),
                    Flashcard.status == FlashcardStatus.active,
                )
                .group_by(Module.course_id)
            )
        ).all()
    )
    return [
        _course_out(
            course, count, doc_counts.get(course.id, 0), card_counts.get(course.id, 0)
        )
        for course, count in rows
    ]


@router.post("", dependencies=[Depends(require_csrf)])
async def create_course(
    data: CourseIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> CourseOut:
    max_pos = (
        await db.execute(
            select(func.coalesce(func.max(Course.position), -1)).where(
                Course.user_id == user.id
            )
        )
    ).scalar_one()
    course = Course(user_id=user.id, position=max_pos + 1, **data.model_dump())
    db.add(course)
    await db.commit()
    return _course_out(course, 0)


@router.patch("/{course_id}", dependencies=[Depends(require_csrf)])
async def update_course(
    course_id: int,
    data: CoursePatch,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> CourseOut:
    course = await _get_course(db, user, course_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(course, key, value)
    await db.commit()
    count = (
        await db.execute(select(func.count(Module.id)).where(Module.course_id == course.id))
    ).scalar_one()
    return _course_out(course, count)


@router.put("/reorder", dependencies=[Depends(require_csrf)])
async def reorder_courses(
    data: ReorderIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    courses = (
        (await db.execute(select(Course).where(Course.user_id == user.id)))
        .scalars()
        .all()
    )
    by_id = {c.id: c for c in courses}
    for position, course_id in enumerate(data.ids):
        if course_id in by_id:
            by_id[course_id].position = position
    await db.commit()
    return {"ok": True}


@router.delete("/{course_id}", dependencies=[Depends(require_csrf)])
async def delete_course(
    course_id: int,
    confirm: bool = False,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    course = await _get_course(db, user, course_id)
    module_ids = (
        (await db.execute(select(Module.id).where(Module.course_id == course.id)))
        .scalars()
        .all()
    )
    doc_count = 0
    note_count = 0
    if module_ids:
        doc_count = (
            await db.execute(
                select(func.count(Document.id)).where(Document.module_id.in_(module_ids))
            )
        ).scalar_one()
        note_count = (
            await db.execute(
                select(func.count(Note.id)).where(Note.module_id.in_(module_ids))
            )
        ).scalar_one()

    if not confirm:
        raise HTTPException(
            status_code=409,
            detail={
                "requires_confirmation": True,
                "modules": len(module_ids),
                "documents": doc_count,
                "notes": note_count,
            },
        )

    # Modules FK is RESTRICT by design — deletion is always this explicit path.
    if module_ids:
        await db.execute(delete(Module).where(Module.id.in_(module_ids)))
    await db.delete(course)
    await db.commit()
    return {"ok": True}
