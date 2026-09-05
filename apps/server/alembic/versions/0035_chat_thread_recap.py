"""Rolling recap for long chat threads: chat_threads.summary holds a model-
written digest of the turns that no longer fit the prompt window;
summary_upto_id is the last message id the digest covers.

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chat_threads", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column("chat_threads", sa.Column("summary_upto_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_threads", "summary_upto_id")
    op.drop_column("chat_threads", "summary")
