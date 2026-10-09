"""class_roundups: an evening note on what happened in each class meeting

One row per course per day (naive Manila date). Writable for past days at
any time and for today from 8 PM; read by the calendar, the course page's
class log and Steven's daily briefing.

Revision ID: 0045
Revises: 0044
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "class_roundups",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "course_id",
            sa.BigInteger(),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("course_id", "date", name="uq_class_roundups_course_date"),
    )
    op.create_index("ix_class_roundups_date", "class_roundups", ["date"])


def downgrade() -> None:
    op.drop_index("ix_class_roundups_date", table_name="class_roundups")
    op.drop_table("class_roundups")
