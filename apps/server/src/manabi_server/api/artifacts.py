"""AI artifact endpoints: summaries, flashcard decks, quizzes.

Generation is asynchronous: POST .../generate creates a Job on the gpu queue
and returns it; the worker on the AI node persists the artifact. Staleness is
computed at read time by comparing the artifact's source fingerprint against
the module's current AI-eligible chunk set.
"""

import asyncio
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from manabi_core.models import (
    AIFeedback,
    AIFeedbackKind,
    Artifact,
    ArtifactType,
    Citation,
    Course,
    Document,
    Flashcard,
    FlashcardStatus,
    Job,
    JobQueue,
    LectureAudio,
    LectureCheckpointResult,
    Module,
    Note,
    QuizAttempt,
    QuizQuestion,
    SummaryHighlight,
    User,
)
from manabi_core.retrieval import (
    dedup_diversify,
    load_chunks_by_ids,
    load_context_chunks,
    retrieve,
    source_fingerprint,
)
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.api.modules import get_owned_module
from manabi_server.db import get_db
from manabi_server.jobs.queue import (
    DEFINE_TERM_TASK,
    GENERATE_FLASHCARDS_TASK,
    GENERATE_QUIZ_TASK,
    GENERATE_SUMMARY_TASK,
    REGENERATE_QUESTION_TASK,
    TEACH_MODULE_TASK,
    VERIFY_QUESTION_TASK,
    defer_task,
)
from manabi_server.security import get_default_user, require_csrf

router = APIRouter(prefix="/api", tags=["artifacts"])


# ── Shared shapes ─────────────────────────────────────────────────────────


class CitationOut(BaseModel):
    id: int
    item_ref: str
    chunk_id: int | None
    document_id: int | None
    document_title: str
    page_start: int | None
    page_end: int | None
    support_score: float | None
    status: str


class JobRef(BaseModel):
    job_id: int


async def _staleness(db: AsyncSession, artifact: Artifact) -> str:
    """fresh: chunk set identical · incomplete: everything the artifact used
    is unchanged but new material exists · stale: used material changed."""
    if artifact.instructions:
        # Focused-retrieval artifact: its chunk set was picked by topic
        # relevance and can't be reproduced from scope alone. Fresh while the
        # exact chunks it used still exist unchanged, stale otherwise — no
        # "incomplete" tier (new material is expected to be off-topic).
        surviving = await load_chunks_by_ids(
            db, [int(c) for c in artifact.source_chunk_ids]
        )
        return (
            "fresh"
            if source_fingerprint(surviving) == artifact.source_fingerprint
            else "stale"
        )
    # Compare against the same scope the artifact was generated from (None =
    # whole module, today's behavior). Note-scope edits are invisible here —
    # notes are emphasis, not chunks.
    chunks = await load_context_chunks(
        db,
        [int(m) for m in artifact.scope_module_ids],
        document_ids=artifact.scope_document_ids,
    )
    if source_fingerprint(chunks) == artifact.source_fingerprint:
        return "fresh"
    old_ids = set(artifact.source_chunk_ids)
    surviving = [c for c in chunks if c.id in old_ids]
    if len(surviving) == len(old_ids) and source_fingerprint(surviving) == (
        artifact.source_fingerprint
    ):
        return "incomplete"
    return "stale"


async def _citations_by_ref(
    db: AsyncSession, artifact_id: int
) -> dict[str, list[CitationOut]]:
    rows = (
        (
            await db.execute(
                select(Citation).where(Citation.artifact_id == artifact_id).order_by(Citation.id)
            )
        )
        .scalars()
        .all()
    )
    grouped: dict[str, list[CitationOut]] = {}
    for c in rows:
        grouped.setdefault(c.item_ref, []).append(
            CitationOut(
                id=c.id,
                item_ref=c.item_ref,
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                document_title=c.document_title,
                page_start=c.page_start,
                page_end=c.page_end,
                support_score=c.support_score,
                status=c.status,
            )
        )
    return grouped


async def _latest_artifact(
    db: AsyncSession, module_id: int, artifact_type: ArtifactType
) -> Artifact | None:
    return (
        await db.execute(
            select(Artifact)
            .where(Artifact.module_id == module_id, Artifact.artifact_type == artifact_type)
            .order_by(Artifact.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _review_deck(db: AsyncSession, module_id: int) -> Artifact | None:
    """The module's review-rotation deck, falling back to the latest deck so
    module-level card routes stay sane if every deck was toggled out."""
    artifact = (
        await db.execute(
            select(Artifact)
            .where(
                Artifact.module_id == module_id,
                Artifact.artifact_type == ArtifactType.flashcard_deck,
                Artifact.review_enabled.is_(True),
            )
            .order_by(Artifact.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if artifact is not None:
        return artifact
    return await _latest_artifact(db, module_id, ArtifactType.flashcard_deck)


def _matching_inflight(jobs: list[Job], payload: dict) -> Job | None:
    """Duplicate-proofing is payload-aware: only a request identical to one
    already in flight is collapsed into it — different scopes/instructions on
    the same module run as separate jobs."""
    for job in jobs:
        if job.payload == payload:
            return job
    return None


async def _validate_scope(
    db: AsyncSession,
    module_id: int,
    document_ids: list[int] | None,
    note_ids: list[int] | None,
) -> None:
    """422 unless every selected document/note belongs to the module."""
    if document_ids:
        valid = set(
            (
                await db.execute(
                    select(Document.id).where(
                        Document.module_id == module_id,
                        Document.deleted_at.is_(None),
                    )
                )
            ).scalars()
        )
        if not set(document_ids) <= valid:
            raise HTTPException(status_code=422, detail="Document not in this module")
    if note_ids:
        valid = set(
            (
                await db.execute(
                    select(Note.id).where(Note.module_id == module_id)
                )
            ).scalars()
        )
        if not set(note_ids) <= valid:
            raise HTTPException(status_code=422, detail="Note not in this module")


# Generation wants breadth (it writes many items, unlike a chat answer), so the
# focus pool is much wider than chat's 12/8.
_FOCUS_POOL, _FOCUS_FINAL, _FOCUS_MIN_HITS = 32, 24, 6


async def _focus_chunk_ids(
    db: AsyncSession,
    module_ids: list[int],
    instructions: str,
    document_ids: list[int] | None,
) -> list[int] | None:
    """Topic-focused retrieval for instruction-steered generation (mirrors chat
    _dispatch_answer). Returns None when the topic barely matches the material —
    the worker then falls back to the full scope with only the FOCUS prompt."""
    from manabi_server.processing.embedding import embed_texts

    vec = (await asyncio.to_thread(embed_texts, [instructions], is_query=True))[0]
    hits = await retrieve(
        db, module_ids, vec, instructions, k=_FOCUS_POOL, document_ids=document_ids
    )
    ids = [h.id for h in dedup_diversify(hits, _FOCUS_FINAL)]
    return ids if len(ids) >= _FOCUS_MIN_HITS else None


async def _enqueue_generation(
    db: AsyncSession,
    user: User,
    module: Module,
    job_type: str,
    task_name: str,
    **task_kwargs,
) -> Job:
    from manabi_core.models import JobStatus

    inflight = (
        (
            await db.execute(
                select(Job).where(
                    Job.module_id == module.id,
                    Job.job_type == job_type,
                    Job.status.in_([JobStatus.queued, JobStatus.running]),
                )
            )
        )
        .scalars()
        .all()
    )
    existing = _matching_inflight(list(inflight), task_kwargs)
    if existing is not None:
        return existing

    chunks = await load_context_chunks(
        db, [module.id], document_ids=task_kwargs.get("document_ids")
    )
    # Exercise mode with a focus topic can synthesize from nothing — every
    # other generation needs at least one AI-eligible chunk in scope.
    topic_only_ok = bool(
        task_kwargs.get("mode") == "exercise" and task_kwargs.get("instructions")
    )
    if not chunks and not topic_only_ok:
        raise HTTPException(
            status_code=409,
            detail="No AI-eligible material in the selected sources — pick "
            "documents that are included for AI, or widen the selection",
        )
    job = Job(
        user_id=user.id,
        job_type=job_type,
        queue=JobQueue.gpu,
        payload=task_kwargs,
        module_id=module.id,
    )
    db.add(job)
    await db.flush()
    job.procrastinate_job_id = await defer_task(
        task_name, "gpu", job_id=job.id, **task_kwargs
    )
    await db.commit()
    return job


# ── Whole-module generation ───────────────────────────────────────────────


QUIZ_TYPES = (
    "mcq",
    "tf",
    "short",
    "enumeration",
    "identification",
    "essay",
    "coding",
    "output",
)


class GenerateAllIn(BaseModel):
    summary: bool = True
    flashcards_count: int | None = 12
    quiz_count: int | None = None
    quiz_types: list[str] = ["mcq", "tf", "short"]


@router.post("/modules/{module_id}/generate-all", dependencies=[Depends(require_csrf)])
async def generate_all(
    config: GenerateAllIn,
    module: Module = Depends(get_owned_module),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Queue the selected artifact generations; the GPU worker runs them in
    order. Each is duplicate-proof via _enqueue_generation."""
    jobs: dict[str, int] = {}
    if config.summary:
        job = await _enqueue_generation(
            db, user, module, "generate_summary", GENERATE_SUMMARY_TASK,
            module_id=module.id,
        )
        jobs["summary"] = job.id
    if config.flashcards_count:
        job = await _enqueue_generation(
            db, user, module, "generate_flashcards", GENERATE_FLASHCARDS_TASK,
            module_id=module.id, count=max(4, min(60, config.flashcards_count)),
        )
        jobs["flashcards"] = job.id
    if config.quiz_count:
        types = [t for t in config.quiz_types if t in QUIZ_TYPES] or ["mcq"]
        job = await _enqueue_generation(
            db, user, module, "generate_quiz", GENERATE_QUIZ_TASK,
            module_ids=[module.id], types=types,
            count=max(3, min(30, config.quiz_count)),
        )
        jobs["quiz"] = job.id
    if not jobs:
        raise HTTPException(status_code=422, detail="Nothing selected to generate")
    return {"jobs": jobs}


# ── Generation history ────────────────────────────────────────────────────


class ArtifactVersion(BaseModel):
    artifact_id: int
    artifact_type: ArtifactType
    title: str
    model_name: str
    generated_at: datetime
    item_count: int
    review_enabled: bool | None = None
    generation_mode: str | None = None
    instructions: str | None = None
    scope_document_ids: list[int] | None = None
    scope_note_ids: list[int] | None = None


@router.get("/modules/{module_id}/artifacts")
async def list_artifact_versions(
    type: ArtifactType,
    module: Module = Depends(get_owned_module),
    db: AsyncSession = Depends(get_db),
) -> list[ArtifactVersion]:
    artifacts = (
        (
            await db.execute(
                select(Artifact)
                .where(Artifact.module_id == module.id, Artifact.artifact_type == type)
                .order_by(Artifact.id.desc())
            )
        )
        .scalars()
        .all()
    )
    out = []
    for a in artifacts:
        if a.artifact_type == ArtifactType.summary:
            count = sum(len(s.get("blocks", [])) for s in a.content.get("sections", []))
        elif a.artifact_type == ArtifactType.flashcard_deck:
            count = len(
                (
                    await db.execute(
                        select(Flashcard.id).where(Flashcard.artifact_id == a.id)
                    )
                ).all()
            )
        else:
            count = len(
                (
                    await db.execute(
                        select(QuizQuestion.id).where(QuizQuestion.artifact_id == a.id)
                    )
                ).all()
            )
        out.append(
            ArtifactVersion(
                artifact_id=a.id,
                artifact_type=a.artifact_type,
                title=a.title,
                model_name=a.model_name,
                generated_at=a.created_at,
                item_count=count,
                review_enabled=a.review_enabled,
                generation_mode=a.generation_mode,
                instructions=a.instructions,
                scope_document_ids=a.scope_document_ids,
                scope_note_ids=a.scope_note_ids,
            )
        )
    return out


async def _get_owned_artifact(
    artifact_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> Artifact:
    artifact = (
        await db.execute(
            select(Artifact)
            .join(Module, Module.id == Artifact.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(Artifact.id == artifact_id, Course.user_id == user.id)
        )
    ).scalar_one_or_none()
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact


@router.get("/artifacts/{artifact_id}")
async def get_artifact_version(
    artifact: Artifact = Depends(_get_owned_artifact), db: AsyncSession = Depends(get_db)
) -> dict:
    """Historical artifact rendered in the same shape as the live endpoints."""
    citations = await _citations_by_ref(db, artifact.id)
    base = {
        "artifact_id": artifact.id,
        "artifact_type": artifact.artifact_type,
        "title": artifact.title,
        "model_name": artifact.model_name,
        "generated_at": artifact.created_at,
        "staleness": await _staleness(db, artifact),
        "review_enabled": artifact.review_enabled,
        "generation_mode": artifact.generation_mode,
        "instructions": artifact.instructions,
        "citations": {k: [c.model_dump() for c in v] for k, v in citations.items()},
    }
    if artifact.artifact_type == ArtifactType.summary:
        base["overview"] = artifact.content.get("overview", "")
        base["sections"] = artifact.content.get("sections", [])
        base["key_terms"] = artifact.content.get("key_terms", [])
        base["acronyms"] = artifact.content.get("acronyms", [])
        base["people"] = artifact.content.get("people", [])
        base["edited_at"] = artifact.content.get("edited_at")
    elif artifact.artifact_type == ArtifactType.flashcard_deck:
        cards = (
            (
                await db.execute(
                    select(Flashcard)
                    .where(Flashcard.artifact_id == artifact.id)
                    .order_by(Flashcard.ord, Flashcard.id)
                )
            )
            .scalars()
            .all()
        )
        base["cards"] = [
            {
                "id": c.id,
                "front": c.front,
                "back": c.back,
                "status": c.status,
                "edited": c.edited,
                "citations": [x.model_dump() for x in citations.get(f"card:{c.ord}", [])],
            }
            for c in cards
        ]
    return base


class ArtifactPatch(BaseModel):
    title: str | None = None
    review_enabled: bool | None = None


@router.patch("/artifacts/{artifact_id}", dependencies=[Depends(require_csrf)])
async def patch_artifact(
    data: ArtifactPatch,
    artifact: Artifact = Depends(_get_owned_artifact),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Rename a deck/quiz; toggle a deck's SRS rotation membership."""
    if artifact.artifact_type not in (
        ArtifactType.flashcard_deck,
        ArtifactType.quiz,
    ):
        raise HTTPException(status_code=422, detail="Not a deck or quiz artifact")
    if data.title is not None:
        title = data.title.strip()[:255]
        if not title:
            raise HTTPException(status_code=422, detail="Title cannot be empty")
        artifact.title = title
    if data.review_enabled is not None:
        if artifact.artifact_type != ArtifactType.flashcard_deck:
            raise HTTPException(
                status_code=422, detail="Only flashcard decks join the review queue"
            )
        artifact.review_enabled = data.review_enabled
    await db.commit()
    return {"ok": True}


@router.delete("/artifacts/{artifact_id}", dependencies=[Depends(require_csrf)])
async def delete_artifact(
    artifact: Artifact = Depends(_get_owned_artifact),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a deck or quiz (cards/questions/citations/attempts cascade).
    Deleting a review-rotation deck removes its module from the SRS queue
    until another deck is generated or toggled in — the UI warns first."""
    if artifact.artifact_type not in (
        ArtifactType.flashcard_deck,
        ArtifactType.quiz,
    ):
        raise HTTPException(status_code=422, detail="Not a deck or quiz artifact")
    await db.delete(artifact)
    await db.commit()
    return {"ok": True}


# ── Summary term editing + AI find-in-material ───────────────────────────


class TermIn(BaseModel):
    term: str
    definition: str
    user_added: bool = True


class AcronymIn(BaseModel):
    acronym: str
    meaning: str
    user_added: bool = True


class TermsPatch(BaseModel):
    key_terms: list[TermIn] | None = None
    acronyms: list[AcronymIn] | None = None


@router.patch("/artifacts/{artifact_id}/terms", dependencies=[Depends(require_csrf)])
async def patch_terms(
    data: TermsPatch,
    artifact: Artifact = Depends(_get_owned_artifact),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manual editing of a summary's key terms / acronyms. AI-generated
    entries keep their citations; user entries carry user_added instead."""
    if artifact.artifact_type != ArtifactType.summary:
        raise HTTPException(status_code=422, detail="Not a summary artifact")
    content = dict(artifact.content)
    if data.key_terms is not None:
        content["key_terms"] = [t.model_dump() for t in data.key_terms]
    if data.acronyms is not None:
        content["acronyms"] = [a.model_dump() for a in data.acronyms]
    artifact.content = content
    await db.commit()
    return {"ok": True}


class SectionBlockIn(BaseModel):
    text: str


class SectionIn(BaseModel):
    title: str
    blocks: list[SectionBlockIn]


class SectionsPatch(BaseModel):
    sections: list[SectionIn]


@router.patch("/artifacts/{artifact_id}/sections", dependencies=[Depends(require_csrf)])
async def patch_sections(
    data: SectionsPatch,
    artifact: Artifact = Depends(_get_owned_artifact),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manual editing of a summary's section prose. Marks each changed block
    `edited` (sticky) and stamps a summary-level `edited_at`. Preserves each
    block's chunk_ids so citations (keyed by s{si}:b{bi}) keep resolving; block
    count/order is unchanged (text-only editing)."""
    if artifact.artifact_type != ArtifactType.summary:
        raise HTTPException(status_code=422, detail="Not a summary artifact")
    content = dict(artifact.content)
    old_sections = content.get("sections", [])
    new_sections: list[dict] = []
    changed = False
    for si, sec in enumerate(data.sections):
        old_sec = old_sections[si] if si < len(old_sections) else {}
        old_blocks = old_sec.get("blocks", [])
        blocks: list[dict] = []
        for bi, blk in enumerate(sec.blocks):
            old_blk = old_blocks[bi] if bi < len(old_blocks) else {}
            text_changed = blk.text != (old_blk.get("text") or "")
            changed = changed or text_changed
            blocks.append(
                {
                    "text": blk.text,
                    "chunk_ids": old_blk.get("chunk_ids", []),
                    "edited": bool(old_blk.get("edited")) or text_changed,
                }
            )
        changed = changed or sec.title != (old_sec.get("title") or "")
        new_sections.append({"title": sec.title, "blocks": blocks})
    content["sections"] = new_sections
    if changed:
        content["edited_at"] = datetime.now(UTC).isoformat()
    artifact.content = content
    await db.commit()
    return {"ok": True}


# ── Summary highlights (persistent, artifact-anchored) ────────────────────

_HL_COLORS = ("yellow", "blue", "red", "green")


class HighlightIn(BaseModel):
    quote: str
    note: str | None = None
    color: str = "yellow"


class HighlightPatch(BaseModel):
    note: str | None = None
    color: str | None = None


class HighlightOut(BaseModel):
    id: int
    quote: str
    note: str | None
    color: str


@router.get("/artifacts/{artifact_id}/highlights")
async def list_highlights(
    artifact: Artifact = Depends(_get_owned_artifact), db: AsyncSession = Depends(get_db)
) -> list[HighlightOut]:
    rows = (
        (
            await db.execute(
                select(SummaryHighlight)
                .where(SummaryHighlight.artifact_id == artifact.id)
                .order_by(SummaryHighlight.id)
            )
        )
        .scalars()
        .all()
    )
    return [
        HighlightOut(id=h.id, quote=h.quote, note=h.note, color=h.color) for h in rows
    ]


@router.post(
    "/artifacts/{artifact_id}/highlights", dependencies=[Depends(require_csrf)]
)
async def create_highlight(
    data: HighlightIn,
    artifact: Artifact = Depends(_get_owned_artifact),
    db: AsyncSession = Depends(get_db),
) -> HighlightOut:
    quote = data.quote.strip()
    if not quote:
        raise HTTPException(status_code=422, detail="Empty selection")
    hl = SummaryHighlight(
        artifact_id=artifact.id,
        quote=quote[:2000],
        note=data.note,
        color=data.color if data.color in _HL_COLORS else "yellow",
    )
    db.add(hl)
    await db.commit()
    return HighlightOut(id=hl.id, quote=hl.quote, note=hl.note, color=hl.color)


async def _get_owned_highlight(
    highlight_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> SummaryHighlight:
    hl = (
        await db.execute(
            select(SummaryHighlight)
            .join(Artifact, Artifact.id == SummaryHighlight.artifact_id)
            .join(Module, Module.id == Artifact.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(SummaryHighlight.id == highlight_id, Course.user_id == user.id)
        )
    ).scalar_one_or_none()
    if hl is None:
        raise HTTPException(status_code=404, detail="Highlight not found")
    return hl


@router.patch("/summary-highlights/{highlight_id}", dependencies=[Depends(require_csrf)])
async def update_highlight(
    data: HighlightPatch,
    hl: SummaryHighlight = Depends(_get_owned_highlight),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if data.note is not None:
        hl.note = data.note or None
    if data.color in _HL_COLORS:
        hl.color = data.color
    await db.commit()
    return {"ok": True}


@router.delete("/summary-highlights/{highlight_id}", dependencies=[Depends(require_csrf)])
async def delete_highlight(
    hl: SummaryHighlight = Depends(_get_owned_highlight),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await db.delete(hl)
    await db.commit()
    return {"ok": True}


class FindTermIn(BaseModel):
    term: str


@router.post(
    "/artifacts/{artifact_id}/terms/find", dependencies=[Depends(require_csrf)]
)
async def find_term(
    data: FindTermIn,
    artifact: Artifact = Depends(_get_owned_artifact),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> JobRef:
    """User names a missing term → retrieval decides honestly whether the
    materials mention it; only then does the AI define it (with citations)."""
    import asyncio

    from manabi_core.retrieval import retrieve

    from manabi_server.processing.embedding import embed_texts

    if artifact.artifact_type != ArtifactType.summary:
        raise HTTPException(status_code=422, detail="Not a summary artifact")
    term = data.term.strip()
    if not term:
        raise HTTPException(status_code=422, detail="Term is empty")

    scope = [int(m) for m in artifact.scope_module_ids]

    # Gate on a LITERAL match first — vector search always returns nearest
    # neighbors, so it can't tell "absent" from "related". Terms the user
    # wants defined appear verbatim in real materials.
    from sqlalchemy import text as sql_text

    literal_hits = (
        await db.execute(
            sql_text(
                """
                SELECT count(*) FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.module_id = ANY(:scope) AND d.ai_included
                  AND d.deleted_at IS NULL AND c.text ILIKE :pat
                """
            ),
            {"scope": scope, "pat": f"%{term}%"},
        )
    ).scalar_one()
    if literal_hits == 0:
        raise HTTPException(
            status_code=404,
            detail=f"'{term}' was not found in this module's materials",
        )

    vec = (await asyncio.to_thread(embed_texts, [term], is_query=True))[0]
    hits = await retrieve(db, scope, vec, term, k=6)
    if not hits:
        raise HTTPException(
            status_code=404,
            detail=f"'{term}' was not found in this module's materials",
        )

    job = Job(
        user_id=user.id,
        job_type="define_term",
        queue=JobQueue.gpu,
        payload={"term": term, "artifact_id": artifact.id},
        module_id=artifact.module_id,
    )
    db.add(job)
    await db.flush()
    job.procrastinate_job_id = await defer_task(
        DEFINE_TERM_TASK,
        "gpu",
        job_id=job.id,
        artifact_id=artifact.id,
        term=term,
        chunk_ids=[h.id for h in hits],
    )
    await db.commit()
    return JobRef(job_id=job.id)


# ── Active generation jobs (resume after navigation/reload) ──────────────


class ActiveJobOut(BaseModel):
    job_id: int
    job_type: str
    status: str
    progress_pct: int | None
    progress_note: str | None


@router.get("/modules/{module_id}/active-jobs")
async def active_jobs(
    module: Module = Depends(get_owned_module), db: AsyncSession = Depends(get_db)
) -> list[ActiveJobOut]:
    from manabi_core.models import JobStatus

    jobs = (
        (
            await db.execute(
                select(Job)
                .where(
                    Job.module_id == module.id,
                    Job.job_type.in_(
                        [
                            "generate_summary",
                            "generate_flashcards",
                            "generate_quiz",
                            "define_term",
                        ]
                    ),
                    Job.status.in_([JobStatus.queued, JobStatus.running]),
                )
                .order_by(Job.id)
            )
        )
        .scalars()
        .all()
    )
    return [
        ActiveJobOut(
            job_id=j.id,
            job_type=j.job_type,
            status=j.status,
            progress_pct=j.progress_pct,
            progress_note=j.progress_note,
        )
        for j in jobs
    ]


# ── Summary ───────────────────────────────────────────────────────────────


class SummaryOut(BaseModel):
    artifact_id: int
    title: str
    model_name: str
    generated_at: datetime
    staleness: str
    overview: str = ""
    sections: list[dict]
    key_terms: list[dict] = []
    acronyms: list[dict] = []
    people: list[dict] = []
    coverage: dict | None = None
    edited_at: str | None = None
    citations: dict[str, list[CitationOut]]


@router.get("/modules/{module_id}/summary")
async def get_summary(
    module: Module = Depends(get_owned_module), db: AsyncSession = Depends(get_db)
) -> SummaryOut | None:
    artifact = await _latest_artifact(db, module.id, ArtifactType.summary)
    if artifact is None:
        return None
    return SummaryOut(
        artifact_id=artifact.id,
        title=artifact.title,
        model_name=artifact.model_name,
        generated_at=artifact.created_at,
        staleness=await _staleness(db, artifact),
        overview=artifact.content.get("overview", ""),
        sections=artifact.content.get("sections", []),
        key_terms=artifact.content.get("key_terms", []),
        acronyms=artifact.content.get("acronyms", []),
        people=artifact.content.get("people", []),
        coverage=artifact.content.get("coverage"),
        edited_at=artifact.content.get("edited_at"),
        citations=await _citations_by_ref(db, artifact.id),
    )


@router.post("/modules/{module_id}/summary/generate", dependencies=[Depends(require_csrf)])
async def generate_summary(
    module: Module = Depends(get_owned_module),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> JobRef:
    job = await _enqueue_generation(
        db, user, module, "generate_summary", GENERATE_SUMMARY_TASK, module_id=module.id
    )
    return JobRef(job_id=job.id)


# ── Flashcards ────────────────────────────────────────────────────────────


class CardOut(BaseModel):
    id: int
    front: str
    back: str
    status: FlashcardStatus
    edited: bool
    citations: list[CitationOut]


class DeckOut(BaseModel):
    artifact_id: int
    title: str
    model_name: str
    generated_at: datetime
    staleness: str
    review_enabled: bool | None
    generation_mode: str | None
    instructions: str | None
    cards: list[CardOut]


class GenerateCardsIn(BaseModel):
    count: int = 12
    # None = whole module of that kind; [] = none (documents [] alone will 409 —
    # generation needs at least one AI-eligible chunk in scope).
    document_ids: list[int] | None = None
    note_ids: list[int] | None = None
    instructions: str | None = None
    mode: Literal["sources", "exercise"] = "sources"


class CardPatch(BaseModel):
    front: str | None = None
    back: str | None = None
    status: FlashcardStatus | None = None


async def _deck_out(db: AsyncSession, artifact: Artifact) -> DeckOut:
    cards = (
        (
            await db.execute(
                select(Flashcard)
                .where(Flashcard.artifact_id == artifact.id)
                .order_by(Flashcard.ord, Flashcard.id)
            )
        )
        .scalars()
        .all()
    )
    citations = await _citations_by_ref(db, artifact.id)
    return DeckOut(
        artifact_id=artifact.id,
        title=artifact.title,
        model_name=artifact.model_name,
        generated_at=artifact.created_at,
        staleness=await _staleness(db, artifact),
        review_enabled=artifact.review_enabled,
        generation_mode=artifact.generation_mode,
        instructions=artifact.instructions,
        cards=[
            CardOut(
                id=c.id,
                front=c.front,
                back=c.back,
                status=c.status,
                edited=c.edited,
                citations=citations.get(f"card:{c.ord}", []),
            )
            for c in cards
        ],
    )


@router.get("/modules/{module_id}/flashcards")
async def get_deck(
    module: Module = Depends(get_owned_module), db: AsyncSession = Depends(get_db)
) -> DeckOut | None:
    """The module's review-rotation deck (legacy single-deck shape)."""
    artifact = await _review_deck(db, module.id)
    if artifact is None:
        return None
    return await _deck_out(db, artifact)


async def _get_owned_deck(
    artifact_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> Artifact:
    artifact = (
        await db.execute(
            select(Artifact)
            .join(Module, Module.id == Artifact.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(
                Artifact.id == artifact_id,
                Artifact.artifact_type == ArtifactType.flashcard_deck,
                Course.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if artifact is None:
        raise HTTPException(status_code=404, detail="Deck not found")
    return artifact


@router.get("/decks/{artifact_id}")
async def get_deck_by_id(
    artifact: Artifact = Depends(_get_owned_deck), db: AsyncSession = Depends(get_db)
) -> DeckOut:
    return await _deck_out(db, artifact)


@router.post(
    "/modules/{module_id}/flashcards/generate", dependencies=[Depends(require_csrf)]
)
async def generate_flashcards(
    data: GenerateCardsIn,
    module: Module = Depends(get_owned_module),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> JobRef:
    count = 0 if data.count == 0 else max(4, min(60, data.count))
    await _validate_scope(db, module.id, data.document_ids, data.note_ids)
    instructions = (data.instructions or "").strip()[:2000] or None
    chunk_ids = (
        await _focus_chunk_ids(db, [module.id], instructions, data.document_ids)
        if instructions
        else None
    )
    job = await _enqueue_generation(
        db,
        user,
        module,
        "generate_flashcards",
        GENERATE_FLASHCARDS_TASK,
        module_id=module.id,
        count=count,
        document_ids=data.document_ids,
        note_ids=data.note_ids,
        instructions=instructions,
        mode=data.mode,
        chunk_ids=chunk_ids,
    )
    return JobRef(job_id=job.id)


async def _get_owned_card(
    card_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> Flashcard:
    card = (
        await db.execute(
            select(Flashcard)
            .join(Artifact, Artifact.id == Flashcard.artifact_id)
            .join(Module, Module.id == Artifact.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(Flashcard.id == card_id, Course.user_id == user.id)
        )
    ).scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


@router.patch("/flashcards/{card_id}", dependencies=[Depends(require_csrf)])
async def patch_card(
    data: CardPatch,
    card: Flashcard = Depends(_get_owned_card),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rewrote = (data.front is not None and data.front != card.front) or (
        data.back is not None and data.back != card.back
    )
    if rewrote:
        # `edited` alone says a card was rewritten but not what it replaced,
        # and the original is overwritten a line below. Keep the pair.
        db.add(
            AIFeedback(
                kind=AIFeedbackKind.card_edited,
                artifact_id=card.artifact_id,
                flashcard_id=card.id,
                rejected={"front": card.front, "back": card.back},
                preferred={
                    "front": data.front if data.front is not None else card.front,
                    "back": data.back if data.back is not None else card.back,
                },
            )
        )
    if data.front is not None:
        card.front = data.front
        card.edited = True
    if data.back is not None:
        card.back = data.back
        card.edited = True
    if data.status is not None:
        card.status = data.status
    await db.commit()
    return {"ok": True}


@router.delete("/flashcards/{card_id}", dependencies=[Depends(require_csrf)])
async def delete_card(
    card: Flashcard = Depends(_get_owned_card), db: AsyncSession = Depends(get_db)
) -> dict:
    await db.delete(card)
    await db.commit()
    return {"ok": True}


class CardCreate(BaseModel):
    front: str
    back: str


async def _insert_card(db: AsyncSession, artifact_id: int, front: str, back: str) -> CardOut:
    """No CardReview row is needed — a card without one is treated as due, and
    the row is created on its first rating."""
    next_ord = (
        await db.execute(
            select(func.coalesce(func.max(Flashcard.ord), -1) + 1).where(
                Flashcard.artifact_id == artifact_id
            )
        )
    ).scalar_one()
    card = Flashcard(
        artifact_id=artifact_id,
        ord=next_ord,
        front=front,
        back=back,
        edited=True,  # user-authored
        status=FlashcardStatus.active,
    )
    db.add(card)
    await db.commit()
    await db.refresh(card)
    return CardOut(
        id=card.id,
        front=card.front,
        back=card.back,
        status=card.status,
        edited=card.edited,
        citations=[],
    )


@router.post(
    "/modules/{module_id}/flashcards/cards", dependencies=[Depends(require_csrf)]
)
async def add_card(
    data: CardCreate,
    module: Module = Depends(get_owned_module),
    db: AsyncSession = Depends(get_db),
) -> CardOut:
    """Manually add a card to the module's review deck (creating a manual deck
    if the module has none)."""
    front = data.front.strip()
    back = data.back.strip()
    if not front or not back:
        raise HTTPException(status_code=422, detail="Front and back are required")
    artifact = await _review_deck(db, module.id)
    if artifact is None:
        artifact = Artifact(
            module_id=module.id,
            artifact_type=ArtifactType.flashcard_deck,
            scope_module_ids=[module.id],
            title=f"Flashcards — {module.title}",
            content={},
            model_name="manual",
            prompt_version="manual",
            source_chunk_ids=[],
            source_fingerprint="",
            module_version_at_gen=module.content_version,
            review_enabled=True,
        )
        db.add(artifact)
        await db.flush()
    return await _insert_card(db, artifact.id, front, back)


@router.post("/artifacts/{artifact_id}/cards", dependencies=[Depends(require_csrf)])
async def add_card_to_deck(
    data: CardCreate,
    artifact: Artifact = Depends(_get_owned_deck),
    db: AsyncSession = Depends(get_db),
) -> CardOut:
    """Manually add a card to a specific deck."""
    front = data.front.strip()
    back = data.back.strip()
    if not front or not back:
        raise HTTPException(status_code=422, detail="Front and back are required")
    return await _insert_card(db, artifact.id, front, back)


async def _apkg_response(
    db: AsyncSession, artifact: Artifact, *, include_deck_title: bool
) -> Response:
    from manabi_server.export.anki_export import build_apkg

    cards = (
        (
            await db.execute(
                select(Flashcard)
                .where(
                    Flashcard.artifact_id == artifact.id,
                    Flashcard.status == FlashcardStatus.active,
                )
                .order_by(Flashcard.ord, Flashcard.id)
            )
        )
        .scalars()
        .all()
    )
    citations = await _citations_by_ref(db, artifact.id)
    module = (
        await db.execute(select(Module).where(Module.id == artifact.module_id))
    ).scalar_one()
    course = (
        await db.execute(select(Course).where(Course.id == module.course_id))
    ).scalar_one()

    def source_label(ord_: int) -> str:
        cites = citations.get(f"card:{ord_}", [])
        return "; ".join(
            f"{c.document_title} · p. {c.page_start}"
            + (f"–{c.page_end}" if c.page_end and c.page_end != c.page_start else "")
            for c in cites
        )

    # The module route keeps its historical Anki deck name so re-exports keep
    # landing in the same Anki deck; per-deck exports get their own name.
    deck_name = f"{course.code}::{module.title}"
    if include_deck_title:
        deck_name += f"::{artifact.title}"
    data = build_apkg(
        deck_name=deck_name,
        cards=[(c.id, c.front, c.back, source_label(c.ord)) for c in cards],
    )
    safe = deck_name.replace("::", "_").replace(" ", "_")
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe}.apkg"'},
    )


@router.get("/modules/{module_id}/flashcards/export.apkg")
async def export_deck(
    module: Module = Depends(get_owned_module), db: AsyncSession = Depends(get_db)
) -> Response:
    artifact = await _review_deck(db, module.id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="No flashcards to export yet")
    return await _apkg_response(db, artifact, include_deck_title=False)


@router.get("/artifacts/{artifact_id}/export.apkg")
async def export_deck_by_id(
    artifact: Artifact = Depends(_get_owned_deck), db: AsyncSession = Depends(get_db)
) -> Response:
    return await _apkg_response(db, artifact, include_deck_title=True)


# ── Quizzes ───────────────────────────────────────────────────────────────


class QuizConfigIn(BaseModel):
    module_ids: list[int]
    types: list[str] = ["mcq", "tf", "short"]
    count: int = 10
    # Document/note scoping is only meaningful for a single-module quiz (422
    # otherwise); None = whole module of that kind.
    document_ids: list[int] | None = None
    note_ids: list[int] | None = None
    instructions: str | None = None
    mode: Literal["sources", "exercise"] = "sources"


class QuestionOut(BaseModel):
    id: int
    ord: int
    qtype: str
    prompt: str
    options: list | None
    answer: dict
    explanation: str | None
    citations: list[CitationOut]


class QuizOut(BaseModel):
    artifact_id: int
    title: str
    model_name: str
    generated_at: datetime
    scope_module_ids: list[int]
    generation_mode: str | None
    instructions: str | None
    questions: list[QuestionOut]


class QuizListItem(BaseModel):
    artifact_id: int
    title: str
    generated_at: datetime
    question_count: int
    attempt_count: int
    best_score: float | None
    generation_mode: str | None = None


class AttemptIn(BaseModel):
    responses: dict
    score: float | None = None
    finished: bool = False


@router.post("/quizzes", dependencies=[Depends(require_csrf)])
async def create_quiz(
    config: QuizConfigIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> JobRef:
    if not config.module_ids:
        raise HTTPException(status_code=422, detail="Select at least one module")
    # ownership check on every module in scope
    owned = (
        (
            await db.execute(
                select(Module.id)
                .join(Course, Course.id == Module.course_id)
                .where(Module.id.in_(config.module_ids), Course.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    if set(owned) != set(config.module_ids):
        raise HTTPException(status_code=404, detail="Module not found")
    anchor = (
        await db.execute(select(Module).where(Module.id == config.module_ids[0]))
    ).scalar_one()
    types = [t for t in config.types if t in QUIZ_TYPES] or ["mcq"]
    if (config.document_ids is not None or config.note_ids is not None) and len(
        config.module_ids
    ) != 1:
        raise HTTPException(
            status_code=422,
            detail="Document/note scoping requires exactly one module",
        )
    if len(config.module_ids) == 1:
        await _validate_scope(
            db, config.module_ids[0], config.document_ids, config.note_ids
        )
    instructions = (config.instructions or "").strip()[:2000] or None
    chunk_ids = (
        await _focus_chunk_ids(
            db, config.module_ids, instructions, config.document_ids
        )
        if instructions
        else None
    )
    job = await _enqueue_generation(
        db,
        user,
        anchor,
        "generate_quiz",
        GENERATE_QUIZ_TASK,
        module_ids=config.module_ids,
        types=types,
        count=max(3, min(30, config.count)),
        document_ids=config.document_ids,
        note_ids=config.note_ids,
        instructions=instructions,
        mode=config.mode,
        chunk_ids=chunk_ids,
    )
    return JobRef(job_id=job.id)


@router.get("/modules/{module_id}/quizzes")
async def list_quizzes(
    module: Module = Depends(get_owned_module), db: AsyncSession = Depends(get_db)
) -> list[QuizListItem]:
    artifacts = (
        (
            await db.execute(
                select(Artifact)
                .where(
                    Artifact.module_id == module.id,
                    Artifact.artifact_type == ArtifactType.quiz,
                )
                .order_by(Artifact.id.desc())
            )
        )
        .scalars()
        .all()
    )
    out = []
    for a in artifacts:
        questions = (
            await db.execute(
                select(QuizQuestion.id).where(QuizQuestion.artifact_id == a.id)
            )
        ).all()
        attempts = (
            (
                await db.execute(
                    select(QuizAttempt).where(
                        QuizAttempt.artifact_id == a.id,
                        QuizAttempt.finished_at.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        out.append(
            QuizListItem(
                artifact_id=a.id,
                title=a.title,
                generated_at=a.created_at,
                question_count=len(questions),
                attempt_count=len(attempts),
                best_score=max((x.score for x in attempts if x.score is not None), default=None),
                generation_mode=a.generation_mode,
            )
        )
    return out


async def _get_owned_quiz(
    artifact_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> Artifact:
    artifact = (
        await db.execute(
            select(Artifact)
            .join(Module, Module.id == Artifact.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(
                Artifact.id == artifact_id,
                Artifact.artifact_type == ArtifactType.quiz,
                Course.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if artifact is None:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return artifact


@router.get("/quizzes/{artifact_id}")
async def get_quiz(
    artifact: Artifact = Depends(_get_owned_quiz), db: AsyncSession = Depends(get_db)
) -> QuizOut:
    questions = (
        (
            await db.execute(
                select(QuizQuestion)
                .where(QuizQuestion.artifact_id == artifact.id)
                .order_by(QuizQuestion.ord)
            )
        )
        .scalars()
        .all()
    )
    citations = await _citations_by_ref(db, artifact.id)
    return QuizOut(
        artifact_id=artifact.id,
        title=artifact.title,
        model_name=artifact.model_name,
        generated_at=artifact.created_at,
        scope_module_ids=[int(m) for m in artifact.scope_module_ids],
        generation_mode=artifact.generation_mode,
        instructions=artifact.instructions,
        questions=[
            QuestionOut(
                id=q.id,
                ord=q.ord,
                qtype=q.qtype,
                prompt=q.prompt,
                options=q.options,
                answer=q.answer,
                explanation=q.explanation,
                citations=citations.get(f"q:{q.ord}", []),
            )
            for q in questions
        ],
    )


async def _get_owned_question(
    question_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> QuizQuestion:
    q = (
        await db.execute(
            select(QuizQuestion)
            .join(Artifact, Artifact.id == QuizQuestion.artifact_id)
            .join(Module, Module.id == Artifact.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(QuizQuestion.id == question_id, Course.user_id == user.id)
        )
    ).scalar_one_or_none()
    if q is None:
        raise HTTPException(status_code=404, detail="Question not found")
    return q


async def _enqueue_question_job(
    db: AsyncSession,
    user: User,
    question: QuizQuestion,
    job_type: str,
    task_name: str,
    **task_kwargs,
) -> Job:
    """Per-question GPU job (verify/regenerate) with the same payload-aware
    duplicate-proofing as full generations."""
    from manabi_core.models import JobStatus

    artifact = (
        await db.execute(select(Artifact).where(Artifact.id == question.artifact_id))
    ).scalar_one()
    inflight = (
        (
            await db.execute(
                select(Job).where(
                    Job.job_type == job_type,
                    Job.status.in_([JobStatus.queued, JobStatus.running]),
                )
            )
        )
        .scalars()
        .all()
    )
    existing = _matching_inflight(list(inflight), task_kwargs)
    if existing is not None:
        return existing
    job = Job(
        user_id=user.id,
        job_type=job_type,
        queue=JobQueue.gpu,
        payload=task_kwargs,
        module_id=artifact.module_id,
    )
    db.add(job)
    await db.flush()
    job.procrastinate_job_id = await defer_task(
        task_name, "gpu", job_id=job.id, **task_kwargs
    )
    await db.commit()
    return job


class ChallengeIn(BaseModel):
    user_answer: str = ""


@router.post(
    "/quiz-questions/{question_id}/challenge", dependencies=[Depends(require_csrf)]
)
async def challenge_question(
    data: ChallengeIn,
    question: QuizQuestion = Depends(_get_owned_question),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> JobRef:
    """Student disputes the stored answer — an adjudication job re-checks it
    against the question's cited sources and reports who is right."""
    job = await _enqueue_question_job(
        db,
        user,
        question,
        "verify_question",
        VERIFY_QUESTION_TASK,
        question_id=question.id,
        user_answer=(data.user_answer or "").strip()[:4000],
    )
    return JobRef(job_id=job.id)


@router.post(
    "/quiz-questions/{question_id}/regenerate", dependencies=[Depends(require_csrf)]
)
async def regenerate_quiz_question(
    question: QuizQuestion = Depends(_get_owned_question),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> JobRef:
    """Replace this question with a freshly generated one (same type, same
    quiz scope/mode)."""
    job = await _enqueue_question_job(
        db,
        user,
        question,
        "regenerate_question",
        REGENERATE_QUESTION_TASK,
        question_id=question.id,
    )
    return JobRef(job_id=job.id)


@router.post("/quizzes/{artifact_id}/attempts", dependencies=[Depends(require_csrf)])
async def start_attempt(
    artifact: Artifact = Depends(_get_owned_quiz), db: AsyncSession = Depends(get_db)
) -> dict:
    attempt = QuizAttempt(artifact_id=artifact.id)
    db.add(attempt)
    await db.commit()
    return {"attempt_id": attempt.id}


@router.patch("/quiz-attempts/{attempt_id}", dependencies=[Depends(require_csrf)])
async def update_attempt(
    attempt_id: int,
    data: AttemptIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    attempt = (
        await db.execute(
            select(QuizAttempt)
            .join(Artifact, Artifact.id == QuizAttempt.artifact_id)
            .join(Module, Module.id == Artifact.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(QuizAttempt.id == attempt_id, Course.user_id == user.id)
        )
    ).scalar_one_or_none()
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found")
    attempt.responses = data.responses
    if data.score is not None:
        attempt.score = data.score
    if data.finished:
        attempt.finished_at = datetime.now(UTC)
    await db.commit()
    return {"ok": True}


# ── Teacher lectures ──────────────────────────────────────────────────────


class LectureSegmentOut(BaseModel):
    index: int
    title: str
    display_text: str
    spoken_text: str
    checkpoint: dict | None
    audio_ready: bool
    audio_id: int | None  # changes on re-synthesis — cache-buster for the URL
    duration_ms: int | None
    citations: list[CitationOut]


class LectureOut(BaseModel):
    artifact_id: int
    title: str
    mode: str
    model_name: str
    generated_at: datetime
    staleness: str
    voice_available: bool
    audio_job_active: bool
    segments: list[LectureSegmentOut]


class TeachIn(BaseModel):
    mode: str = "standard"


async def _tts_available(db: AsyncSession) -> bool:
    from manabi_core.models import AINodeHeartbeat

    hb = (
        await db.execute(
            select(AINodeHeartbeat)
            .order_by(AINodeHeartbeat.last_seen_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return bool(hb and (hb.gpu_info or {}).get("tts"))


@router.get("/modules/{module_id}/lecture")
async def get_lecture(
    module: Module = Depends(get_owned_module), db: AsyncSession = Depends(get_db)
) -> LectureOut | None:
    from manabi_core.models import JobStatus

    artifact = await _latest_artifact(db, module.id, ArtifactType.lecture)
    if artifact is None:
        return None
    citations = await _citations_by_ref(db, artifact.id)
    audio_rows = {
        r.segment_index: r
        for r in (
            await db.execute(
                select(LectureAudio).where(LectureAudio.artifact_id == artifact.id)
            )
        ).scalars()
    }
    audio_job = (
        await db.execute(
            select(Job)
            .where(
                Job.module_id == module.id,
                Job.job_type == "synthesize_lecture",
                Job.status.in_([JobStatus.queued, JobStatus.running]),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    segments = []
    for i, seg in enumerate((artifact.content or {}).get("segments", [])):
        row = audio_rows.get(i)
        segments.append(
            LectureSegmentOut(
                index=i,
                title=seg.get("title", f"Segment {i + 1}"),
                display_text=seg.get("display_text", ""),
                spoken_text=seg.get("spoken_text", ""),
                checkpoint=seg.get("checkpoint"),
                audio_ready=row is not None,
                audio_id=row.id if row else None,
                duration_ms=row.duration_ms if row else None,
                citations=citations.get(f"seg:{i}", []),
            )
        )
    return LectureOut(
        artifact_id=artifact.id,
        title=artifact.title or "Lecture",
        mode=(artifact.content or {}).get("mode", "standard"),
        model_name=artifact.model_name or "",
        generated_at=artifact.created_at,
        staleness=await _staleness(db, artifact),
        voice_available=await _tts_available(db),
        audio_job_active=audio_job is not None,
        segments=segments,
    )


@router.post(
    "/modules/{module_id}/lecture/generate", dependencies=[Depends(require_csrf)]
)
async def generate_lecture(
    data: TeachIn,
    module: Module = Depends(get_owned_module),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    mode = data.mode if data.mode in ("standard", "cram", "deep_dive") else "standard"
    job = await _enqueue_generation(
        db,
        user,
        module,
        "teach_module",
        TEACH_MODULE_TASK,
        module_id=module.id,
        mode=mode,
    )
    return {"job_id": job.id}


@router.post(
    "/modules/{module_id}/lecture/remediate", dependencies=[Depends(require_csrf)]
)
async def remediate_lecture(
    module: Module = Depends(get_owned_module),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Re-teach the chunks cited by checkpoints the student got wrong."""
    artifact = await _latest_artifact(db, module.id, ArtifactType.lecture)
    if artifact is None:
        raise HTTPException(status_code=404, detail="No lecture yet")
    missed = (
        (
            await db.execute(
                select(LectureCheckpointResult.segment_index)
                .where(
                    LectureCheckpointResult.artifact_id == artifact.id,
                    LectureCheckpointResult.correct.is_(False),
                )
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    if not missed:
        raise HTTPException(status_code=409, detail="No missed checkpoints to review")
    segs = (artifact.content or {}).get("segments", [])
    chunk_ids = sorted(
        {cid for i in missed if i < len(segs) for cid in segs[i].get("chunk_ids", [])}
    )
    if not chunk_ids:
        raise HTTPException(status_code=409, detail="Missed segments have no sources")
    job = await _enqueue_generation(
        db,
        user,
        module,
        "teach_module",
        TEACH_MODULE_TASK,
        module_id=module.id,
        mode="remediation",
        chunk_ids=chunk_ids,
    )
    return {"job_id": job.id, "chunks": len(chunk_ids)}


class CheckpointIn(BaseModel):
    correct: bool


@router.post(
    "/artifacts/{artifact_id}/checkpoints/{segment_index}",
    dependencies=[Depends(require_csrf)],
)
async def record_checkpoint(
    segment_index: int,
    data: CheckpointIn,
    artifact: Artifact = Depends(_get_owned_artifact),
    db: AsyncSession = Depends(get_db),
) -> dict:
    db.add(
        LectureCheckpointResult(
            artifact_id=artifact.id, segment_index=segment_index, correct=data.correct
        )
    )
    await db.commit()
    return {"ok": True}


@router.post(
    "/artifacts/{artifact_id}/audio/generate", dependencies=[Depends(require_csrf)]
)
async def generate_lecture_audio(
    artifact: Artifact = Depends(_get_owned_artifact),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Backfill/re-run voice synthesis for an existing lecture."""
    from manabi_core.models import JobStatus

    from manabi_server.jobs.queue import SYNTHESIZE_LECTURE_TASK

    existing = (
        await db.execute(
            select(Job)
            .where(
                Job.module_id == artifact.module_id,
                Job.job_type == "synthesize_lecture",
                Job.status.in_([JobStatus.queued, JobStatus.running]),
            )
            .order_by(Job.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {"job_id": existing.id}
    job = Job(
        user_id=user.id,
        job_type="synthesize_lecture",
        queue=JobQueue.gpu,
        module_id=artifact.module_id,
    )
    db.add(job)
    await db.flush()
    job.procrastinate_job_id = await defer_task(
        SYNTHESIZE_LECTURE_TASK, "gpu", job_id=job.id, artifact_id=artifact.id
    )
    await db.commit()
    return {"job_id": job.id}


@router.get("/artifacts/{artifact_id}/audio/{segment_index}")
async def get_lecture_audio(
    segment_index: int,
    artifact: Artifact = Depends(_get_owned_artifact),
    db: AsyncSession = Depends(get_db),
) -> Response:
    row = (
        await db.execute(
            select(LectureAudio).where(
                LectureAudio.artifact_id == artifact.id,
                LectureAudio.segment_index == segment_index,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Audio not synthesized yet")
    return Response(
        content=row.audio,
        media_type=row.mime,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )
