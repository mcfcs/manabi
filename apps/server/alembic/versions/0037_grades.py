"""Syllabus-weighted grades: per-course weighted components and their scored
items, the course's own letter cutoffs and units (for QPI), plus the global
app_settings.grades_hidden switch.

Canvas is only a source of scores — the breakdown itself is the syllabus', so
weights and cutoffs live here rather than being read from Canvas.

Revision ID: 0037
Revises: 0036
Create Date: 2026-09-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("courses", sa.Column("units", sa.Float(), nullable=False, server_default="3"))
    # The six graded letters and their minimums; NULL until the user sets them.
    op.add_column("courses", sa.Column("grade_cutoffs", postgresql.JSONB(), nullable=True))

    op.create_table(
        "grade_components",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "course_id",
            sa.BigInteger(),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_grade_components_course", "grade_components", ["course_id"])

    op.create_table(
        "grade_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "component_id",
            sa.BigInteger(),
            sa.ForeignKey("grade_components.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        # points scored / possible; NULL earned = not graded yet
        sa.Column("earned", sa.Float()),
        sa.Column("possible", sa.Float()),
        # a straight percentage instead of points (mutually exclusive)
        sa.Column("percent", sa.Float()),
        sa.Column("canvas_assignment_id", sa.BigInteger()),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_grade_items_component", "grade_items", ["component_id"])
    # One Canvas assignment can only be linked once inside a component; the API
    # also refuses a duplicate anywhere in the same course (double counting).
    op.create_index(
        "uq_grade_items_canvas",
        "grade_items",
        ["component_id", "canvas_assignment_id"],
        unique=True,
        postgresql_where=sa.text("canvas_assignment_id IS NOT NULL"),
    )

    op.add_column(
        "app_settings",
        sa.Column("grades_hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "grades_hidden")
    op.drop_index("uq_grade_items_canvas", table_name="grade_items")
    op.drop_index("ix_grade_items_component", table_name="grade_items")
    op.drop_table("grade_items")
    op.drop_index("ix_grade_components_course", table_name="grade_components")
    op.drop_table("grade_components")
    op.drop_column("courses", "grade_cutoffs")
    op.drop_column("courses", "units")
