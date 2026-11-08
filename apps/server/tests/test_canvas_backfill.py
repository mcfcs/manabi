"""Backfill after a Canvas outage (the token expired 2026-11-06 16:00 UTC; the
last good sync was 15:56). The gap survives the scheduler's own recovery
sync, announcements are re-read from the gap's start, and the poll's
baseline means nothing is pushed twice."""

from datetime import UTC, date, datetime, timedelta

import pytest
from manabi_core.models import AppSettings, Course, User
from manabi_server.api import canvas, tasks
from manabi_server.services import canvas_backfill as bf
from manabi_server.services import push

LAST_GOOD = datetime(2026, 11, 6, 15, 56, 56, tzinfo=UTC)
NOW = datetime(2026, 11, 8, 15, 0, tzinfo=UTC)
USER = User(id=1)


def _app(**kw):
    return AppSettings(
        id=1, semester_start=date(2026, 8, 5), semester_end=date(2026, 12, 12), **kw
    )


def _ann(aid, title="T", code="SocSc 14", posted="2026-11-07T02:00:00Z"):
    return canvas.AnnouncementOut(
        id=aid, title=title, preview="", message="", posted_at=posted, author=None,
        course_id=4, course_code=code, accent_color=None, html_url=None,
    )


class FakeDB:
    def __init__(self, app=None, courses=()):
        self.app = app
        self.courses = list(courses)
        self.commits = 0

    async def get(self, model, pk):
        return self.app

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass

    async def execute(self, *a, **k):
        rows = self.courses

        class _R:
            def scalars(self):
                return self

            def all(self):
                return rows

        return _R()


# ── pure helpers ──────────────────────────────────────────────────────────


def test_the_gap_starts_at_the_last_good_sync_and_keeps_the_earliest():
    app = _app(canvas_last_synced_at=LAST_GOOD)
    bf.mark_outage(app)
    assert app.canvas_backfill_since == LAST_GOOD
    app.canvas_last_synced_at = NOW  # a later failure doesn't move the start
    bf.mark_outage(app)
    assert app.canvas_backfill_since == LAST_GOOD


def test_a_short_gap_is_forgotten_and_a_long_one_stays_owed():
    blip = _app(canvas_backfill_since=NOW - timedelta(minutes=25))
    bf.settle_after_sync(blip, NOW)
    assert blip.canvas_backfill_since is None
    outage = _app(canvas_backfill_since=LAST_GOOD)
    bf.settle_after_sync(outage, NOW)
    assert outage.canvas_backfill_since == LAST_GOOD
    assert bf.backfill_due(LAST_GOOD, NOW) and not bf.backfill_due(None, NOW)
    assert not bf.backfill_due(NOW - timedelta(minutes=59), NOW)


def test_only_announcements_never_pushed_count_as_missed():
    anns = [_ann(30), _ann(20), _ann(10)]
    assert [a.id for a in bf.missed_announcements(anns, 15)] == [30, 20]
    assert bf.missed_announcements(anns, None) == []  # no baseline → never a storm


def test_one_summary_push_for_all_missed():
    assert bf.backfill_push([]) is None
    one = bf.backfill_push([_ann(1, "Quiz moved")])
    assert one["title"] == "Missed Canvas announcement"
    assert one["body"] == "SocSc 14: Quiz moved"
    many = bf.backfill_push([_ann(3, "Quiz moved"), _ann(2), _ann(1)])
    assert many["title"] == "Missed Canvas announcements"
    assert many["body"] == "SocSc 14: Quiz moved (+2 more)"


# ── sync bookkeeping ──────────────────────────────────────────────────────


async def test_a_failed_sync_opens_the_gap_and_a_good_one_keeps_a_long_gap(monkeypatch):
    app = _app(canvas_last_synced_at=LAST_GOOD)
    db = FakeDB(app)

    async def expired(db, user):
        raise canvas.CanvasAuthError()

    monkeypatch.setattr(tasks, "_sync_canvas_tasks_inner", expired)
    with pytest.raises(canvas.CanvasAuthError):
        await tasks.sync_canvas_tasks(db, None)
    assert app.canvas_backfill_since == LAST_GOOD

    async def ok(db, user):
        return {"created": 0}

    monkeypatch.setattr(tasks, "_sync_canvas_tasks_inner", ok)
    await tasks.sync_canvas_tasks(db, None)  # the scheduler's recovery sync
    assert app.canvas_backfill_since == LAST_GOOD  # still owed: two days
    assert app.canvas_last_synced_at > LAST_GOOD


async def test_announcements_since_a_gap_ask_canvas_for_the_whole_window(monkeypatch):
    calls = []

    async def fake_get_all(path, params=None):
        calls.append(params)
        return []

    monkeypatch.setattr(canvas, "_canvas_get_all", fake_get_all)
    db = FakeDB(courses=[Course(id=4, user_id=1, code="SocSc 14", canvas_course_id=70265)])
    await canvas.fetch_announcements(db, 1, limit=100, since=LAST_GOOD)
    assert calls[0]["start_date"] == "2026-11-06T15:56:56+00:00"
    # Canvas's default end_date is start + 28 days — a long gap must set it
    assert datetime.fromisoformat(calls[0]["end_date"]) > datetime.now(UTC)
    await canvas.fetch_announcements(db, 1, limit=10)  # the poll: unchanged
    assert "start_date" not in calls[1]


# ── the endpoint ──────────────────────────────────────────────────────────


def _patch_backfill(monkeypatch, anns, sync_error=None):
    seen = {"since": "unset", "pushes": []}

    async def fake_sync(db, user):
        if sync_error:
            raise sync_error
        db.app.canvas_last_synced_at = NOW  # what a good sync does
        return {"created": 2, "closed": 1, "reopened": 0, "updated": 5, "grades_updated": 1}

    async def fake_fetch(db, user_id, course_id=None, limit=5, since=None):
        seen["since"] = since
        return anns

    async def fake_send(db, payload):
        seen["pushes"].append(payload)
        return 1

    monkeypatch.setattr(tasks, "sync_canvas_tasks", fake_sync)
    monkeypatch.setattr(canvas, "fetch_announcements", fake_fetch)
    monkeypatch.setattr(push, "send_to_all", fake_send)
    return seen


async def test_backfill_catches_up_from_the_gap_start(monkeypatch):
    app = _app(
        canvas_backfill_since=LAST_GOOD,
        canvas_last_synced_at=NOW - timedelta(minutes=3),  # scheduler already recovered
        last_announcement_id=20,
    )
    seen = _patch_backfill(monkeypatch, [_ann(40, "Exam room"), _ann(30), _ann(20)])
    out = await canvas.canvas_backfill(user=USER, db=FakeDB(app))
    assert seen["since"] == LAST_GOOD  # not the recovery sync's timestamp
    assert out.tasks["created"] == 2 and len(out.announcements) == 3
    assert out.notified == 2  # 20 was already pushed by the poll
    assert [p["body"] for p in seen["pushes"]] == ["SocSc 14: Exam room (+1 more)"]
    assert app.last_announcement_id == 40 and app.canvas_backfill_since is None


async def test_backfill_with_a_dead_token_keeps_the_gap(monkeypatch):
    app = _app(canvas_backfill_since=LAST_GOOD, last_announcement_id=20)
    seen = _patch_backfill(monkeypatch, [_ann(40)], sync_error=canvas.CanvasAuthError())
    with pytest.raises(canvas.CanvasAuthError):
        await canvas.canvas_backfill(user=USER, db=FakeDB(app))
    assert app.canvas_backfill_since == LAST_GOOD and seen["pushes"] == []


async def test_nothing_missed_sends_nothing(monkeypatch):
    app = _app(canvas_backfill_since=LAST_GOOD, last_announcement_id=40)
    seen = _patch_backfill(monkeypatch, [_ann(40), _ann(30)])
    out = await canvas.canvas_backfill(user=USER, db=FakeDB(app))
    assert out.notified == 0 and seen["pushes"] == []
    assert app.last_announcement_id == 40 and app.canvas_backfill_since is None
