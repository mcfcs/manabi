"""Chat material scoping, multiple notes per module, canvas sync bookkeeping.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-10

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Chat thread material scope: NULL = all, [] = none of that kind.
    op.add_column(
        "chat_threads",
        sa.Column("scope_document_ids", postgresql.ARRAY(sa.BigInteger()), nullable=True),
    )
    op.add_column(
        "chat_threads",
        sa.Column("scope_note_ids", postgresql.ARRAY(sa.BigInteger()), nullable=True),
    )

    # Multiple notes per module; server_default backfills existing rows.
    op.drop_constraint("notes_module_id_key", "notes", type_="unique")
    op.create_index("ix_notes_module_id", "notes", ["module_id"])
    op.add_column(
        "notes",
        sa.Column("title", sa.String(255), nullable=False, server_default="Notes"),
    )
    op.add_column(
        "notes",
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )

    # Canvas task sync bookkeeping (timestamp advances only on success).
    op.add_column(
        "app_settings",
        sa.Column("canvas_last_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("app_settings", sa.Column("canvas_last_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("app_settings", "canvas_last_error")
    op.drop_column("app_settings", "canvas_last_synced_at")
    op.drop_column("notes", "position")
    op.drop_column("notes", "title")
    op.drop_index("ix_notes_module_id", table_name="notes")
    # Lossy: keeps only the newest note per module before restoring uniqueness.
    op.execute(
        """
        DELETE FROM notes n USING notes newer
        WHERE newer.module_id = n.module_id AND newer.id > n.id
        """
    )
    op.create_unique_constraint("notes_module_id_key", "notes", ["module_id"])
    op.drop_column("chat_threads", "scope_note_ids")
    op.drop_column("chat_threads", "scope_document_ids")
