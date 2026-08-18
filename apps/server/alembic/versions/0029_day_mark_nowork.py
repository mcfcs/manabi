"""Allow the 'nowork' mode on day_marks (labeled blocks can be RTO / WFH / No
work for a date, e.g. an internship day off).

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-19

"""
from collections.abc import Sequence

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_day_marks_mode", "day_marks", type_="check")
    op.create_check_constraint(
        "ck_day_marks_mode",
        "day_marks",
        "mode IN ('sync','async','rto','wfh','nowork')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_day_marks_mode", "day_marks", type_="check")
    op.create_check_constraint(
        "ck_day_marks_mode", "day_marks", "mode IN ('sync','async','rto','wfh')"
    )
