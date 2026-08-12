"""Assistant-proposed actions on chat messages ("Steven takes actions").

chat_messages gains a nullable JSONB `action` holding a proposed action
(create_task / create_event / …) that only executes after the user confirms.

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-12

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_messages", sa.Column("action", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "action")
