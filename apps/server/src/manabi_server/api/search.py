"""Global search: one query across courses, modules, documents, page text
(via chunk FTS), notes, tasks, and events — grouped jump targets."""

from fastapi import APIRouter, Depends, Query
from manabi_core.models import (
    CalendarEvent,
    Chunk,
    Course,
    Document,
    Module,
    Note,
    StudyTask,
    User,
)
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.db import get_db
from manabi_server.security import get_default_user

router = APIRouter(prefix="/api/search", tags=["search"])


class SearchHit(BaseModel):
    kind: str  # course | module | document | content | note | task | event
    title: str
    snippet: str | None
    course_id: int | None = None
    module_id: int | None = None
    document_id: int | None = None
    note_id: int | None = None
    page: int | None = None
    accent_color: str | None = None


class SearchOut(BaseModel):
    hits: list[SearchHit]


@router.get("")
async def search(
    q: str = Query(..., min_length=2, max_length=100),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> SearchOut:
    like = f"%{q}%"
    hits: list[SearchHit] = []

    courses = (
        await db.execute(
            select(Course)
            .where(
                Course.user_id == user.id,
                Course.archived_at.is_(None),
                (Course.code.ilike(like)) | (Course.name.ilike(like)),
            )
            .limit(4)
        )
    ).scalars()
    for c in courses:
        hits.append(
            SearchHit(
                kind="course",
                title=f"{c.code} · {c.name}",
                snippet=None,
                course_id=c.id,
                accent_color=c.accent_color,
            )
        )

    modules = (
        await db.execute(
            select(Module, Course)
            .join(Course, Course.id == Module.course_id)
            .where(
                Course.user_id == user.id,
                Module.is_general.is_(False),
                Module.title.ilike(like),
            )
            .limit(5)
        )
    ).all()
    for m, c in modules:
        hits.append(
            SearchHit(
                kind="module",
                title=m.title,
                snippet=c.code,
                course_id=c.id,
                module_id=m.id,
                accent_color=c.accent_color,
            )
        )

    docs = (
        await db.execute(
            select(Document, Module, Course)
            .join(Module, Module.id == Document.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(
                Course.user_id == user.id,
                Document.deleted_at.is_(None),
                Document.filename.ilike(like),
            )
            .limit(5)
        )
    ).all()
    for d, m, c in docs:
        hits.append(
            SearchHit(
                kind="document",
                title=d.filename,
                snippet=f"{c.code} · {m.title}",
                document_id=d.id,
                accent_color=c.accent_color,
            )
        )

    # Content: chunk FTS via the DB-generated tsv column (not ORM-mapped)
    content = (
        await db.execute(
            select(Chunk, Document, Course)
            .join(Document, Document.id == Chunk.document_id)
            .join(Module, Module.id == Chunk.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(
                Course.user_id == user.id,
                Document.deleted_at.is_(None),
                text("chunks.tsv @@ websearch_to_tsquery('english', :q)"),
            )
            .order_by(
                text(
                    "ts_rank(chunks.tsv, websearch_to_tsquery('english', :q)) DESC"
                )
            )
            .limit(6)
            .params(q=q)
        )
    ).all()
    for ch, d, c in content:
        snippet = (ch.text or "")[:140].replace("\n", " ")
        hits.append(
            SearchHit(
                kind="content",
                title=f"{d.filename} · p. {ch.page_start}",
                snippet=snippet,
                document_id=d.id,
                page=ch.page_start,
                accent_color=c.accent_color,
            )
        )

    notes = (
        await db.execute(
            select(Note, Module, Course)
            .join(Module, Module.id == Note.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(Course.user_id == user.id, Note.plain_text.ilike(like))
            .limit(4)
        )
    ).all()
    for n, m, c in notes:
        note_text = n.plain_text or ""
        pos = note_text.lower().find(q.lower())
        snippet = note_text[max(0, pos - 40) : pos + 100].replace("\n", " ")
        hits.append(
            SearchHit(
                kind="note",
                title=f"{n.title} — {m.title}",
                snippet=snippet,
                course_id=c.id,
                module_id=m.id,
                note_id=n.id,
                accent_color=c.accent_color,
            )
        )

    tasks = (
        await db.execute(
            select(StudyTask)
            .where(StudyTask.user_id == user.id, StudyTask.title.ilike(like))
            .limit(4)
        )
    ).scalars()
    for t in tasks:
        hits.append(
            SearchHit(
                kind="task",
                title=t.title,
                snippet=t.due_date.isoformat() if t.due_date else None,
            )
        )

    events = (
        await db.execute(
            select(CalendarEvent)
            .where(CalendarEvent.user_id == user.id, CalendarEvent.title.ilike(like))
            .limit(4)
        )
    ).scalars()
    for e in events:
        hits.append(
            SearchHit(kind="event", title=e.title, snippet=e.date.isoformat())
        )

    return SearchOut(hits=hits)
