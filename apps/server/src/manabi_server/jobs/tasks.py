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
            if str(answer.get("verified", "")).startswith(("executed", "rejected")):
                continue  # already settled by an earlier pass
            chk = check_code_question(q.qtype, q.prompt or "", q.options, answer)
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
    if reexplain:
        try:
            defer_task_sync(
                REEXPLAIN_QUESTIONS_TASK, "gpu", artifact_id=artifact_id, question_ids=reexplain
            )
        except Exception:  # noqa: BLE001 — the key is fixed; the prose can wait
            log.exception("could not queue re-explanations for quiz %s", artifact_id)
    return counts["corrected"] + counts["converted"] + counts["rejected"]
