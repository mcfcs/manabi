"""pronunciations: how Steven says a course's terms

One row per course per term: the respelling fed to the voice ("Quimpo" →
"Keem Poe"), whether it was learned automatically or set by the student, and
how closely the voice's sounds matched the intended ones.

Revision ID: 0047
Revises: 0046
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "pronunciations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "course_id",
            sa.BigInteger(),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("term", sa.String(80), nullable=False),
        sa.Column("say", sa.String(160), nullable=False),
        sa.Column("source", sa.String(8), nullable=False, server_default="auto"),
        sa.Column("match", sa.Float(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("course_id", "term", name="uq_pronunciations_course_term"),
    )


def downgrade() -> None:
    op.drop_table("pronunciations")
