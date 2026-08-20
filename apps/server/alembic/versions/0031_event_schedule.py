"""Categorize a calendar event under a schedule group (e.g. Internship):
calendar_events.schedule_id.

Revision ID: 0031
Revises: 0030
Create Date: 2026-08-19

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "calendar_events",
        sa.Column(
            "schedule_id",
            sa.BigInteger(),
            sa.ForeignKey("schedules.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("calendar_events", "schedule_id")
