"""Scoped chunk access — THE only code paths that read chunks for AI.

Module isolation and per-document AI exclusion are enforced HERE, in SQL:
- every function REQUIRES an explicit module_ids scope (no default),
- every query joins documents and filters ai_included AND NOT deleted.

Used by the app server (search, exports) and the GPU worker (generation
context). Do not query the chunks table anywhere else for AI purposes.
"""

import hashlib
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class ScopedChunk:
    id: int
    module_id: int
    document_id: int
    document_title: str
    page_start: int
    page_end: int
    heading_path: str | None
    text: str
    token_count: int
    content_hash: str


_SCOPE_FILTER = """
    JOIN documents d ON d.id = c.document_id
    WHERE c.module_id = ANY(:module_ids)
      AND d.ai_included
      AND d.deleted_at IS NULL
"""


async def load_context_chunks(
    db: AsyncSession, module_ids: list[int]
) -> list[ScopedChunk]:
    """Generation path: all AI-eligible chunks in scope, document/page order."""
    assert module_ids, "explicit module scope is required"
    rows = (
        await db.execute(
            text(
                f"""
                SELECT c.id, c.module_id, c.document_id, d.filename,
                       c.page_start, c.page_end, c.heading_path, c.text,
                       c.token_count, c.content_hash
                FROM chunks c
                {_SCOPE_FILTER}
                ORDER BY c.document_id, c.page_start, c.id
                """
            ),
            {"module_ids": module_ids},
        )
    ).all()
    return [ScopedChunk(*row) for row in rows]


async def retrieve(
    db: AsyncSession,
    module_ids: list[int],
    query_embedding: list[float],
    query_text: str,
    k: int = 8,
) -> list[ScopedChunk]:
    """Hybrid search: pgvector cosine + Postgres FTS fused with RRF.

    Exact vector scan on purpose — perfect recall at personal scale.
    """
    assert module_ids, "explicit module scope is required"
    rows = (
        await db.execute(
            text(
                f"""
                WITH scoped AS (
                    SELECT c.*, d.filename
                    FROM chunks c
                    {_SCOPE_FILTER}
                ),
                v AS (
                    SELECT s.id,
                           row_number() OVER (
                               ORDER BY ce.embedding <=> CAST(:qvec AS vector)
                           ) AS r
                    FROM scoped s
                    JOIN chunk_embeddings ce ON ce.chunk_id = s.id
                ),
                f AS (
                    SELECT s.id,
                           row_number() OVER (
                               ORDER BY ts_rank(s.tsv, plainto_tsquery('english', :q)) DESC
                           ) AS r
                    FROM scoped s
                    WHERE s.tsv @@ plainto_tsquery('english', :q)
                )
                SELECT s.id, s.module_id, s.document_id, s.filename,
                       s.page_start, s.page_end, s.heading_path, s.text,
                       s.token_count, s.content_hash
                FROM scoped s
                LEFT JOIN v ON v.id = s.id
                LEFT JOIN f ON f.id = s.id
                WHERE v.id IS NOT NULL OR f.id IS NOT NULL
                ORDER BY coalesce(1.0 / (60 + v.r), 0) + coalesce(1.0 / (60 + f.r), 0) DESC
                LIMIT :k
                """
            ),
            {
                "module_ids": module_ids,
                "qvec": str(query_embedding),
                "q": query_text,
                "k": k,
            },
        )
    ).all()
    return [ScopedChunk(*row) for row in rows]


def source_fingerprint(chunks: list[ScopedChunk]) -> str:
    """Staleness anchor: hash of the exact chunk set an artifact was built on."""
    payload = "|".join(f"{c.id}:{c.content_hash}" for c in sorted(chunks, key=lambda c: c.id))
    return hashlib.sha256(payload.encode()).hexdigest()
