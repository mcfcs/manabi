"""CPU-queue task implementations (run by `python -m manabi_server.worker`).

Tasks are SYNC on purpose: document processing is heavy blocking work, and
Procrastinate runs sync tasks in a worker thread, keeping the async worker
loop responsive. DB access uses a sync engine for the same reason.
"""

import logging

import procrastinate
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from manabi_server.config import get_settings
from manabi_server.jobs.queue import (
    EXTRACT_TEXT_HTML_TASK,
    PROCESS_DOCUMENT_TASK,
    SCORE_SUPPORT_TASK,
    VERIFY_CARD_OUTPUTS_TASK,
    VERIFY_OUTPUTS_TASK,
)


def _conninfo() -> str:
    return get_settings().database_url_sync.replace("postgresql+psycopg", "postgresql")


log = logging.getLogger("manabi.tasks")

app = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=_conninfo()))

_session_factory: sessionmaker | None = None


def db_session() -> Session:
    global _session_factory
    if _session_factory is None:
        engine = create_engine(get_settings().database_url_sync, pool_size=2)
        _session_factory = sessionmaker(engine)
    return _session_factory()


@app.task(name=PROCESS_DOCUMENT_TASK, queue="cpu", retry=3)
def process_document(document_id: int, job_id: int | None = None) -> None:
    from manabi_server.processing.pipeline import run_pipeline

    with db_session() as db:
        run_pipeline(db, document_id, job_id)


@app.task(name=EXTRACT_TEXT_HTML_TASK, queue="cpu", retry=2)
def extract_text_html(document_id: int) -> None:
    """Lightweight backfill: per-page rich text without re-running Docling."""
    from manabi_server.processing.text_html import build_text_html

    with db_session() as db:
        build_text_html(db, document_id)


@app.task(name=SCORE_SUPPORT_TASK, queue="cpu", retry=2)
def score_support(artifact_id: int) -> None:
    """Post-generation validation layer: cosine(claim text, cited chunk)
    using the local embedding model. Flags weak citations — never deletes."""
    import numpy as np
    from manabi_core.models import Chunk, ChunkEmbedding, Citation, CitationStatus
    from sqlalchemy import select

    from manabi_server.config import get_settings
    from manabi_server.processing.embedding import embed_texts

    threshold = get_settings().support_weak_threshold
    with db_session() as db:
        rows = (
            db.execute(
                select(Citation, ChunkEmbedding.embedding, Chunk.text)
                .join(Chunk, Chunk.id == Citation.chunk_id)
                .join(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
                .where(
                    Citation.artifact_id == artifact_id,
                    Citation.quote_excerpt.is_not(None),
                )
            )
        ).all()
        if not rows:
            return
        claim_vecs = embed_texts([c.quote_excerpt for c, _, _ in rows], is_query=True)
        for (citation, chunk_vec, _), claim_vec in zip(rows, claim_vecs, strict=True):
            a = np.asarray(claim_vec)
            b = np.asarray(chunk_vec, dtype=float)
            cos = float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))
            citation.support_score = round(cos, 4)
            if cos < threshold:
                citation.status = CitationStatus.weak
        db.commit()


MAX_REPLACEMENTS = 2  # per question: a topic that keeps producing UB gets dropped
# `verified` stamps a later pass must not touch (run, retired, or hand-checked).
SETTLED = ("executed", "rejected", "manual", "language-checked")


def _queue_replacements(db, artifact, question_ids: list[int]) -> int:
    """Ask the GPU for an in-place replacement of each retired question, so a
    quiz does not quietly come up short. The replacement is regenerated with
    the same type and scope and verified again; after MAX_REPLACEMENTS the
    question stays retired (the material keeps producing undefined code)."""
    from manabi_core.models import (
        AIFeedback,
        AIFeedbackKind,
        Course,
        Job,
        JobQueue,
        Module,
    )
    from sqlalchemy import func, select

    from manabi_server.jobs.queue import REGENERATE_QUESTION_TASK, defer_task_sync

    if not question_ids:
        return 0
    user_id = db.execute(
        select(Course.user_id)
        .join(Module, Module.course_id == Course.id)
        .where(Module.id == artifact.module_id)
    ).scalar_one_or_none()
    if user_id is None:
        return 0
    queued = 0
    for qid in question_ids:
        done = db.execute(
            select(func.count(AIFeedback.id)).where(
                AIFeedback.question_id == qid,
                AIFeedback.kind == AIFeedbackKind.question_regenerated,
            )
        ).scalar_one()
        if done >= MAX_REPLACEMENTS:
            continue
        job = Job(
            user_id=user_id,
            job_type="regenerate_question",
            queue=JobQueue.gpu,
            payload={"question_id": qid, "reason": "retired by the code check"},
            module_id=artifact.module_id,
        )
        db.add(job)
        db.flush()
        try:
            job.procrastinate_job_id = defer_task_sync(
                REGENERATE_QUESTION_TASK, "gpu", job_id=job.id, question_id=qid
            )
        except Exception:  # noqa: BLE001 — a missing replacement is not fatal
            log.exception("could not queue a replacement for question %s", qid)
            db.rollback()
            continue
        db.commit()
        queued += 1
    return queued


@app.task(name=VERIFY_CARD_OUTPUTS_TASK, queue="cpu", retry=1)
def verify_card_outputs(artifact_id: int) -> dict:
    """Run the program on every code-output flashcard. The run wins: a wrong
    back is replaced with what the program really prints, and a card whose
    code has no defined output, will not compile or cannot be run is removed
    (with its citations) rather than left to teach a guess."""
    from manabi_core.models import Citation, Flashcard
    from sqlalchemy import delete, select

    from manabi_server.processing.code_exec import check_code_question

    counts = {"agree": 0, "corrected": 0, "removed": 0}
    with db_session() as db:
        cards = (
            db.execute(select(Flashcard).where(Flashcard.artifact_id == artifact_id))
            .scalars()
            .all()
        )
        for card in cards:
            if "```" not in (card.front or "") or card.edited:
                continue
            try:
                chk = check_code_question(
                    "output", card.front, None, {"kind": "output", "text": card.back}
                )
            except Exception:  # noqa: BLE001 — one bad card must not sink the deck
                log.exception("code check crashed on card %s", card.id)
                continue
            if chk.status == "agree":
                counts["agree"] += 1
            elif chk.status == "corrected" and chk.answer:
                card.back = chk.answer["text"]
                counts["corrected"] += 1
            elif chk.status in ("rejected", "unverifiable", "converted"):
                db.execute(
                    delete(Citation).where(
                        Citation.artifact_id == artifact_id,
                        Citation.item_ref == f"card:{card.ord}",
                    )
                )
                db.delete(card)
                counts["removed"] += 1
        db.commit()
    log.info("card outputs for deck %s: %s", artifact_id, counts)
    return counts


@app.task(name=VERIFY_OUTPUTS_TASK, queue="cpu", retry=1)
def verify_quiz_outputs(artifact_id: int) -> int:
    """Run the code in every code question and correct the keys that lie.

    Models are specifically unreliable here: asked what `sentence + 5` prints
    for "the quick brown fox", qwen3.5:27b named index 5 ('u') correctly in its
    own explanation and then answered "quick brown fox" — the substring from
    index 4. Compiling the same code answers "uick brown fox" every time.

    Covers `output` questions, and `mcq`/`short` questions whose stem asks what
    code prints (an mcq key is moved to the option the program really prints;
    an mcq none of whose options is right becomes an `output` question). Code
    with no defined output (undefined behaviour, copy elision) is retired:
    `answer.verified = "rejected:…"` hides it from the quiz. Code that will not
    compile is left exactly as the model wrote it — only a successful, defined
    run overrules it. A corrected key leaves a walkthrough that argues for the
    old answer, so those questions are queued for a fresh explanation.
    Returns how many questions were changed (corrected, converted or retired).
    """
    from manabi_core.models import AIFeedback, AIFeedbackKind, Artifact, QuizQuestion
    from sqlalchemy import select

    from manabi_server.jobs.queue import REEXPLAIN_QUESTIONS_TASK, defer_task_sync
    from manabi_server.processing.code_exec import check_code_question, converted_prompt

    counts = {"agree": 0, "corrected": 0, "converted": 0, "rejected": 0, "unverifiable": 0}
    reexplain: list[int] = []
    retired: list[int] = []
    with db_session() as db:
        artifact = db.execute(
            select(Artifact).where(Artifact.id == artifact_id)
        ).scalar_one_or_none()
        if artifact is None:
            return 0
        questions = (
            db.execute(
                select(QuizQuestion).where(
                    QuizQuestion.artifact_id == artifact_id,
                    QuizQuestion.qtype.in_(("output", "mcq", "short")),
                )
            )
            .scalars()
            .all()
        )
        for q in questions:
            answer = dict(q.answer or {})
            if str(answer.get("verified", "")).startswith(SETTLED):
                continue  # already settled by an earlier pass
            try:
                chk = check_code_question(q.qtype, q.prompt or "", q.options, answer)
            except Exception:  # noqa: BLE001 — one bad question must not sink the quiz
                log.exception("code check crashed on question %s", q.id)
                continue
            if chk.status == "skip":
                continue
            counts[chk.status] = counts.get(chk.status, 0) + 1
            if chk.status == "unverifiable":
                # Record WHY it could not be checked, rather than skipping in
                # silence: an unverified `output` key self-grades on the client.
                if q.qtype == "output":
                    q.answer = {**answer, "verified": f"unverifiable:{chk.reason}"}
                continue
            if chk.status == "agree":
                q.answer = chk.answer
                continue
            if chk.status == "rejected":
                q.answer = {**answer, "verified": f"rejected:{chk.reason}"}
                db.add(
                    AIFeedback(
                        kind=AIFeedbackKind.answer_disputed,
                        artifact_id=artifact_id,
                        question_id=q.id,
                        rejected={"prompt": q.prompt, "answer": answer},
                        preferred={"retired": chk.reason, "verified_by": "compiler"},
                        model_name=artifact.model_name,
                        prompt_version=artifact.prompt_version,
                    )
                )
                retired.append(q.id)
                continue
            # corrected / converted: the run wins over the model.
            db.add(
                AIFeedback(
                    kind=AIFeedbackKind.answer_disputed,
                    artifact_id=artifact_id,
                    question_id=q.id,
                    rejected={
                        "qtype": q.qtype,
                        "options": q.options,
                        "answer": answer,
                        "explanation": q.explanation,
                    },
                    preferred={
                        "qtype": chk.qtype or q.qtype,
                        "answer": chk.answer,
                        "verified_by": "executed",
                    },
                    model_name=artifact.model_name,
                    prompt_version=artifact.prompt_version,
                )
            )
            if chk.status == "converted":
                q.qtype = "output"
                q.options = None
                q.prompt = converted_prompt(q.prompt or "")
            q.answer = chk.answer
            q.explanation = (
                f"The program prints:\n\n```\n{chk.real}\n```\n\n"
                "(The original walkthrough reached a different answer, so it was "
                "replaced; a corrected step-by-step explanation is being written.)"
            )
            reexplain.append(q.id)
        db.commit()
        log.info("quiz %s code checks: %s", artifact_id, counts)
        replace = _queue_replacements(db, artifact, retired)
    if replace:
        log.info("quiz %s: asked for %d replacement question(s)", artifact_id, replace)
    if reexplain:
        try:
            defer_task_sync(
                REEXPLAIN_QUESTIONS_TASK, "gpu", artifact_id=artifact_id, question_ids=reexplain
            )
        except Exception:  # noqa: BLE001 — the key is fixed; the prose can wait
            log.exception("could not queue re-explanations for quiz %s", artifact_id)
    return counts["corrected"] + counts["converted"] + counts["rejected"]
