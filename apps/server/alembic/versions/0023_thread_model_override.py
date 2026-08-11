"""Per-chat model override for the general assistant.

chat_threads gains model_override (NULL = use the global general_chat_model /
node default). Only meaningful for general (module-less) threads.

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-11

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_threads", sa.Column("model_override", sa.String(128), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("chat_threads", "model_override")
