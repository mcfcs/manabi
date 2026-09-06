"""Steven narrates readings: a narration per document (status + options) and
its per-paragraph segments with synthesized audio, plus the master switch
app_settings.narration_enabled. The GPU worker reads/writes segments, so the
manabi_gpu role (when it exists) gets the same grants the lecture tables have.

Revision ID: 0036
Revises: 0035
Create Date: 2026-09-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "narrations",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "document_id",
            sa.BigInteger(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="scripted"),
        sa.Column("options", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("script_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("error", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "narration_segments",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "narration_id",
            sa.BigInteger(),
            sa.ForeignKey("narrations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ord", sa.Integer(), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("spoken_text", sa.Text(), nullable=False),
        sa.Column("audio", sa.LargeBinary()),
        sa.Column("mime", sa.String(64)),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("voice", sa.String(64)),
        sa.UniqueConstraint("narration_id", "ord", name="uq_narration_segments_ord"),
    )
    op.create_index("ix_narration_segments_narration", "narration_segments", ["narration_id"])
    op.add_column(
        "app_settings",
        sa.Column("narration_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # The GPU worker may connect as a restricted role (docs/teacher-voice.md).
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'manabi_gpu') THEN
                GRANT SELECT, UPDATE ON narrations, narration_segments TO manabi_gpu;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.drop_column("app_settings", "narration_enabled")
    op.drop_index("ix_narration_segments_narration", table_name="narration_segments")
    op.drop_table("narration_segments")
    op.drop_table("narrations")
