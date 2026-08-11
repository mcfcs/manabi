"""Chat reasoning mode + viewer-originated thread source ref + course cover.

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-11

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Chat threads: reasoning mode + the viewer passage a discussion is about.
    op.add_column(
        "chat_threads",
        sa.Column(
            "strict_grounding", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
    )
    op.add_column(
        "chat_threads", sa.Column("source_document_id", sa.BigInteger(), nullable=True)
    )
    op.add_column("chat_threads", sa.Column("source_page", sa.Integer(), nullable=True))
    op.add_column("chat_threads", sa.Column("source_quote", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_chat_threads_source_document",
        "chat_threads",
        "documents",
        ["source_document_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_chat_threads_source_document_id", "chat_threads", ["source_document_id"]
    )

    # Courses: cosmetic card cover image.
    op.add_column(
        "courses", sa.Column("cover_image_path", sa.String(1024), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("courses", "cover_image_path")
    op.drop_index("ix_chat_threads_source_document_id", table_name="chat_threads")
    op.drop_constraint(
        "fk_chat_threads_source_document", "chat_threads", type_="foreignkey"
    )
    op.drop_column("chat_threads", "source_quote")
    op.drop_column("chat_threads", "source_page")
    op.drop_column("chat_threads", "source_document_id")
    op.drop_column("chat_threads", "strict_grounding")
