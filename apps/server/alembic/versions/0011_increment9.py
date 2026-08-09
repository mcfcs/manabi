"""Schedule, calendar, tasks, push subscriptions (Increment 9).

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-10

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("courses", sa.Column("canvas_course_id", sa.BigInteger()))
    op.create_index(
        "uq_courses_canvas_course_id",
        "courses",
        ["canvas_course_id"],
        unique=True,
        postgresql_where=sa.text("canvas_course_id IS NOT NULL"),
    )

    op.create_table(
        "schedule_blocks",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "course_id",
            sa.BigInteger(),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day_of_week", sa.SmallInteger(), nullable=False),
        sa.Column("start_minute", sa.Integer(), nullable=False),
        sa.Column("end_minute", sa.Integer(), nullable=False),
        sa.Column("location", sa.String(64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("end_minute > start_minute", name="ck_schedule_block_range"),
    )
    op.create_index("ix_schedule_blocks_course_id", "schedule_blocks", ["course_id"])

    op.create_table(
        "app_settings",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column(
            "semester_start", sa.Date(), nullable=False, server_default="2026-08-05"
        ),
        sa.Column(
            "semester_end", sa.Date(), nullable=False, server_default="2026-12-12"
        ),
        sa.Column("gcal_ics_url", sa.Text()),
        sa.Column("gcal_last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("gcal_last_error", sa.Text()),
        sa.Column(
            "class_reminders", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.CheckConstraint("id = 1", name="ck_app_settings_single_row"),
    )
    op.execute("INSERT INTO app_settings (id) VALUES (1)")

    op.create_table(
        "calendar_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "course_id", sa.BigInteger(), sa.ForeignKey("courses.id", ondelete="SET NULL")
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("start_minute", sa.Integer()),
        sa.Column("end_minute", sa.Integer()),
        sa.Column(
            "repeat_weekly", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("repeat_until", sa.Date()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_calendar_events_date", "calendar_events", ["date"])

    op.create_table(
        "day_marks",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column(
            "course_id", sa.BigInteger(), sa.ForeignKey("courses.id", ondelete="CASCADE")
        ),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("note", sa.String(255)),
        sa.UniqueConstraint(
            "date", "course_id", name="uq_day_marks_date_course",
            postgresql_nulls_not_distinct=True,
        ),
        sa.CheckConstraint("mode IN ('sync','async')", name="ck_day_marks_mode"),
    )

    op.create_table(
        "gcal_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("uid", sa.String(512), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("start_minute", sa.Integer()),
        sa.Column("end_minute", sa.Integer()),
        sa.Column("location", sa.String(255)),
    )
    op.create_index("ix_gcal_events_date", "gcal_events", ["date"])

    op.create_table(
        "tasks",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "course_id", sa.BigInteger(), sa.ForeignKey("courses.id", ondelete="SET NULL")
        ),
        sa.Column("due_date", sa.Date()),
        sa.Column("due_minute", sa.Integer()),
        sa.Column("done_at", sa.DateTime(timezone=True)),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("canvas_assignment_id", sa.BigInteger(), unique=True),
        sa.Column("notified_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("source IN ('manual','canvas')", name="ck_tasks_source"),
    )
    op.create_index("ix_tasks_due_date", "tasks", ["due_date"])

    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("endpoint", sa.Text(), nullable=False, unique=True),
        sa.Column("p256dh", sa.String(255), nullable=False),
        sa.Column("auth", sa.String(255), nullable=False),
        sa.Column("user_agent", sa.String(255)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("push_subscriptions")
    op.drop_table("tasks")
    op.drop_table("gcal_events")
    op.drop_table("day_marks")
    op.drop_table("calendar_events")
    op.drop_table("app_settings")
    op.drop_table("schedule_blocks")
    op.drop_index("uq_courses_canvas_course_id", table_name="courses")
    op.drop_column("courses", "canvas_course_id")
