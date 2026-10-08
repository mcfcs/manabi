"""practice: judged coding problems and theory tasks (grammar / regex / DFA)

`practice_problems` holds a statement, visible samples, hidden tests and a
hidden reference solution. Test expectations are computed by the app (running
the reference, or membership in the reference language), never written by the
model. `practice_submissions` records every Run and Submit with per-test
results.

Revision ID: 0044
Revises: 0043
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "practice_problems",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("course_id", sa.BigInteger(), sa.ForeignKey("courses.id", ondelete="CASCADE")),
        sa.Column("module_id", sa.BigInteger(), sa.ForeignKey("modules.id", ondelete="SET NULL")),
        sa.Column("plan_id", sa.BigInteger(), sa.ForeignKey("study_plans.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("language", sa.String(16)),
        sa.Column("title", sa.String(255), nullable=False, server_default="Practice problem"),
        sa.Column("topic", sa.Text()),
        sa.Column("difficulty", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("source", sa.String(16), nullable=False, server_default="materials"),
        sa.Column("statement", sa.Text(), nullable=False, server_default=""),
        sa.Column("spec", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("samples", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("tests", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("reference", sa.Text(), nullable=False, server_default=""),
        sa.Column("time_limit_ms", sa.Integer(), nullable=False, server_default="2000"),
        sa.Column("status", sa.String(16), nullable=False, server_default="generating"),
        sa.Column("error", sa.Text()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model_name", sa.String(128)),
        sa.Column(
            "source_chunk_ids",
            postgresql.ARRAY(sa.BigInteger()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("job_id", sa.BigInteger(), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("solved_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_practice_problems_user", "practice_problems", ["user_id"])
    op.create_index("ix_practice_problems_course", "practice_problems", ["course_id"])
    op.create_table(
        "practice_submissions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "problem_id",
            sa.BigInteger(),
            sa.ForeignKey("practice_problems.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("language", sa.String(16)),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("verdict", sa.String(24), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("results", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_practice_submissions_problem", "practice_submissions", ["problem_id"])


def downgrade() -> None:
    op.drop_index("ix_practice_submissions_problem", table_name="practice_submissions")
    op.drop_table("practice_submissions")
    op.drop_index("ix_practice_problems_course", table_name="practice_problems")
    op.drop_index("ix_practice_problems_user", table_name="practice_problems")
    op.drop_table("practice_problems")
