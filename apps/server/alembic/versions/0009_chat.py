"""Per-module chat threads and messages.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-09

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_threads",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "module_id",
            sa.BigInteger(),
            sa.ForeignKey("modules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_chat_threads_module_id", "chat_threads", ["module_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "thread_id",
            sa.BigInteger(),
            sa.ForeignKey("chat_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Enum("user", "assistant", name="chat_role"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("grounded", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "general_knowledge", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("citations", postgresql.JSONB()),
        sa.Column(
            "job_id", sa.BigInteger(), sa.ForeignKey("jobs.id", ondelete="SET NULL")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_chat_messages_thread_id", "chat_messages", ["thread_id"])


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("chat_threads")
    sa.Enum(name="chat_role").drop(op.get_bind())
