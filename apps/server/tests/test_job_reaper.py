"""The reap rule decides whether a feature stays blocked. Procrastinate owns the
truth about whether a task is still going; our row only mirrors it."""

from datetime import timedelta

from manabi_server.services.job_reaper import MIN_AGE, is_dead

OLD = MIN_AGE + timedelta(minutes=1)
FRESH = MIN_AGE - timedelta(minutes=1)


def test_queued_against_a_succeeded_task_is_dead():
    # Job 171's exact shape: run_pipeline returned without raising when its
    # document was gone, so Procrastinate succeeded and our row never moved.
    assert is_dead("queued", "succeeded", OLD) is True


def test_running_against_a_failed_task_is_dead():
    assert is_dead("running", "failed", OLD) is True


def test_a_missing_procrastinate_row_is_dead():
    assert is_dead("queued", None, OLD) is True


def test_a_live_task_is_never_reaped():
    assert is_dead("running", "doing", OLD) is False
    assert is_dead("queued", "todo", OLD) is False


def test_a_task_still_winding_down_is_not_reaped():
    # `aborting` has not landed anywhere yet; give it its chance.
    assert is_dead("running", "aborting", OLD) is False


def test_a_young_job_is_left_alone_whatever_procrastinate_says():
    # The job row and the Procrastinate row commit on separate connections, so
    # a fresh job can briefly look parentless.
    assert is_dead("queued", None, FRESH) is False
    assert is_dead("queued", "succeeded", FRESH) is False


def test_finished_jobs_are_not_touched():
    for status in ("succeeded", "failed", "cancelled"):
        assert is_dead(status, "succeeded", OLD) is False
