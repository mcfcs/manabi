"""Review queue: one-level undo and leech handling. card_reviews.prev_state
holds the pre-rating snapshot (or {"new": true}) so the last rating can be
reverted; is_leech marks cards auto-suspended for lapsing too often.

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("card_reviews", sa.Column("prev_state", postgresql.JSONB(), nullable=True))
    op.add_column(
        "card_reviews",
        sa.Column("is_leech", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("card_reviews", "is_leech")
    op.drop_column("card_reviews", "prev_state")
