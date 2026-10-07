"""tasks: remember who marked a task done, and latch Canvas's done state

The Canvas sync now closes a task when Canvas reports the assignment
submitted / excused / graded. `done_source` records who set done_at
('manual' | 'canvas'); `canvas_done_seen` latches "Canvas's done state was
already applied once", so a manual un-check survives every later sync and a
redo request only reopens tasks Canvas itself closed.

Backfill: the latch starts off everywhere (the first sync closes open tasks
Canvas already reports done). Every task already done was ticked by hand —
nothing closed tasks automatically before this — so it is marked 'manual'.

Revision ID: 0043
Revises: 0042
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("done_source", sa.String(length=16), nullable=True))
    op.add_column(
        "tasks",
        sa.Column(
            "canvas_done_seen",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.execute("UPDATE tasks SET done_source = 'manual' WHERE done_at IS NOT NULL")


def downgrade() -> None:
    op.drop_column("tasks", "canvas_done_seen")
    op.drop_column("tasks", "done_source")
