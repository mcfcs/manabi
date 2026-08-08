"""Embedding via the app server's local Ollama (sync — called from CPU-worker
task threads and, for query embedding, via asyncio.to_thread)."""

import httpx

from manabi_server.config import get_settings

# Qwen3 embeddings are instruction-tuned: queries get an instruction prefix,
# documents are embedded raw (asymmetric retrieval).
_QUERY_INSTRUCT = (
    "Instruct: Given a study question, retrieve relevant course material "
    "passages\nQuery: "
)

BATCH_SIZE = 16


def embed_texts(texts: list[str], *, is_query: bool = False) -> list[list[float]]:
    settings = get_settings()
    inputs = [(_QUERY_INSTRUCT + t) if is_query else t for t in texts]
    vectors: list[list[float]] = []
    with httpx.Client(timeout=120) as client:
        for start in range(0, len(inputs), BATCH_SIZE):
            batch = inputs[start : start + BATCH_SIZE]
            r = client.post(
                f"{settings.embedding_ollama_url}/api/embed",
                json={"model": settings.embedding_model, "input": batch},
            )
            r.raise_for_status()
            vectors.extend(r.json()["embeddings"])
    return vectors


def embed_missing_chunks_sync(db) -> int:
    """Idempotent backfill: embed every chunk lacking an embedding row."""
    from manabi_core.models import Chunk, ChunkEmbedding
    from sqlalchemy import select

    settings = get_settings()
    missing = (
        db.execute(
            select(Chunk.id, Chunk.heading_path, Chunk.text)
            .outerjoin(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
            .where(ChunkEmbedding.chunk_id.is_(None))
            .order_by(Chunk.id)
        )
    ).all()
    if not missing:
        return 0
    texts = [f"{h}\n{t}" if h else t for _, h, t in missing]
    vectors = embed_texts(texts)
    for (chunk_id, _, _), vec in zip(missing, vectors, strict=True):
        db.add(
            ChunkEmbedding(
                chunk_id=chunk_id, embedding=vec, embedding_model=settings.embedding_model
            )
        )
    db.commit()
    return len(missing)
