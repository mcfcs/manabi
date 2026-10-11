"""A course's pronunciation list: how Steven says its terms.

Entries are learned automatically when a reading is recorded (the worker's
manabi_ai.pronunciation) and corrected here; a correction re-records only the
paragraphs that use the term."""

import re

from fastapi import APIRouter, Depends, HTTPException
from manabi_core.models import (
    Course,
    Document,
    Module,
    Narration,
    NarrationSegment,
    Pronunciation,
    User,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.db import get_db
from manabi_server.security import get_default_user, require_csrf

router = APIRouter(prefix="/api", tags=["pronunciations"])


class PronunciationOut(BaseModel):
    id: int
    term: str
    say: str
    source: str  # "auto" | "user"
    match: float | None  # how close the voice came to the intended sounds


class PronunciationIn(BaseModel):
    term: str = Field(min_length=1, max_length=80)
    say: str = Field(min_length=1, max_length=160)


class PronunciationPatch(BaseModel):
    say: str = Field(min_length=1, max_length=160)


class RerecordOut(BaseModel):
    segments: int  # paragraphs queued again
    busy: list[str]  # readings skipped because a recording is running


def _out(p: Pronunciation) -> PronunciationOut:
    return PronunciationOut(id=p.id, term=p.term, say=p.say, source=p.source, match=p.match)


def _clean_say(say: str) -> str:
    # The voice spells out the short pieces of a hyphenated respelling.
    return re.sub(r"\s+", " ", say.replace("-", " ")).strip()


async def _owned_course(db: AsyncSession, user: User, course_id: int) -> Course:
    course = await db.get(Course, course_id)
    if course is None or course.user_id != user.id:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


async def _owned(db: AsyncSession, user: User, pid: int) -> Pronunciation:
    row = (
        await db.execute(
            select(Pronunciation)
            .join(Course, Course.id == Pronunciation.course_id)
            .where(Pronunciation.id == pid, Course.user_id == user.id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Pronunciation not found")
    return row


@router.get("/courses/{course_id}/pronunciations")
async def list_pronunciations(
    course_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> list[PronunciationOut]:
    course = await _owned_course(db, user, course_id)
    rows = (
        await db.execute(
            select(Pronunciation)
            .where(Pronunciation.course_id == course.id)
            .order_by(Pronunciation.term)
        )
    ).scalars()
    return [_out(p) for p in rows]


@router.post("/courses/{course_id}/pronunciations", dependencies=[Depends(require_csrf)])
async def add_pronunciation(
    course_id: int,
    data: PronunciationIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> PronunciationOut:
    course = await _owned_course(db, user, course_id)
    term = data.term.strip()
    existing = (
        await db.execute(
            select(Pronunciation).where(
                Pronunciation.course_id == course.id, Pronunciation.term == term
            )
        )
    ).scalar_one_or_none()
    row = existing or Pronunciation(course_id=course.id, term=term)
    row.say, row.source, row.match = _clean_say(data.say), "user", None
    if existing is None:
        db.add(row)
    await db.commit()
    return _out(row)


@router.patch("/pronunciations/{pid}", dependencies=[Depends(require_csrf)])
async def update_pronunciation(
    pid: int,
    data: PronunciationPatch,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> PronunciationOut:
    row = await _owned(db, user, pid)
    row.say, row.source, row.match = _clean_say(data.say), "user", None
    await db.commit()
    return _out(row)


@router.delete("/pronunciations/{pid}", dependencies=[Depends(require_csrf)])
async def delete_pronunciation(
    pid: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await _owned(db, user, pid)
    await db.delete(row)
    await db.commit()
    return {"ok": True}


@router.post("/pronunciations/{pid}/rerecord", dependencies=[Depends(require_csrf)])
async def rerecord_term(
    pid: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> RerecordOut:
    """Drop the audio of every recorded paragraph in this course that uses the
    term and queue those paragraphs again — not the whole reading."""
    from manabi_server.api.narration import _active_job, prepare_narration

    row = await _owned(db, user, pid)
    word = re.compile(rf"(?<![A-Za-z]){re.escape(row.term)}(?![A-Za-z])", re.IGNORECASE)
    docs = (
        await db.execute(
            select(Document, Narration)
            .join(Module, Module.id == Document.module_id)
            .join(Narration, Narration.document_id == Document.id)
            .where(Module.course_id == row.course_id, Document.deleted_at.is_(None))
        )
    ).all()
    cleared = 0
    busy: list[str] = []
    for doc, narration in docs:
        segments = (
            await db.execute(
                select(NarrationSegment).where(
                    NarrationSegment.narration_id == narration.id,
                    NarrationSegment.audio.is_not(None),
                )
            )
        ).scalars()
        hits = [s for s in segments if word.search(s.spoken_text or "")]
        if not hits:
            continue
        if await _active_job(db, doc.id) is not None:
            busy.append(doc.filename)
            continue
        for s in hits:
            s.audio, s.duration_ms, s.mime = None, None, None
        cleared += len(hits)
        await db.flush()
        await prepare_narration(None, doc=doc, user=user, db=db)  # queues the missing ones
    await db.commit()
    return RerecordOut(segments=cleared, busy=busy)
