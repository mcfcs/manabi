"""Canvas task sync: auto-done on submission through the done_source /
canvas_done_seen latch, the creation window, and rate-limit handling —
mocked Canvas and an in-memory fake session (no live DB)."""

import types
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from manabi_core.models import AppSettings, Course, GradeItem, StudyTask
from manabi_server.api import canvas, tasks

# ── canvas_says_done ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("submission", "done"),
    [
        (None, False),  # no submission object at all
        ({"workflow_state": "unsubmitted"}, False),
        ({"workflow_state": "unsubmitted", "missing": True}, False),
        ({"workflow_state": "submitted", "submitted_at": "2026-10-01T10:00:00Z"}, True),
        (
            {"workflow_state": "submitted", "submitted_at": "2026-10-01T10:00:00Z", "late": True},
            True,
        ),
        ({"workflow_state": "pending_review"}, True),
        ({"workflow_state": "graded", "submitted_at": "2026-10-01T10:00:00Z"}, True),
        ({"workflow_state": "graded", "submitted_at": None}, True),  # on_paper, graded
        ({"workflow_state": "graded", "missing": True, "score": 0}, False),
        ({"workflow_state": "unsubmitted", "excused": True}, True),
    ],
)
def test_canvas_says_done(submission, done):
    assert tasks.canvas_says_done({"id": 1, "submission": submission}) is done


# ── Fake session ───────────────────────────────────────────────────────────


class _Res:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class _Scalars(list):
    def all(self):
        return list(self)


class FakeDB:
    def __init__(self, courses, tasks_, app=None, grade_items=None):
        self.courses = courses
        self.tasks = tasks_
        self.app = app
        self.grade_items = grade_items or []
        self.commits = 0

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0]["entity"]
        if entity is Course:
            return _Res(self.courses)
        if entity is StudyTask:
            return _Res([t for t in self.tasks if t.canvas_assignment_id is not None])
        if entity is GradeItem:
            return _Res([i for i in self.grade_items if i.canvas_assignment_id is not None])
        raise AssertionError(f"unexpected query on {entity}")

    async def get(self, model, pk):
        if model is AppSettings:
            return self.app
        if model is StudyTask:
            return next((t for t in self.tasks if t.id == pk), None)
        return None

    def add(self, obj):
        self.tasks.append(obj)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


USER = types.SimpleNamespace(id=1)
NOW = datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _course():
    return Course(id=10, user_id=1, code="CS 1", canvas_course_id=777, archived_at=None)


def _app(semester_start: date):
    return AppSettings(id=1, semester_start=semester_start, semester_end=date(2027, 1, 1))


def _assignment(aid, due, submission=None, types_=("online_upload",)):
    return {
        "id": aid,
        "name": f"A{aid}",
        "due_at": _iso(due) if due else None,
        "submission_types": list(types_),
        "submission": submission or {"workflow_state": "unsubmitted"},
    }


SUBMITTED = {"workflow_state": "submitted", "submitted_at": "2026-10-01T10:00:00Z"}
UNSUBMITTED = {"workflow_state": "unsubmitted"}


def _canvas_task(aid, **kw):
    return StudyTask(
        id=aid,
        user_id=1,
        title=f"A{aid}",
        course_id=10,
        due_date=(NOW + timedelta(days=3)).date(),
        source="canvas",
        canvas_assignment_id=aid,
        canvas_done_seen=kw.pop("canvas_done_seen", False),
        done_at=kw.pop("done_at", None),
        done_source=kw.pop("done_source", None),
        created_at=NOW,
    )


def _patch_canvas(monkeypatch, assignments):
    calls = []

    async def fake_get_all(path, params=None):
        calls.append((path, params))
        return list(assignments)

    monkeypatch.setattr(canvas, "_canvas_get_all", fake_get_all)
    return calls


async def test_sync_fetches_one_unbucketed_request_per_course(monkeypatch):
    calls = _patch_canvas(monkeypatch, [])
    db = FakeDB([_course()], [], _app(date(2026, 8, 1)))
    out = await tasks._sync_canvas_tasks_inner(db, USER)
    assert out["courses_checked"] == 1
    assert calls == [("/courses/777/assignments", {"include[]": "submission"})]


async def test_sync_creates_only_open_assignments_inside_the_window(monkeypatch):
    sem_start = (NOW - timedelta(days=30)).date()
    _patch_canvas(
        monkeypatch,
        [
            _assignment(1, NOW + timedelta(days=2)),  # future, open → created
            _assignment(2, NOW + timedelta(days=2), SUBMITTED),  # done → skipped
            _assignment(3, NOW - timedelta(days=5)),  # overdue this semester → created
            _assignment(4, NOW - timedelta(days=60)),  # before semester start → skipped
            _assignment(5, NOW - timedelta(days=5), types_=("on_paper",)),  # nothing to submit
            _assignment(6, None),  # undated → skipped
            _assignment(7, NOW + timedelta(days=9), {"excused": True}),  # excused → skipped
        ],
    )
    db = FakeDB([_course()], [], _app(sem_start))
    out = await tasks._sync_canvas_tasks_inner(db, USER)
    assert sorted(t.canvas_assignment_id for t in db.tasks) == [1, 3]
    assert out["created"] == 2
    assert all(t.done_at is None and t.source == "canvas" for t in db.tasks)


async def test_sync_refreshes_a_linked_grade_from_the_same_download(monkeypatch):
    graded = {"workflow_state": "graded", "submitted_at": None, "score": 10}
    calls = _patch_canvas(
        monkeypatch,
        [{**_assignment(1, NOW - timedelta(days=2), graded), "points_possible": 10}],
    )
    row = GradeItem(title="A1", earned=None, possible=10.0, percent=None, canvas_assignment_id=1)
    db = FakeDB([_course()], [], _app(date(2026, 8, 1)), grade_items=[row])
    out = await tasks._sync_canvas_tasks_inner(db, USER)
    assert out["grades_updated"] == 1 and row.earned == 10.0
    assert len(calls) == 1  # no second Canvas request for grades


async def test_sync_without_settings_row_uses_a_60_day_window(monkeypatch):
    _patch_canvas(
        monkeypatch,
        [_assignment(1, NOW - timedelta(days=30)), _assignment(2, NOW - timedelta(days=90))],
    )
    db = FakeDB([_course()], [], app=None)
    await tasks._sync_canvas_tasks_inner(db, USER)
    assert [t.canvas_assignment_id for t in db.tasks] == [1]


async def test_sync_closes_an_open_task_once_canvas_reports_it_submitted(monkeypatch):
    task = _canvas_task(1)
    _patch_canvas(monkeypatch, [_assignment(1, NOW + timedelta(days=3), SUBMITTED)])
    db = FakeDB([_course()], [task], _app(date(2026, 8, 1)))
    out = await tasks._sync_canvas_tasks_inner(db, USER)
    assert out["closed"] == 1
    assert task.done_at == datetime(2026, 10, 1, 10, 0, tzinfo=UTC)  # submitted_at
    assert task.done_source == "canvas" and task.canvas_done_seen is True
    assert tasks._task_out(task, None).done_source == "canvas"


async def test_manual_uncheck_survives_later_syncs(monkeypatch):
    task = _canvas_task(1)
    _patch_canvas(monkeypatch, [_assignment(1, NOW + timedelta(days=3), SUBMITTED)])
    db = FakeDB([_course()], [task], _app(date(2026, 8, 1)))
    await tasks._sync_canvas_tasks_inner(db, USER)
    assert task.done_at is not None

    # the user un-checks it through the API
    await tasks.update_task(1, tasks.TaskPatch(done=False), user=USER, db=db)
    assert task.done_at is None and task.done_source == "manual"

    for _ in range(3):  # Canvas still says submitted — the latch keeps it open
        out = await tasks._sync_canvas_tasks_inner(db, USER)
        assert out["closed"] == 0
    assert task.done_at is None and task.done_source == "manual"


async def test_redo_reopens_only_tasks_canvas_closed(monkeypatch):
    by_canvas = _canvas_task(
        1, done_at=NOW, done_source="canvas", canvas_done_seen=True
    )
    by_hand = _canvas_task(2, done_at=NOW, done_source="manual", canvas_done_seen=True)
    _patch_canvas(
        monkeypatch,
        [
            _assignment(1, NOW + timedelta(days=3), UNSUBMITTED),
            _assignment(2, NOW + timedelta(days=3), UNSUBMITTED),
        ],
    )
    db = FakeDB([_course()], [by_canvas, by_hand], _app(date(2026, 8, 1)))
    out = await tasks._sync_canvas_tasks_inner(db, USER)
    assert out["reopened"] == 1
    assert by_canvas.done_at is None and by_canvas.done_source is None
    assert by_hand.done_at == NOW and by_hand.done_source == "manual"  # never auto-unchecked
    assert not by_canvas.canvas_done_seen and not by_hand.canvas_done_seen


async def test_resubmission_after_redo_closes_again(monkeypatch):
    task = _canvas_task(1, done_at=NOW, done_source="canvas", canvas_done_seen=True)
    db = FakeDB([_course()], [task], _app(date(2026, 8, 1)))
    _patch_canvas(monkeypatch, [_assignment(1, NOW + timedelta(days=3), UNSUBMITTED)])
    await tasks._sync_canvas_tasks_inner(db, USER)
    assert task.done_at is None
    _patch_canvas(monkeypatch, [_assignment(1, NOW + timedelta(days=3), SUBMITTED)])
    await tasks._sync_canvas_tasks_inner(db, USER)
    assert task.done_at is not None and task.done_source == "canvas"


async def test_manually_done_task_is_left_alone_when_canvas_agrees(monkeypatch):
    task = _canvas_task(1, done_at=NOW, done_source="manual")
    _patch_canvas(monkeypatch, [_assignment(1, NOW + timedelta(days=3), SUBMITTED)])
    db = FakeDB([_course()], [task], _app(date(2026, 8, 1)))
    out = await tasks._sync_canvas_tasks_inner(db, USER)
    assert out["closed"] == 0
    assert task.done_at == NOW and task.done_source == "manual"
    assert task.canvas_done_seen is True


async def test_user_toggle_marks_done_source_manual():
    task = _canvas_task(1)
    db = FakeDB([], [task])
    out = await tasks.update_task(1, tasks.TaskPatch(done=True), user=USER, db=db)
    assert out.done and out.done_source == "manual"


async def test_sync_failure_propagates(monkeypatch):
    async def boom(path, params=None):
        raise canvas.CanvasRateLimited()

    monkeypatch.setattr(canvas, "_canvas_get_all", boom)
    db = FakeDB([_course(), Course(id=11, user_id=1, code="X", canvas_course_id=8)], [])
    with pytest.raises(canvas.CanvasRateLimited):
        await tasks._sync_canvas_tasks_inner(db, USER)


# ── Shared client, rate limiting, gather_limited ───────────────────────────


def _mock_client(monkeypatch, handler):
    client = httpx.AsyncClient(
        base_url="https://canvas.test/api/v1", transport=httpx.MockTransport(handler)
    )
    monkeypatch.setattr(canvas, "_get_client", lambda: client)
    monkeypatch.setattr(canvas, "_RATE_LIMIT_BACKOFF", (0, 0, 0))
    return client


async def test_rate_limit_is_not_swallowed_as_an_empty_tab(monkeypatch):
    hits = []

    def handler(request):
        hits.append(request.url.path)
        return httpx.Response(403, text="403 Forbidden (Rate Limit Exceeded)")

    _mock_client(monkeypatch, handler)
    with pytest.raises(canvas.CanvasRateLimited):
        await canvas._safe_get_all("/courses/1/pages")
    assert len(hits) == 4  # first try + three backed-off retries


async def test_rate_limit_retries_then_succeeds(monkeypatch):
    responses = [
        httpx.Response(403, text="403 Forbidden (Rate Limit Exceeded)"),
        httpx.Response(200, json=[{"id": 1}]),
    ]
    _mock_client(monkeypatch, lambda request: responses.pop(0))
    assert await canvas._canvas_get_all("/courses/1/pages") == [{"id": 1}]


async def test_plain_403_is_still_an_empty_tab(monkeypatch):
    _mock_client(monkeypatch, lambda request: httpx.Response(403, text="unauthorized tab"))
    assert await canvas._safe_get_all("/courses/1/pages") == []


async def test_pagination_follows_next_links(monkeypatch):
    def handler(request):
        if "page=2" in str(request.url):
            return httpx.Response(200, json=[{"id": 2}])
        return httpx.Response(
            200,
            json=[{"id": 1}],
            headers={"Link": '<https://canvas.test/api/v1/x?page=2>; rel="next"'},
        )

    _mock_client(monkeypatch, handler)
    assert await canvas._canvas_get_all("/x") == [{"id": 1}, {"id": 2}]


async def test_shared_client_is_reused_within_a_loop(canvas_configured):
    try:
        first = canvas._get_client()
        assert canvas._get_client() is first
        assert str(first.base_url).endswith("/api/v1/")
    finally:
        await canvas.aclose_canvas_client()
    assert canvas._client is None


async def test_gather_limited_caps_concurrency_and_keeps_order():
    import asyncio

    running = peak = 0

    async def job(i):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return i

    assert await canvas.gather_limited((job(i) for i in range(10)), n=3) == list(range(10))
    assert peak == 3


async def test_canvas_is_read_only(canvas_configured):
    # Owner's rule: Manabi never writes to Canvas. Enforced on the client.
    try:
        client = canvas._get_client()
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with pytest.raises(canvas.CanvasWriteRefused):
                await client.request(method, "/courses/1/assignments")
    finally:
        await canvas.aclose_canvas_client()
