"""Chunk embeddings + per-document AI exclusion.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-09

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chunk_embeddings",
        sa.Column(
            "chunk_id",
            sa.BigInteger(),
            sa.ForeignKey("chunks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("embedding_model", sa.String(128), nullable=False),
        sa.Column(
            "embedded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # Exact scan at this scale — no HNSW index (add only if measured slow).

    op.add_column(
        "documents",
        sa.Column("ai_included", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("documents", "ai_included")
    op.drop_table("chunk_embeddings")
