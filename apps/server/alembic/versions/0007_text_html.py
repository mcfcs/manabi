"""Per-page extracted rich text for the viewer Text view.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-09

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("document_pages", sa.Column("text_html", sa.Text()))


def downgrade() -> None:
    op.drop_column("document_pages", "text_html")
