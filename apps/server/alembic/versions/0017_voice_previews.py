"""Voice lab: cached A/B synthesis previews (zero-shot vs fine-tuned).

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-10

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "voice_previews",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("variant", sa.String(16), nullable=False),  # base | tuned
        sa.Column("text", sa.String(500), nullable=False),
        sa.Column("audio", sa.LargeBinary(), nullable=False),
        sa.Column("mime", sa.String(64), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("variant", "text", name="uq_voice_previews_variant_text"),
    )


def downgrade() -> None:
    op.drop_table("voice_previews")
