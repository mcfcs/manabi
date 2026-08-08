"""AI artifacts: summaries, flashcard decks, quizzes, citations.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-09

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "module_id",
            sa.BigInteger(),
            sa.ForeignKey("modules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "artifact_type",
            sa.Enum("summary", "flashcard_deck", "quiz", name="artifact_type"),
            nullable=False,
        ),
        sa.Column("scope_module_ids", postgresql.ARRAY(sa.BigInteger()), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("source_chunk_ids", postgresql.ARRAY(sa.BigInteger()), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("module_version_at_gen", sa.Integer(), nullable=False),
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
    op.create_index("ix_artifacts_module_type", "artifacts", ["module_id", "artifact_type"])

    op.create_table(
        "flashcards",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "artifact_id",
            sa.BigInteger(),
            sa.ForeignKey("artifacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ord", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("front", sa.Text(), nullable=False),
        sa.Column("back", sa.Text(), nullable=False),
        sa.Column("edited", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "status",
            sa.Enum("active", "suspended", name="flashcard_status"),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_flashcards_artifact_id", "flashcards", ["artifact_id"])

    op.create_table(
        "quiz_questions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "artifact_id",
            sa.BigInteger(),
            sa.ForeignKey("artifacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ord", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("qtype", sa.String(16), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("options", postgresql.JSONB()),
        sa.Column("answer", postgresql.JSONB(), nullable=False),
        sa.Column("explanation", sa.Text()),
    )
    op.create_index("ix_quiz_questions_artifact_id", "quiz_questions", ["artifact_id"])

    op.create_table(
        "quiz_attempts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "artifact_id",
            sa.BigInteger(),
            sa.ForeignKey("artifacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("responses", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("score", sa.Float()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_quiz_attempts_artifact_id", "quiz_attempts", ["artifact_id"])

    op.create_table(
        "citations",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "artifact_id",
            sa.BigInteger(),
            sa.ForeignKey("artifacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_ref", sa.String(64), nullable=False),
        sa.Column(
            "chunk_id", sa.BigInteger(), sa.ForeignKey("chunks.id", ondelete="SET NULL")
        ),
        sa.Column("document_id", sa.BigInteger()),
        sa.Column("document_title", sa.String(512), nullable=False),
        sa.Column("page_start", sa.Integer()),
        sa.Column("page_end", sa.Integer()),
        sa.Column("quote_excerpt", sa.Text()),
        sa.Column("support_score", sa.Float()),
        sa.Column(
            "status",
            sa.Enum("verified", "weak", "source_removed", name="citation_status"),
            nullable=False,
            server_default="verified",
        ),
    )
    op.create_index("ix_citations_artifact_id", "citations", ["artifact_id"])
    op.create_index("ix_citations_chunk_id", "citations", ["chunk_id"])


def downgrade() -> None:
    op.drop_table("citations")
    op.drop_table("quiz_attempts")
    op.drop_table("quiz_questions")
    op.drop_table("flashcards")
    op.drop_table("artifacts")
    sa.Enum(name="citation_status").drop(op.get_bind())
    sa.Enum(name="flashcard_status").drop(op.get_bind())
    sa.Enum(name="artifact_type").drop(op.get_bind())
