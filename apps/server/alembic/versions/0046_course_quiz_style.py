"""courses.quiz_style: how this course's instructor writes quizzes

Free text the student pastes in: past quiz questions and notes on the
instructor's habits ("identification answers are one term", "always one
opinion question"). Quiz generation writes in that style; NULL = no style.

Revision ID: 0046
Revises: 0045
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("courses", sa.Column("quiz_style", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("courses", "quiz_style")
