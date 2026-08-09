"""AI artifact endpoints: summaries, flashcard decks, quizzes.

Generation is asynchronous: POST .../generate creates a Job on the gpu queue
and returns it; the worker on the AI node persists the artifact. Staleness is
computed at read time by comparing the artifact's source fingerprint against
the module's current AI-eligible chunk set.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from manabi_core.models import (
    Artifact,
    ArtifactType,
    Citation,
    Course,
    Flashcard,
    FlashcardStatus,
    Job,
    JobQueue,
    Module,
    QuizAttempt,
    QuizQuestion,
    User,
)
from manabi_core.retrieval import load_context_chunks, source_fingerprint
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.api.modules import get_owned_module
from manabi_server.db import get_db
from manabi_server.jobs.queue import (
    GENERATE_FLASHCARDS_TASK,
    GENERATE_QUIZ_TASK,
    GENERATE_SUMMARY_TASK,
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
    chunks = await load_context_chunks(db, [int(m) for m in artifact.scope_module_ids])
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


async def _enqueue_generation(
    db: AsyncSession,
    user: User,
    module: Module,
    job_type: str,
    task_name: str,
    **task_kwargs,
) -> Job:
    # Duplicate-proof: an identical generation already in flight is returned
    # instead of queued twice.
    from manabi_core.models import JobStatus

    existing = (
        await db.execute(
            select(Job).where(
                Job.module_id == module.id,
                Job.job_type == job_type,
                Job.status.in_([JobStatus.queued, JobStatus.running]),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    chunks = await load_context_chunks(db, [module.id])
    if not chunks:
        raise HTTPException(
            status_code=409,
            detail="No AI-eligible material in this module — upload documents "
            "(or re-include them for AI) first",
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
            module_id=module.id, count=max(4, min(30, config.flashcards_count)),
        )
        jobs["flashcards"] = job.id
    if config.quiz_count:
        types = [t for t in config.quiz_types if t in ("mcq", "tf", "short")] or ["mcq"]
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
        "citations": {k: [c.model_dump() for c in v] for k, v in citations.items()},
    }
    if artifact.artifact_type == ArtifactType.summary:
        base["sections"] = artifact.content.get("sections", [])
        base["key_terms"] = artifact.content.get("key_terms", [])
        base["acronyms"] = artifact.content.get("acronyms", [])
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
                        ["generate_summary", "generate_flashcards", "generate_quiz"]
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
    sections: list[dict]
    key_terms: list[dict] = []
    acronyms: list[dict] = []
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
        sections=artifact.content.get("sections", []),
        key_terms=artifact.content.get("key_terms", []),
        acronyms=artifact.content.get("acronyms", []),
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
    model_name: str
    generated_at: datetime
    staleness: str
    cards: list[CardOut]


class GenerateCardsIn(BaseModel):
    count: int = 12


class CardPatch(BaseModel):
    front: str | None = None
    back: str | None = None
    status: FlashcardStatus | None = None


@router.get("/modules/{module_id}/flashcards")
async def get_deck(
    module: Module = Depends(get_owned_module), db: AsyncSession = Depends(get_db)
) -> DeckOut | None:
    artifact = await _latest_artifact(db, module.id, ArtifactType.flashcard_deck)
    if artifact is None:
        return None
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
        model_name=artifact.model_name,
        generated_at=artifact.created_at,
        staleness=await _staleness(db, artifact),
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


@router.post(
    "/modules/{module_id}/flashcards/generate", dependencies=[Depends(require_csrf)]
)
async def generate_flashcards(
    data: GenerateCardsIn,
    module: Module = Depends(get_owned_module),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> JobRef:
    count = max(4, min(30, data.count))
    job = await _enqueue_generation(
        db,
        user,
        module,
        "generate_flashcards",
        GENERATE_FLASHCARDS_TASK,
        module_id=module.id,
        count=count,
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


@router.get("/modules/{module_id}/flashcards/export.apkg")
async def export_deck(
    module: Module = Depends(get_owned_module), db: AsyncSession = Depends(get_db)
) -> Response:
    from manabi_server.export.anki_export import build_apkg

    artifact = await _latest_artifact(db, module.id, ArtifactType.flashcard_deck)
    if artifact is None:
        raise HTTPException(status_code=404, detail="No flashcards to export yet")
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

    data = build_apkg(
        deck_name=f"{course.code}::{module.title}",
        cards=[(c.id, c.front, c.back, source_label(c.ord)) for c in cards],
    )
    safe = f"{course.code}_{module.title}".replace(" ", "_")
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe}.apkg"'},
    )


# ── Quizzes ───────────────────────────────────────────────────────────────


class QuizConfigIn(BaseModel):
    module_ids: list[int]
    types: list[str] = ["mcq", "tf", "short"]
    count: int = 10


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
    questions: list[QuestionOut]


class QuizListItem(BaseModel):
    artifact_id: int
    title: str
    generated_at: datetime
    question_count: int
    attempt_count: int
    best_score: float | None


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
    types = [t for t in config.types if t in ("mcq", "tf", "short")] or ["mcq"]
    job = await _enqueue_generation(
        db,
        user,
        anchor,
        "generate_quiz",
        GENERATE_QUIZ_TASK,
        module_ids=config.module_ids,
        types=types,
        count=max(3, min(30, config.count)),
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
