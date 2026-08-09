"""Hidden per-course "Course files" containers (system modules).

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-10

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "modules",
        sa.Column("is_general", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Existing "General" modules created by the earlier Canvas import flow
    # become course-files containers.
    op.execute("UPDATE modules SET is_general = true WHERE lower(title) = 'general'")


def downgrade() -> None:
    op.drop_column("modules", "is_general")
