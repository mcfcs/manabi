"""Scoped/custom generation provenance on artifacts (scope_document_ids,
scope_note_ids, instructions, generation_mode) and per-deck SRS opt-in
(review_enabled). Backfills review_enabled so the latest deck per module keeps
today's "latest deck feeds the review queue" semantics.

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-22

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "artifacts",
        sa.Column("scope_document_ids", sa.ARRAY(sa.BigInteger()), nullable=True),
    )
    op.add_column(
        "artifacts",
        sa.Column("scope_note_ids", sa.ARRAY(sa.BigInteger()), nullable=True),
    )
    op.add_column("artifacts", sa.Column("instructions", sa.Text(), nullable=True))
    op.add_column(
        "artifacts", sa.Column("generation_mode", sa.String(16), nullable=True)
    )
    op.add_column("artifacts", sa.Column("review_enabled", sa.Boolean(), nullable=True))
    op.execute(
        "UPDATE artifacts SET review_enabled = false "
        "WHERE artifact_type = 'flashcard_deck'"
    )
    op.execute(
        """
        UPDATE artifacts SET review_enabled = true
        WHERE id IN (
            SELECT max(id) FROM artifacts
            WHERE artifact_type = 'flashcard_deck' GROUP BY module_id
        )
        """
    )


def downgrade() -> None:
    op.drop_column("artifacts", "review_enabled")
    op.drop_column("artifacts", "generation_mode")
    op.drop_column("artifacts", "instructions")
    op.drop_column("artifacts", "scope_note_ids")
    op.drop_column("artifacts", "scope_document_ids")
