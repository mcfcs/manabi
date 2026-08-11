"""Daily briefing: once-per-day gate on app_settings.

Steven's "good day" digest is generated once per Manila day and cached as his
first message in a daily thread. app_settings gains last_briefing_date (the
Manila date of the most recent briefing) to gate regeneration.

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-12

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_settings", sa.Column("last_briefing_date", sa.Date(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("app_settings", "last_briefing_date")
