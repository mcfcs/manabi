"""Fail app-level jobs whose Procrastinate task is already over.

`jobs` rows are the dedup guards for chat, generation and narration, so a row
stuck at `queued`/`running` does not merely spin a placeholder — it blocks the
feature outright: chat 409s "still answering", a narration can never be
re-prepared, lecture audio can never be regenerated. The only existing cleanup
is `_reap_orphans` in the GPU worker, which runs *once* at worker startup, so a
box that sleeps or simply is not restarted leaves the block in place forever.

The signal is exact and needs no timestamps: Procrastinate owns the truth about
whether a task is still going. If it says the task reached a terminal state (or
the row is gone) while our row still says queued/running, nobody is coming back
to finish it.

That is not hypothetical — job 171 has sat at `queued` since 2026-08-13 against
a Procrastinate row marked `succeeded`, because `pipeline.run_pipeline` returns
without raising when its document has disappeared, and because `_start()` is
called outside the `try` in every worker task, so a failure there leaves the row
untouched with `error = NULL`.
"""

from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Procrastinate states meaning "this task will not run again".
# `todo` and `doing` are live; `aborting` is still winding down.
TERMINAL = ("succeeded", "failed", "cancelled", "aborted")

# Grace period. A job row and its Procrastinate row are committed on separate
# connections, so for a moment a fresh job can look parentless. Well past that.
MIN_AGE = timedelta(minutes=15)

REAPED_ERROR = "the worker stopped without finishing this job"

_SQL = """
UPDATE jobs j
SET status      = 'failed',
    error       = COALESCE(j.error, :msg),
    finished_at = COALESCE(j.finished_at, now())
WHERE j.status IN ('queued', 'running')
  AND j.created_at < now() - CAST(:min_age AS interval)
  AND (
        j.procrastinate_job_id IS NULL
     OR NOT EXISTS (
          SELECT 1 FROM procrastinate_jobs p WHERE p.id = j.procrastinate_job_id
        )
     OR EXISTS (
          SELECT 1 FROM procrastinate_jobs p
          WHERE p.id = j.procrastinate_job_id
            AND p.status::text = ANY(:terminal)
        )
  )
RETURNING j.id
"""


def is_dead(app_status: str, proc_status: str | None, age: timedelta) -> bool:
    """Pure form of the SQL above, so the rule is testable without a database.
    `proc_status` is None when the Procrastinate row is missing."""
    if app_status not in ("queued", "running"):
        return False
    if age < MIN_AGE:
        return False
    return proc_status is None or proc_status in TERMINAL


async def reap_dead_jobs(db: AsyncSession) -> list[int]:
    """Fail every job whose task is demonstrably over. Returns the ids reaped."""
    rows = (
        await db.execute(
            text(_SQL),
            {
                "msg": REAPED_ERROR,
                "min_age": f"{int(MIN_AGE.total_seconds())} seconds",
                "terminal": list(TERMINAL),
            },
        )
    ).all()
    if rows:
        await db.commit()
    return [r[0] for r in rows]
