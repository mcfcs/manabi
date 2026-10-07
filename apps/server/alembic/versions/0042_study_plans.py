"""study_plans: named, scoped study paths within a course

A course can hold several plans ("Midterm prep", "Pointers drill", "Readings
for the essay test"). A plan picks modules, optionally a subset of their
materials, the question types (NULL = chosen from the material), a type mix
and a free-text focus. The plan's tests are ordinary quiz artifacts tagged
`content.plan_id`.

Backfill: every course that already has study-path quizzes (content.role set)
gets a plan named "Midterm prep" over its non-general modules, and those
quizzes are attached to it.

Revision ID: 0042
Revises: 0041
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "study_plans",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column(
            "course_id",
            sa.BigInteger(),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("module_ids", postgresql.ARRAY(sa.BigInteger()), nullable=False),
        sa.Column("document_ids", postgresql.ARRAY(sa.BigInteger()), nullable=True),
        sa.Column("types", postgresql.ARRAY(sa.String(length=16)), nullable=True),
        sa.Column("type_mix", postgresql.JSONB(), nullable=True),
        sa.Column("focus", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_study_plans_course_id", "study_plans", ["course_id"])

    # Backfill: one "Midterm prep" plan per course that already has a path.
    op.execute(
        """
        INSERT INTO study_plans (course_id, name, position, module_ids, type_mix, types)
        SELECT c.id, 'Midterm prep', 0,
               ARRAY(SELECT m.id FROM modules m
                     WHERE m.course_id = c.id AND NOT m.is_general
                     ORDER BY m.position, m.id),
               '{"output": 5, "mcq": 4, "tf": 1, "identification": 1}'::jsonb,
               ARRAY['output', 'mcq', 'tf', 'identification']::varchar[]
        FROM courses c
        WHERE EXISTS (
            SELECT 1 FROM artifacts a JOIN modules m ON m.id = a.module_id
            WHERE m.course_id = c.id AND a.artifact_type = 'quiz'
              AND a.content ? 'role' AND a.content->>'role' IS NOT NULL
        )
        """
    )
    op.execute(
        """
        UPDATE artifacts a
        SET content = jsonb_set(a.content::jsonb, '{plan_id}', to_jsonb(p.id))
        FROM modules m, study_plans p
        WHERE m.id = a.module_id AND p.course_id = m.course_id
          AND a.artifact_type = 'quiz'
          AND a.content::jsonb ? 'role' AND a.content->>'role' IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_study_plans_course_id", table_name="study_plans")
    op.drop_table("study_plans")
