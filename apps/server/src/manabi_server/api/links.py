"""Course resource links — external URLs (Canvas ExternalUrl module-items or
manually added). Links can't be AI-chunked; they're an openable reference list
on the course / module."""

from fastapi import APIRouter, Depends, HTTPException
from manabi_core.models import Course, CourseLink, Module, User
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.db import get_db
from manabi_server.security import get_default_user, require_csrf

router = APIRouter(prefix="/api", tags=["links"])


class LinkOut(BaseModel):
    id: int
    course_id: int
    module_id: int | None
    title: str
    url: str
    canvas_item_id: int | None


class LinkIn(BaseModel):
    module_id: int | None = None
    canvas_item_id: int | None = None
    title: str
    url: str
    position: int = 0


def _out(link: CourseLink) -> LinkOut:
    return LinkOut(
        id=link.id,
        course_id=link.course_id,
        module_id=link.module_id,
        title=link.title,
        url=link.url,
        canvas_item_id=link.canvas_item_id,
    )


async def _owned_course(course_id: int, user: User, db: AsyncSession) -> Course:
    course = (
        await db.execute(
            select(Course).where(Course.id == course_id, Course.user_id == user.id)
        )
    ).scalar_one_or_none()
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


@router.get("/courses/{course_id}/links")
async def list_links(
    course_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> list[LinkOut]:
    await _owned_course(course_id, user, db)
    rows = (
        (
            await db.execute(
                select(CourseLink)
                .where(CourseLink.course_id == course_id)
                .order_by(CourseLink.module_id, CourseLink.position, CourseLink.id)
            )
        )
        .scalars()
        .all()
    )
    return [_out(link) for link in rows]


@router.post("/courses/{course_id}/links", dependencies=[Depends(require_csrf)])
async def create_link(
    course_id: int,
    data: LinkIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> LinkOut:
    await _owned_course(course_id, user, db)
    title = (data.title or "").strip() or data.url
    url = (data.url or "").strip()
    if not url:
        raise HTTPException(status_code=422, detail="A URL is required")
    if data.module_id is not None:
        module = (
            await db.execute(
                select(Module).where(
                    Module.id == data.module_id, Module.course_id == course_id
                )
            )
        ).scalar_one_or_none()
        if module is None:
            raise HTTPException(status_code=404, detail="Module not in this course")
    # Upsert Canvas links by (course, canvas_item_id) so re-sync doesn't duplicate.
    existing = None
    if data.canvas_item_id is not None:
        existing = (
            await db.execute(
                select(CourseLink).where(
                    CourseLink.course_id == course_id,
                    CourseLink.canvas_item_id == data.canvas_item_id,
                )
            )
        ).scalar_one_or_none()
    if existing is not None:
        existing.title = title
        existing.url = url
        existing.module_id = data.module_id
        existing.position = data.position
        link = existing
    else:
        link = CourseLink(
            course_id=course_id,
            module_id=data.module_id,
            canvas_item_id=data.canvas_item_id,
            title=title,
            url=url,
            position=data.position,
        )
        db.add(link)
    await db.commit()
    await db.refresh(link)
    return _out(link)


@router.delete("/links/{link_id}", dependencies=[Depends(require_csrf)])
async def delete_link(
    link_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    link = (
        await db.execute(
            select(CourseLink)
            .join(Course, Course.id == CourseLink.course_id)
            .where(CourseLink.id == link_id, Course.user_id == user.id)
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=404, detail="Link not found")
    await db.delete(link)
    await db.commit()
    return {"ok": True}
