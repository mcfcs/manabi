"""Self-tracked class absences ("cuts") and lates.

Every course carries an allowed number of cuts at this university; students
track their own usage. An absence consumes a full cut, a late consumes half.
Totals are computed at read time from the entries — never stored.
"""

from datetime import date as Date  # alias: a field named `date` would shadow the type

from fastapi import APIRouter, Depends, HTTPException
from manabi_core.models import Course, CutEntry, User
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.db import get_db
from manabi_server.security import get_default_user, require_csrf

router = APIRouter(prefix="/api/cuts", tags=["cuts"])

CUT_WEIGHTS = {"cut": 1.0, "late": 0.5}


def cuts_used(kinds: list[str]) -> float:
    """Total cuts consumed: an absence = 1, a late = 0.5."""
    return sum(CUT_WEIGHTS.get(k, 0.0) for k in kinds)


class CutOut(BaseModel):
    id: int
    course_id: int
    date: Date
    kind: str  # cut | late
    reason: str | None


class CourseCutsOut(BaseModel):
    course_id: int
    code: str
    name: str | None
    accent_color: str | None
    total: float  # cuts used (a late counts 0.5)
    entries: list[CutOut]  # newest first


class CutIn(BaseModel):
    course_id: int
    date: Date
    kind: str = "cut"
    reason: str | None = None


def _cut_out(e: CutEntry) -> CutOut:
    return CutOut(
        id=e.id, course_id=e.course_id, date=e.date, kind=e.kind, reason=e.reason
    )


@router.get("")
async def list_cuts(
    user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> list[CourseCutsOut]:
    """Every course with its cut usage — courses without entries included, so
    the whole roster is monitorable at a glance."""
    courses = (
        (
            await db.execute(
                select(Course)
                .where(Course.user_id == user.id)
                .order_by(Course.position, Course.id)
            )
        )
        .scalars()
        .all()
    )
    entries = (
        (
            await db.execute(
                select(CutEntry)
                .join(Course, Course.id == CutEntry.course_id)
                .where(Course.user_id == user.id)
                .order_by(CutEntry.date.desc(), CutEntry.id.desc())
            )
        )
        .scalars()
        .all()
    )
    by_course: dict[int, list[CutEntry]] = {}
    for e in entries:
        by_course.setdefault(e.course_id, []).append(e)
    return [
        CourseCutsOut(
            course_id=c.id,
            code=c.code,
            name=c.name,
            accent_color=c.accent_color,
            total=cuts_used([e.kind for e in by_course.get(c.id, [])]),
            entries=[_cut_out(e) for e in by_course.get(c.id, [])],
        )
        for c in courses
    ]


@router.post("", dependencies=[Depends(require_csrf)])
async def add_cut(
    data: CutIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> CutOut:
    if data.kind not in CUT_WEIGHTS:
        raise HTTPException(status_code=422, detail="kind must be 'cut' or 'late'")
    course = await db.get(Course, data.course_id)
    if course is None or course.user_id != user.id:
        raise HTTPException(status_code=404, detail="Course not found")
    entry = CutEntry(
        course_id=data.course_id,
        date=data.date,
        kind=data.kind,
        reason=(data.reason or "").strip()[:500] or None,
    )
    db.add(entry)
    await db.commit()
    return _cut_out(entry)


@router.delete("/{entry_id}", dependencies=[Depends(require_csrf)])
async def delete_cut(
    entry_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    entry = (
        await db.execute(
            select(CutEntry)
            .join(Course, Course.id == CutEntry.course_id)
            .where(CutEntry.id == entry_id, Course.user_id == user.id)
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    await db.delete(entry)
    await db.commit()
    return {"ok": True}
