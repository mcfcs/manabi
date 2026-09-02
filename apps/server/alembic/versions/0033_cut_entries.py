"""Self-tracked class absences ("cuts") and lates: cut_entries. A late
consumes 0.5 of a cut; totals are computed at read time.

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-29

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cut_entries",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "course_id",
            sa.BigInteger(),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_cut_entries_course_id", "cut_entries", ["course_id"])


def downgrade() -> None:
    op.drop_index("ix_cut_entries_course_id", table_name="cut_entries")
    op.drop_table("cut_entries")
