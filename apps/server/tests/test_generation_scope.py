"""Scoped/custom generation: payload-aware duplicate-proofing, scope
validation, focused retrieval fallback, defer-contract threading, exercise
prompt/schema forks, and scope-aware staleness."""

import sys
import types
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).parents[2] / "ai-worker" / "src"))


# ── Fakes ─────────────────────────────────────────────────────────────────


class _Scalars:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def all(self):
        return self._rows

    def __iter__(self):
        return iter(self._rows)


class _Result:
    def __init__(self, *, scalars=(), scalar_one=None):
        self._scalars = scalars
        self._scalar_one = scalar_one

    def scalars(self):
        return _Scalars(self._scalars)

    def scalar_one(self):
        return self._scalar_one

    def scalar_one_or_none(self):
        return self._scalar_one


class _FakeDB:
    """Returns queued results for successive execute() calls."""

    def __init__(self, results=()):
        self.results = list(results)
        self.added = []

    async def execute(self, *a, **k):
        return self.results.pop(0) if self.results else _Result()

    def add(self, obj):
        self.added.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = 100 + len(self.added)

    async def flush(self):
        pass

    async def commit(self):
        pass


class _User:
    id = 1


def _module(id=5, title="Networks"):
    return types.SimpleNamespace(id=id, title=title, content_version=1)


# ── _matching_inflight (payload-aware dedup) ──────────────────────────────


def test_matching_inflight_same_payload_collapses():
    from manabi_server.api.artifacts import _matching_inflight

    payload = {"module_id": 5, "count": 12, "document_ids": [1], "mode": "sources"}
    job = types.SimpleNamespace(payload=dict(payload))
    assert _matching_inflight([job], payload) is job


def test_matching_inflight_different_payload_allows_new_job():
    from manabi_server.api.artifacts import _matching_inflight

    inflight = types.SimpleNamespace(
        payload={"module_id": 5, "count": 12, "instructions": None, "mode": "sources"}
    )
    new = {"module_id": 5, "count": 12, "instructions": "focus on X", "mode": "sources"}
    assert _matching_inflight([inflight], new) is None


async def test_enqueue_returns_matching_inflight_without_deferring(monkeypatch):
    from manabi_server.api import artifacts

    payload = {"module_id": 5, "count": 12}
    existing = types.SimpleNamespace(payload=dict(payload), id=42)
    db = _FakeDB([_Result(scalars=[existing])])

    async def boom(*a, **k):  # defer must not run
        raise AssertionError("defer_task called for a duplicate request")

    monkeypatch.setattr(artifacts, "defer_task", boom)
    job = await artifacts._enqueue_generation(
        db, _User(), _module(), "generate_flashcards", "task.name", **payload
    )
    assert job is existing


async def test_enqueue_exercise_with_focus_allows_empty_scope(monkeypatch):
    """Topic-only practice: exercise mode + instructions synthesizes from
    nothing — the no-chunks 409 must not fire."""
    from manabi_server.api import artifacts

    captured: dict = {}

    async def fake_defer(task, queue, **kwargs):
        captured.update(kwargs)
        return 999

    async def fake_load(db, module_ids, *, document_ids=None):
        return []  # no AI-eligible material at all

    monkeypatch.setattr(artifacts, "defer_task", fake_defer)
    monkeypatch.setattr(artifacts, "load_context_chunks", fake_load)
    db = _FakeDB([_Result(scalars=[])])  # no in-flight jobs
    job = await artifacts._enqueue_generation(
        db, _User(), _module(), "generate_quiz", "task.name",
        module_ids=[5], mode="exercise", instructions="C increment operators",
    )
    assert job.id is not None and captured["mode"] == "exercise"


async def test_enqueue_sources_mode_still_requires_material(monkeypatch):
    from manabi_server.api import artifacts

    async def fake_load(db, module_ids, *, document_ids=None):
        return []

    monkeypatch.setattr(artifacts, "load_context_chunks", fake_load)
    db = _FakeDB([_Result(scalars=[])])
    with pytest.raises(HTTPException) as exc:
        await artifacts._enqueue_generation(
            db, _User(), _module(), "generate_flashcards", "task.name",
            module_id=5, mode="sources", instructions=None,
        )
    assert exc.value.status_code == 409


# ── _validate_scope ───────────────────────────────────────────────────────


async def test_validate_scope_rejects_foreign_document():
    from manabi_server.api.artifacts import _validate_scope

    db = _FakeDB([_Result(scalars=[1, 2])])  # module owns docs 1, 2
    with pytest.raises(HTTPException) as exc:
        await _validate_scope(db, 5, [1, 99], None)
    assert exc.value.status_code == 422


async def test_validate_scope_accepts_owned_docs_and_notes():
    from manabi_server.api.artifacts import _validate_scope

    db = _FakeDB([_Result(scalars=[1, 2]), _Result(scalars=[7])])
    await _validate_scope(db, 5, [1, 2], [7])  # no raise


# ── _focus_chunk_ids (topic retrieval + fallback) ─────────────────────────


def _hits(n):
    return [types.SimpleNamespace(id=100 + i) for i in range(n)]


async def _run_focus(monkeypatch, hit_count):
    from manabi_server.api import artifacts

    monkeypatch.setattr(
        "manabi_server.processing.embedding.embed_texts",
        lambda texts, is_query=False: [[0.0] * 4],
    )

    async def fake_retrieve(db, module_ids, vec, text, k, document_ids=None):
        return _hits(hit_count)

    monkeypatch.setattr(artifacts, "retrieve", fake_retrieve)
    monkeypatch.setattr(artifacts, "dedup_diversify", lambda hits, limit: hits[:limit])
    return await artifacts._focus_chunk_ids(_FakeDB(), [5], "increment operators", None)


async def test_focus_chunk_ids_returns_ids(monkeypatch):
    ids = await _run_focus(monkeypatch, 10)
    assert ids == [100 + i for i in range(10)]


async def test_focus_chunk_ids_thin_topic_falls_back_to_none(monkeypatch):
    assert await _run_focus(monkeypatch, 3) is None


# ── Endpoint defer contracts ──────────────────────────────────────────────


async def test_generate_flashcards_threads_full_contract(monkeypatch):
    from manabi_server.api import artifacts

    captured: dict = {}

    async def fake_defer(task, queue, **kwargs):
        captured.update(kwargs)
        return 999

    async def fake_focus(db, module_ids, instructions, document_ids):
        return [11, 12, 13, 14, 15, 16]

    async def fake_load(db, module_ids, *, document_ids=None):
        return [object()]  # AI-eligible material exists

    monkeypatch.setattr(artifacts, "defer_task", fake_defer)
    monkeypatch.setattr(artifacts, "_focus_chunk_ids", fake_focus)
    monkeypatch.setattr(artifacts, "load_context_chunks", fake_load)

    db = _FakeDB(
        [
            _Result(scalars=[1, 2]),  # _validate_scope: module's documents
            _Result(scalars=[7]),  # _validate_scope: module's notes
            _Result(scalars=[]),  # _enqueue_generation: no in-flight jobs
        ]
    )
    ref = await artifacts.generate_flashcards(
        artifacts.GenerateCardsIn(
            count=12,
            document_ids=[1, 2],
            note_ids=[7],
            instructions="  focus on increment operators  ",
            mode="exercise",
        ),
        module=_module(),
        user=_User(),
        db=db,
    )
    assert ref.job_id is not None
    assert captured["module_id"] == 5
    assert captured["count"] == 12
    assert captured["document_ids"] == [1, 2]
    assert captured["note_ids"] == [7]
    assert captured["instructions"] == "focus on increment operators"  # stripped
    assert captured["mode"] == "exercise"
    assert captured["chunk_ids"] == [11, 12, 13, 14, 15, 16]
    # the Job payload snapshots the same contract (minus job_id)
    job = next(o for o in db.added if getattr(o, "payload", None) is not None)
    assert job.payload == {k: v for k, v in captured.items() if k != "job_id"}


async def test_generate_flashcards_plain_body_unchanged(monkeypatch):
    """Legacy body {count} still defers, with the new keys explicit-None."""
    from manabi_server.api import artifacts

    captured: dict = {}

    async def fake_defer(task, queue, **kwargs):
        captured.update(kwargs)
        return 999

    async def fake_load(db, module_ids, *, document_ids=None):
        assert document_ids is None
        return [object()]

    monkeypatch.setattr(artifacts, "defer_task", fake_defer)
    monkeypatch.setattr(artifacts, "load_context_chunks", fake_load)

    db = _FakeDB([_Result(scalars=[])])  # no in-flight jobs
    await artifacts.generate_flashcards(
        artifacts.GenerateCardsIn(count=20), module=_module(), user=_User(), db=db
    )
    assert captured["count"] == 20
    assert captured["document_ids"] is None
    assert captured["note_ids"] is None
    assert captured["instructions"] is None
    assert captured["mode"] == "sources"
    assert captured["chunk_ids"] is None


async def test_create_quiz_document_scope_requires_single_module():
    from manabi_server.api import artifacts

    db = _FakeDB(
        [
            _Result(scalars=[1, 2]),  # ownership: both modules owned
            _Result(scalar_one=_module(1)),  # anchor
        ]
    )
    with pytest.raises(HTTPException) as exc:
        await artifacts.create_quiz(
            artifacts.QuizConfigIn(module_ids=[1, 2], document_ids=[3]),
            user=_User(),
            db=db,
        )
    assert exc.value.status_code == 422


# ── Scope-aware staleness ─────────────────────────────────────────────────


def _chunk(id, content_hash=None):
    return types.SimpleNamespace(id=id, content_hash=content_hash or f"h{id}")


async def test_staleness_focused_artifact_fresh_then_stale(monkeypatch):
    from manabi_core.retrieval import source_fingerprint
    from manabi_server.api import artifacts

    used = [_chunk(1), _chunk(2)]
    artifact = types.SimpleNamespace(
        instructions="focus X",
        scope_module_ids=[5],
        scope_document_ids=None,
        source_chunk_ids=[1, 2],
        source_fingerprint=source_fingerprint(used),
    )

    async def hydrate_same(db, ids):
        return used

    monkeypatch.setattr(artifacts, "load_chunks_by_ids", hydrate_same)
    assert await artifacts._staleness(_FakeDB(), artifact) == "fresh"

    async def hydrate_changed(db, ids):
        return [_chunk(1), _chunk(2, content_hash="edited")]

    monkeypatch.setattr(artifacts, "load_chunks_by_ids", hydrate_changed)
    assert await artifacts._staleness(_FakeDB(), artifact) == "stale"


async def test_staleness_scoped_deck_compares_within_scope(monkeypatch):
    """A document-scoped deck is fresh against its own scope even when the
    module has other (unscoped) material — the pre-fix behavior reported
    'incomplete' forever."""
    from manabi_core.retrieval import source_fingerprint
    from manabi_server.api import artifacts

    scoped_chunks = [_chunk(1), _chunk(2)]
    artifact = types.SimpleNamespace(
        instructions=None,
        scope_module_ids=[5],
        scope_document_ids=[10],
        source_chunk_ids=[1, 2],
        source_fingerprint=source_fingerprint(scoped_chunks),
    )
    seen: dict = {}

    async def fake_load(db, module_ids, *, document_ids=None):
        seen["document_ids"] = document_ids
        return scoped_chunks

    monkeypatch.setattr(artifacts, "load_context_chunks", fake_load)
    assert await artifacts._staleness(_FakeDB(), artifact) == "fresh"
    assert seen["document_ids"] == [10]


# ── Prompts v6 + exercise schema forks ────────────────────────────────────


def test_prompt_version_is_current():
    from manabi_ai import prompts

    # exact value asserted in test_quiz_types.py — here just guard staleness
    assert prompts.PROMPT_VERSION >= "v8"


def test_exercise_schemas_make_source_ids_optional():
    from manabi_ai import prompts

    for schema, key in (
        (prompts.FLASHCARDS_EXERCISE_SCHEMA, "cards"),
        (prompts.QUIZ_EXERCISE_SCHEMA, "questions"),
    ):
        item = schema["properties"][key]["items"]
        assert "source_ids" not in item["required"]
        assert "minItems" not in item["properties"]["source_ids"]

    # the strict schemas are untouched by the fork
    for schema, key in (
        (prompts.FLASHCARDS_SCHEMA, "cards"),
        (prompts.QUIZ_SCHEMA, "questions"),
    ):
        item = schema["properties"][key]["items"]
        assert "source_ids" in item["required"]
        assert item["properties"]["source_ids"]["minItems"] == 1


def test_focus_block_formats_by_replace():
    from manabi_ai import prompts

    block = prompts.FOCUS_BLOCK.replace("{instructions}", "C increment operators")
    assert "C increment operators" in block
    assert "{instructions}" not in block


def test_exercise_prompts_have_placeholders_and_self_check():
    from manabi_ai import prompts

    assert "{count}" in prompts.EXERCISE_FLASHCARDS_PROMPT
    assert "{existing_fronts}" in prompts.EXERCISE_FLASHCARDS_PROMPT
    assert "{count}" in prompts.EXERCISE_QUIZ_PROMPT
    assert "{types}" in prompts.EXERCISE_QUIZ_PROMPT
    assert "SELF-CHECK" in prompts.EXERCISE_QUIZ_PROMPT


# ── Worker deck titles ────────────────────────────────────────────────────


def test_deck_titles():
    from manabi_ai.tasks_gen import _deck_title

    assert _deck_title("Networks", "sources", None, None) == "Flashcards — Networks"
    assert _deck_title("Networks", "sources", None, [4, 5]) == "Cards — 2 sources · Networks"
    assert _deck_title("Networks", "sources", "focus on subnetting", None).startswith(
        "Cards — focus on subnetting"
    )
    assert _deck_title("Networks", "exercise", None, None) == "Practice — Networks"
    long = "x" * 60
    t = _deck_title("Networks", "exercise", long, None)
    assert t.startswith("Practice — ") and len(t) < 70
