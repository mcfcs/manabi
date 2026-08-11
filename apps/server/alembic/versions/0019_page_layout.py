"""Two-page-spread handling: documents.page_layout + detected_layout.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-11

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("page_layout", sa.String(8), nullable=False, server_default="auto"),
    )
    op.add_column("documents", sa.Column("detected_layout", sa.String(8), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "detected_layout")
    op.drop_column("documents", "page_layout")
