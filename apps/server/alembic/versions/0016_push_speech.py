"""Announcement-push tracking + spoken chat replies.

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-10

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("app_settings", sa.Column("last_announcement_id", sa.BigInteger()))
    op.create_table(
        "speech_clips",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "chat_message_id",
            sa.BigInteger(),
            sa.ForeignKey("chat_messages.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("audio", sa.LargeBinary(), nullable=False),
        sa.Column("mime", sa.String(64), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("voice", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("speech_clips")
    op.drop_column("app_settings", "last_announcement_id")
