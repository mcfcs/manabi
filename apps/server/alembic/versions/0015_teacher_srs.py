"""Teacher lectures (artifact type, audio, checkpoints, chat persona) +
spaced-repetition card reviews.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-10

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB  # noqa: F401 (parity with models)

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enum values can't be added inside the migration transaction
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE artifact_type ADD VALUE IF NOT EXISTS 'lecture'")

    op.add_column(
        "chat_threads",
        sa.Column("teacher_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "lecture_audio",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "artifact_id",
            sa.BigInteger(),
            sa.ForeignKey("artifacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("audio", sa.LargeBinary(), nullable=False),
        sa.Column("mime", sa.String(64), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("voice", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "artifact_id", "segment_index", name="uq_lecture_audio_segment"
        ),
    )

    op.create_table(
        "lecture_checkpoint_results",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "artifact_id",
            sa.BigInteger(),
            sa.ForeignKey("artifacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column(
            "answered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_checkpoint_results_artifact",
        "lecture_checkpoint_results",
        ["artifact_id", "segment_index"],
    )

    op.create_table(
        "card_reviews",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "flashcard_id",
            sa.BigInteger(),
            sa.ForeignKey("flashcards.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("interval_days", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ease", sa.Float(), nullable=False, server_default="2.5"),
        sa.Column("reps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lapses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_rating", sa.String(8)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_card_reviews_due", "card_reviews", ["due_date"])


def downgrade() -> None:
    op.drop_table("card_reviews")
    op.drop_table("lecture_checkpoint_results")
    op.drop_table("lecture_audio")
    op.drop_column("chat_threads", "teacher_mode")
    # enum value 'lecture' is left in place (PG cannot drop enum values)
