"""Partial unique index for document hash (allow re-upload after soft-delete)
+ app_settings.chat_autovoice.

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-11

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A soft-deleted document kept the (module_id, content_hash) unique slot,
    # so re-uploading the same file after deleting it threw IntegrityError.
    # Make the uniqueness apply only to live rows, matching the dedup query.
    op.drop_constraint("uq_documents_module_hash", "documents", type_="unique")
    op.create_index(
        "uq_documents_module_hash",
        "documents",
        ["module_id", "content_hash"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.add_column(
        "app_settings",
        sa.Column(
            "chat_autovoice", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "chat_autovoice")
    op.drop_index("uq_documents_module_hash", table_name="documents")
    op.create_unique_constraint(
        "uq_documents_module_hash", "documents", ["module_id", "content_hash"]
    )
