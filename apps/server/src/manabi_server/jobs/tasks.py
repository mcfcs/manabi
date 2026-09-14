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
    """Run the code in every `output` question and correct the ones that lie.

    Models are specifically unreliable here: asked what `sentence + 5` prints
    for "the quick brown fox", qwen3.5:27b named index 5 ('u') correctly in its
    own explanation and then answered "quick brown fox" — the substring from
    index 4. Compiling the same code answers "uick brown fox" every time.

    A question whose code will not compile, or whose language we cannot run, is
    left exactly as the model wrote it; only a *successful* run overrules it.
    Returns how many answers were corrected.
    """
    from manabi_core.models import AIFeedback, AIFeedbackKind, Artifact, QuizQuestion
    from sqlalchemy import select

    from manabi_server.processing.code_exec import (
        execute,
        extract_snippet,
        normalize_output,
        outputs_match,
        printed_anything,
    )

    corrected = agreed = unverified = 0
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
                    QuizQuestion.qtype == "output",
                )
            )
            .scalars()
            .all()
        )
        for q in questions:
            answer = dict(q.answer or {})
            snippet = extract_snippet(q.prompt or "")
            if snippet is None:
                # Record WHY it could not be checked, rather than skipping in
                # silence. `output` is graded by exact string equality with no
                # self-grade override, so an unverified key marks a correct
                # student wrong — the client falls back to self-grading unless
                # this says "executed".
                q.answer = {**answer, "verified": "unverifiable:no runnable code block"}
                unverified += 1
                continue
            result = execute(snippet)
            if not result.ok:
                q.answer = {**answer, "verified": f"unverifiable:{result.error}"}
                unverified += 1
                continue
            if not printed_anything(result):
                # Ran clean but printed nothing: the question is about something
                # other than stdout, so "" is not the answer — leave the model's.
                q.answer = {**answer, "verified": "unverifiable:program prints nothing"}
                unverified += 1
                continue
            claimed = answer.get("text", "")
            if outputs_match(claimed, result.stdout):
                q.answer = {**answer, "verified": "executed"}
                agreed += 1
                continue

            real = normalize_output(result.stdout)
            db.add(
                AIFeedback(
                    kind=AIFeedbackKind.answer_disputed,
                    artifact_id=artifact_id,
                    question_id=q.id,
                    rejected={"answer": q.answer, "explanation": q.explanation},
                    preferred={
                        "answer": {"kind": "output", "text": real},
                        "verified_by": f"executed ({snippet.lang})",
                    },
                    model_name=artifact.model_name,
                    prompt_version=artifact.prompt_version,
                )
            )
            q.answer = {"kind": "output", "text": real, "verified": "executed"}
            note = "Verified by running the code."
            q.explanation = f"{(q.explanation or '').rstrip()}\n\n{note}".strip()
            corrected += 1
        db.commit()
        log.info(
            "quiz %s outputs: %d agreed, %d corrected, %d unverifiable",
            artifact_id,
            agreed,
            corrected,
            unverified,
        )
    return corrected
