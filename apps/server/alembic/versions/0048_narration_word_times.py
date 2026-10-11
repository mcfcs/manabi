"""narration_segments.word_times: when each displayed word is spoken

A list of start times (ms into the segment's audio), one per whitespace token
of the segment's `text`, so the player and the reader can highlight the word
Steven is saying. NULL until aligned.

Revision ID: 0048
Revises: 0047
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("narration_segments", sa.Column("word_times", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("narration_segments", "word_times")
