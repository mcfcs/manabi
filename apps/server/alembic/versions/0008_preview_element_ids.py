"""Live generation preview + per-citation element targeting.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-09

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("preview", sa.Text()))
    op.add_column(
        "citations", sa.Column("element_ids", postgresql.ARRAY(sa.BigInteger()))
    )


def downgrade() -> None:
    op.drop_column("citations", "element_ids")
    op.drop_column("jobs", "preview")
