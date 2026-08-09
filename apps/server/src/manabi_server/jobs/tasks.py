"""CPU-queue task implementations (run by `python -m manabi_server.worker`).

Tasks are SYNC on purpose: document processing is heavy blocking work, and
Procrastinate runs sync tasks in a worker thread, keeping the async worker
loop responsive. DB access uses a sync engine for the same reason.
"""

import procrastinate
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from manabi_server.config import get_settings
from manabi_server.jobs.queue import (
    EXTRACT_TEXT_HTML_TASK,
    PROCESS_DOCUMENT_TASK,
    SCORE_SUPPORT_TASK,
)


def _conninfo() -> str:
    return get_settings().database_url_sync.replace("postgresql+psycopg", "postgresql")


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
