"""General "Manabi AI" assistant: module-less chat threads.

chat_threads gains user_id (owner, backfilled), module_id becomes nullable
(NULL = general/assistant thread), plus scope_module_ids + auto_materials for
cross-module material scope. app_settings gains general_chat_model.

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-11

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Owner column — add nullable, backfill from module→course→user, then lock.
    op.add_column("chat_threads", sa.Column("user_id", sa.BigInteger(), nullable=True))
    op.execute(
        """
        UPDATE chat_threads ct SET user_id = co.user_id
        FROM modules m JOIN courses co ON co.id = m.course_id
        WHERE m.id = ct.module_id
        """
    )
    # Safety net for any orphan rows (no general threads exist yet at 0022).
    op.execute(
        "UPDATE chat_threads SET user_id = (SELECT id FROM users ORDER BY id LIMIT 1) "
        "WHERE user_id IS NULL"
    )
    op.alter_column("chat_threads", "user_id", existing_type=sa.BigInteger(), nullable=False)
    op.create_foreign_key(
        "fk_chat_threads_user", "chat_threads", "users", ["user_id"], ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_chat_threads_user_id", "chat_threads", ["user_id"])

    # module_id becomes nullable (NULL = general thread). Keep its CASCADE FK.
    op.alter_column("chat_threads", "module_id", existing_type=sa.BigInteger(), nullable=True)

    op.add_column(
        "chat_threads",
        sa.Column("scope_module_ids", postgresql.ARRAY(sa.BigInteger()), nullable=True),
    )
    op.add_column(
        "chat_threads",
        sa.Column(
            "auto_materials", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )

    op.add_column(
        "app_settings", sa.Column("general_chat_model", sa.String(128), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("app_settings", "general_chat_model")
    # Drop general threads before restoring module_id NOT NULL.
    op.execute("DELETE FROM chat_threads WHERE module_id IS NULL")
    op.alter_column("chat_threads", "module_id", existing_type=sa.BigInteger(), nullable=False)
    op.drop_column("chat_threads", "auto_materials")
    op.drop_column("chat_threads", "scope_module_ids")
    op.drop_index("ix_chat_threads_user_id", table_name="chat_threads")
    op.drop_constraint("fk_chat_threads_user", "chat_threads", type_="foreignkey")
    op.drop_column("chat_threads", "user_id")
