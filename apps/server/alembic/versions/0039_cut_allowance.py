"""courses.cut_allowance: give "N cuts used" a denominator

Revision ID: 0039
Revises: 0038
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Nullable on purpose: NULL means "no allowance recorded", which reads
    # differently from an allowance of zero.
    op.add_column("courses", sa.Column("cut_allowance", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("courses", "cut_allowance")
