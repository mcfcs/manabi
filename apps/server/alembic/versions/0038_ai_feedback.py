"""ai_feedback: keep the outputs the owner rejected

Revision ID: 0038
Revises: 0037
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "ai_feedback",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column(
            "kind",
            postgresql.ENUM(
                "question_regenerated",
                "answer_disputed",
                "card_edited",
                name="ai_feedback_kind",
            ),
            nullable=False,
        ),
        sa.Column(
            "artifact_id",
            sa.BigInteger(),
            sa.ForeignKey("artifacts.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "question_id",
            sa.BigInteger(),
            sa.ForeignKey("quiz_questions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "flashcard_id",
            sa.BigInteger(),
            sa.ForeignKey("flashcards.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("rejected", postgresql.JSONB(), nullable=True),
        sa.Column("preferred", postgresql.JSONB(), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_ai_feedback_kind_created", "ai_feedback", ["kind", "created_at"])

    # The GPU worker writes here (regenerate_question, verify_question) under
    # the restricted role, when that role exists — mirrors 0036_narration.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'manabi_gpu') THEN
            GRANT SELECT, INSERT ON ai_feedback TO manabi_gpu;
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_ai_feedback_kind_created", table_name="ai_feedback")
    op.drop_table("ai_feedback")
    op.execute("DROP TYPE IF EXISTS ai_feedback_kind")
