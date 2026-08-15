"""Multi-page "Ask about pages 1-3, 5": chat_threads gains a nullable
source_pages int array holding the exact pages that ground a viewer discussion.

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-13

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_threads",
        sa.Column("source_pages", postgresql.ARRAY(sa.BigInteger()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_threads", "source_pages")
