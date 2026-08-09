"""Google event details: organizer, attendees, my RSVP status.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-10

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("gcal_events", sa.Column("organizer", sa.String(255)))
    op.add_column("gcal_events", sa.Column("attendees", JSONB()))
    op.add_column("gcal_events", sa.Column("my_status", sa.String(16)))


def downgrade() -> None:
    op.drop_column("gcal_events", "my_status")
    op.drop_column("gcal_events", "attendees")
    op.drop_column("gcal_events", "organizer")
