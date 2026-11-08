"""app_settings.canvas_access_token: a Canvas token pasted in Settings

Wins over CANVAS_ACCESS_TOKEN in .env, so an expired token is replaced from
the app instead of by editing .env and redeploying. NULL = use .env.

Revision ID: 0049
Revises: 0048
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("app_settings", sa.Column("canvas_access_token", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("app_settings", "canvas_access_token")
