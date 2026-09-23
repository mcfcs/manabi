"""Native plain-text materials.

Revision ID: 0040
Revises: 0039
"""

from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE document_kind ADD VALUE IF NOT EXISTS 'txt'")


def downgrade() -> None:
    # PostgreSQL cannot remove an enum value without recreating the type.
    # Retain the additive value so existing text materials remain intact.
    pass
