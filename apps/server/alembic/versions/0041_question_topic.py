"""quiz_questions: what each question tests, and which module it came from

An exam spans modules and a result is only useful broken down: "pointers
7/10, OOP 3/8". The module a question was written from and the topic the
model said it tests are recorded per question (both nullable — every
existing question predates them).

Revision ID: 0041
Revises: 0040
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("quiz_questions", sa.Column("topic", sa.String(length=120), nullable=True))
    op.add_column(
        "quiz_questions",
        sa.Column(
            "module_id",
            sa.BigInteger(),
            sa.ForeignKey("modules.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("quiz_questions", "module_id")
    op.drop_column("quiz_questions", "topic")
