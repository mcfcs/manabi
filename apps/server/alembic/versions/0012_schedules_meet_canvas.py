"""Named schedules, flexible entries, meeting links, render-only docs,
multi-calendar labels.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-10

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "schedules",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.execute("INSERT INTO schedules (title, position) VALUES ('Class schedule', 0)")

    # schedule_blocks becomes a flexible entry: course-linked OR free-label,
    # timed OR TBA (day/time NULL)
    op.add_column("schedule_blocks", sa.Column("schedule_id", sa.BigInteger()))
    op.execute(
        "UPDATE schedule_blocks SET schedule_id = (SELECT id FROM schedules LIMIT 1)"
    )
    op.alter_column("schedule_blocks", "schedule_id", nullable=False)
    op.create_foreign_key(
        "fk_schedule_blocks_schedule",
        "schedule_blocks",
        "schedules",
        ["schedule_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("schedule_blocks", "course_id", nullable=True)
    op.alter_column("schedule_blocks", "day_of_week", nullable=True)
    op.alter_column("schedule_blocks", "start_minute", nullable=True)
    op.alter_column("schedule_blocks", "end_minute", nullable=True)
    op.add_column("schedule_blocks", sa.Column("label", sa.String(128)))
    op.add_column("schedule_blocks", sa.Column("color", sa.String(16)))
    op.drop_constraint("ck_schedule_block_range", "schedule_blocks", type_="check")
    op.create_check_constraint(
        "ck_schedule_block_range",
        "schedule_blocks",
        "start_minute IS NULL OR end_minute IS NULL OR end_minute > start_minute",
    )

    op.add_column("courses", sa.Column("meeting_url", sa.String(512)))
    op.add_column(
        "documents",
        sa.Column(
            "processing_mode", sa.String(16), nullable=False, server_default="full"
        ),
    )
    op.add_column("gcal_events", sa.Column("calendar", sa.String(128)))


def downgrade() -> None:
    op.drop_column("gcal_events", "calendar")
    op.drop_column("documents", "processing_mode")
    op.drop_column("courses", "meeting_url")
    op.drop_constraint("ck_schedule_block_range", "schedule_blocks", type_="check")
    op.create_check_constraint(
        "ck_schedule_block_range", "schedule_blocks", "end_minute > start_minute"
    )
    op.drop_column("schedule_blocks", "color")
    op.drop_column("schedule_blocks", "label")
    op.execute(
        "DELETE FROM schedule_blocks WHERE course_id IS NULL OR day_of_week IS NULL"
        " OR start_minute IS NULL OR end_minute IS NULL"
    )
    op.alter_column("schedule_blocks", "end_minute", nullable=False)
    op.alter_column("schedule_blocks", "start_minute", nullable=False)
    op.alter_column("schedule_blocks", "day_of_week", nullable=False)
    op.alter_column("schedule_blocks", "course_id", nullable=False)
    op.drop_constraint(
        "fk_schedule_blocks_schedule", "schedule_blocks", type_="foreignkey"
    )
    op.drop_column("schedule_blocks", "schedule_id")
    op.drop_table("schedules")
