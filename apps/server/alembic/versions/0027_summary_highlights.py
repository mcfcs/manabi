"""Persistent highlights on summary artifacts (the summary analogue of document
annotations): summary_highlights(artifact_id, quote, color, note).

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-13

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "summary_highlights",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "artifact_id",
            sa.BigInteger(),
            sa.ForeignKey("artifacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("color", sa.String(length=16), nullable=False, server_default="yellow"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_summary_highlights_artifact_id", "summary_highlights", ["artifact_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_summary_highlights_artifact_id", table_name="summary_highlights")
    op.drop_table("summary_highlights")
