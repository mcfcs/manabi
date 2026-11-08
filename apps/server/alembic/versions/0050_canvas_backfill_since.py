"""app_settings.canvas_backfill_since: start of a Canvas outage not yet caught up

The last good sync before Canvas calls started failing (an expired token on
2026-11-06). Kept apart from canvas_last_synced_at because the scheduler's
own sync advances that within minutes of a new token, and the gap would be
forgotten before Backfill could catch announcements up. NULL = nothing owed.

Revision ID: 0050
Revises: 0049
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0050"
down_revision: str | None = "0049"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("canvas_backfill_since", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "canvas_backfill_since")
