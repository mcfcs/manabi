"""Deeper Canvas sync: documents.source_url (origin of rendered Canvas
pages/discussions/syllabus), modules.canvas_module_id (clone dedup), and the
course_links table (ExternalUrl module-items / manual resource links).

Revision ID: 0030
Revises: 0029
Create Date: 2026-08-19

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("source_url", sa.String(length=1024), nullable=True))
    op.add_column("modules", sa.Column("canvas_module_id", sa.BigInteger(), nullable=True))
    op.create_index("ix_modules_canvas_module_id", "modules", ["canvas_module_id"])

    op.create_table(
        "course_links",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "course_id",
            sa.BigInteger(),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "module_id",
            sa.BigInteger(),
            sa.ForeignKey("modules.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("canvas_item_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_course_links_course_id", "course_links", ["course_id"])
    # Re-sync upserts a Canvas link by (course, canvas_item_id).
    op.create_index(
        "uq_course_links_canvas_item",
        "course_links",
        ["course_id", "canvas_item_id"],
        unique=True,
        postgresql_where=sa.text("canvas_item_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_table("course_links")
    op.drop_index("ix_modules_canvas_module_id", table_name="modules")
    op.drop_column("modules", "canvas_module_id")
    op.drop_column("documents", "source_url")
