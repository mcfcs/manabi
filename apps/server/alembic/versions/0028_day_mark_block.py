"""Per-date RTO/WFH marks for labeled schedule blocks (internship / org duty).

day_marks gains `block_id` (a mark can target a non-course ScheduleBlock), the
uniqueness widens to (date, course_id, block_id) so a block mark and the
whole-day class mark — both course_id NULL — stay distinct, and the mode check
grows to allow rto|wfh.

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-18

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "day_marks",
        sa.Column(
            "block_id",
            sa.BigInteger(),
            sa.ForeignKey("schedule_blocks.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.drop_constraint("uq_day_marks_date_course", "day_marks", type_="unique")
    op.execute(
        "ALTER TABLE day_marks ADD CONSTRAINT uq_day_marks_date_course "
        "UNIQUE NULLS NOT DISTINCT (date, course_id, block_id)"
    )
    op.drop_constraint("ck_day_marks_mode", "day_marks", type_="check")
    op.create_check_constraint(
        "ck_day_marks_mode", "day_marks", "mode IN ('sync','async','rto','wfh')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_day_marks_mode", "day_marks", type_="check")
    op.create_check_constraint(
        "ck_day_marks_mode", "day_marks", "mode IN ('sync','async')"
    )
    op.drop_constraint("uq_day_marks_date_course", "day_marks", type_="unique")
    op.execute(
        "ALTER TABLE day_marks ADD CONSTRAINT uq_day_marks_date_course "
        "UNIQUE NULLS NOT DISTINCT (date, course_id)"
    )
    op.drop_column("day_marks", "block_id")
