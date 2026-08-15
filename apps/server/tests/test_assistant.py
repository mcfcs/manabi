"""General "Manabi AI" assistant tests: prompt selection, thread output shape,
and the critical isolation guarantee — module chat's enqueue is byte-identical
(no model/personal_context leak) while general threads pass both."""

import types

# ── Prompt selector (pure) ────────────────────────────────────────────────


def test_assistant_prompt_for_selects_general():
    from manabi_ai import prompts

    assert prompts.assistant_prompt_for(True, False, True) == prompts.GENERAL_ASSISTANT_PROMPT
    assert (
        prompts.assistant_prompt_for(True, True, True)
        == prompts.GENERAL_ASSISTANT_TEACHER_PROMPT
    )
    # module thread → the existing selector (grounding-sensitive)
    assert prompts.assistant_prompt_for(False, False, True) == prompts.CHAT_PROMPT
    assert prompts.assistant_prompt_for(False, False, False) == prompts.REASONING_CHAT_PROMPT
    # the general prompt tells the model NOT to refuse general questions
    assert "not a single-module tutor" in prompts.GENERAL_ASSISTANT_PROMPT


def test_thread_out_flags_general():
    from manabi_server.api.chat import _thread_out

    def _thread(module_id):
        return types.SimpleNamespace(
            id=1, title="t", teacher_mode=False, strict_grounding=False,
            scope_document_ids=None, scope_note_ids=None, scope_module_ids=None,
            auto_materials=False, model_override=None, module_id=module_id,
            source_document_id=None, source_page=None, source_pages=None,
            source_quote=None,
            created_at=__import__("datetime").datetime.now(),
        )

    assert _thread_out(_thread(None)).is_general is True
    assert _thread_out(_thread(5)).is_general is False


# ── post_message isolation + general plumbing (mocked) ────────────────────


class _Result:
    def scalar_one_or_none(self):
        return None  # no in-flight job


class _FakeDB:
    def __init__(self):
        self.added = []

    async def execute(self, *a, **k):
        return _Result()

    def add(self, obj):
        self.added.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = len(self.added)

    async def flush(self):
        pass

    async def commit(self):
        pass


def _thread(module_id, **kw):
    return types.SimpleNamespace(
        id=7, module_id=module_id, title="New conversation",
        scope_document_ids=kw.get("scope_document_ids"),
        scope_module_ids=kw.get("scope_module_ids"),
        auto_materials=kw.get("auto_materials", False),
        model_override=kw.get("model_override"),
        source_document_id=kw.get("source_document_id"),
        source_pages=kw.get("source_pages"),
    )


class _User:
    id = 1


async def _run_post(monkeypatch, thread):
    """Call post_message with all external deps mocked; return the captured
    defer_task kwargs."""
    from manabi_server.api import chat

    captured: dict = {}

    async def fake_defer(task, queue, **kwargs):
        captured.update(kwargs)
        return 999

    monkeypatch.setattr(chat, "defer_task", fake_defer)
    # embed + retrieval (only used on some branches)
    monkeypatch.setattr(
        "manabi_server.processing.embedding.embed_texts",
        lambda texts, is_query=False: [[0.0] * 4],
    )

    async def fake_retrieve(*a, **k):
        return []

    async def fake_retrieve_relevant(*a, **k):
        return [], False

    monkeypatch.setattr(chat, "retrieve", fake_retrieve)
    monkeypatch.setattr(chat, "retrieve_relevant", fake_retrieve_relevant)
    monkeypatch.setattr(chat, "_all_user_module_ids", lambda db, user: _aw([5, 6]))

    # general-branch lazy imports
    async def fake_ctx(db, user, forward_days=7):
        return "PERSONAL CONTEXT: today is testday."

    class _AppSettings:
        general_chat_model = "gpt-oss:20b"

    async def fake_get_app_settings(db):
        return _AppSettings()

    import manabi_server.api.settings as settings_mod
    import manabi_server.services.context as ctx_mod

    monkeypatch.setattr(ctx_mod, "build_personal_context", fake_ctx)
    monkeypatch.setattr(settings_mod, "get_app_settings", fake_get_app_settings)

    await chat.post_message(
        chat.MessageIn(content="hello there"), thread=thread, user=_User(), db=_FakeDB()
    )
    return captured


async def _aw(v):
    return v


async def test_module_thread_enqueue_has_no_general_kwargs(monkeypatch):
    captured = await _run_post(monkeypatch, _thread(module_id=5))
    assert "thread_id" in captured and "chunk_ids" in captured
    assert "model" not in captured  # module chat is untouched
    assert "personal_context" not in captured


async def test_general_thread_enqueue_passes_context_and_model(monkeypatch):
    captured = await _run_post(monkeypatch, _thread(module_id=None))
    assert captured.get("personal_context", "").startswith("PERSONAL CONTEXT")
    assert captured.get("model") == "gpt-oss:20b"  # global default
    assert captured.get("chunk_ids") == []  # default: no material scan


async def test_general_thread_per_chat_model_override_wins(monkeypatch):
    # A per-chat model_override takes precedence over the global setting.
    captured = await _run_post(
        monkeypatch, _thread(module_id=None, model_override="dolphin3:8b")
    )
    assert captured.get("model") == "dolphin3:8b"


# ── Daily briefing endpoint ───────────────────────────────────────────────

import datetime as _dt  # noqa: E402


class _Res:
    def __init__(self, value=None):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def first(self):
        return self._value


def _apply_orm_defaults(obj) -> None:
    """Apply the scalar column defaults a real INSERT/flush would set, so a
    handler that builds an ORM row and immediately serializes it validates under
    the no-DB scripted harness (e.g. ChatThread.auto_materials=False)."""
    try:
        from sqlalchemy import inspect as _sa_inspect

        cols = _sa_inspect(type(obj)).columns
    except Exception:  # not a mapped class
        return
    for col in cols:
        if getattr(obj, col.key, None) is None and col.default is not None:
            if getattr(col.default, "is_scalar", False):
                setattr(obj, col.key, col.default.arg)


class _ScriptedDB:
    """Returns a scripted sequence of execute() results; records adds + commit."""

    def __init__(self, results):
        self._results = list(results)
        self.added: list = []
        self.committed = False

    async def execute(self, *a, **k):
        return self._results.pop(0) if self._results else _Res(None)

    def add(self, obj):
        self.added.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = len(self.added)
        if hasattr(obj, "created_at") and getattr(obj, "created_at", None) is None:
            obj.created_at = _dt.datetime.now()
        _apply_orm_defaults(obj)  # scalar column defaults a real flush would set

    async def flush(self):
        pass

    async def commit(self):
        self.committed = True


def _patch_briefing_deps(monkeypatch, *, last_date, model="gpt-oss:20b"):
    from manabi_server.api import assistant as asst

    captured: dict = {}

    async def fake_defer(task, queue, **kwargs):
        captured.update(kwargs)
        captured["task"] = task
        return 999

    settings = types.SimpleNamespace(
        last_briefing_date=last_date, general_chat_model=model
    )

    async def fake_get_settings(db):
        return settings

    async def fake_ctx(db, user, forward_days=7):
        return "PERSONAL CONTEXT: today is testday."

    import manabi_server.api.settings as settings_mod
    import manabi_server.services.context as ctx_mod

    monkeypatch.setattr(asst, "defer_task", fake_defer)
    monkeypatch.setattr(asst, "today_manila", lambda: _dt.date(2026, 8, 12))
    monkeypatch.setattr(settings_mod, "get_app_settings", fake_get_settings)
    monkeypatch.setattr(ctx_mod, "build_personal_context", fake_ctx)
    return asst, captured, settings


async def test_briefing_first_call_creates_thread_and_job(monkeypatch):
    asst, captured, settings = _patch_briefing_deps(monkeypatch, last_date=None)
    db = _ScriptedDB([_Res(None)])  # today's briefing thread doesn't exist yet
    out = await asst.ensure_daily_briefing(user=_User(), db=db)
    assert out.generating is True
    assert out.job_id is not None
    assert captured["task"] == asst.DAILY_BRIEFING_TASK
    assert captured["personal_context"].startswith("PERSONAL CONTEXT")
    assert captured["model"] == "gpt-oss:20b"
    assert settings.last_briefing_date == _dt.date(2026, 8, 12)  # gate flipped
    assert db.committed is True


async def test_briefing_idempotent_same_day(monkeypatch):
    asst, captured, _ = _patch_briefing_deps(
        monkeypatch, last_date=_dt.date(2026, 8, 12)
    )
    existing = types.SimpleNamespace(id=5)
    # thread found, then its first assistant message row (id, content)
    db = _ScriptedDB([_Res(existing), _Res((42, "Good day, testday."))])
    out = await asst.ensure_daily_briefing(user=_User(), db=db)
    assert out.thread_id == 5
    assert out.generating is False
    assert out.message_id == 42
    assert out.body == "Good day, testday."
    assert "task" not in captured  # no new job deferred


# ── Steven takes actions ──────────────────────────────────────────────────

import pytest  # noqa: E402


async def test_execute_task_action_builds_task(monkeypatch):
    from manabi_server.services import ai_actions

    async def _no_course(db, user, code):
        return None

    monkeypatch.setattr(ai_actions, "_course_id_by_code", _no_course)
    db = _ScriptedDB([])
    out = await ai_actions.execute_task_action(
        db, _User(), {"title": "Review OOP", "due_date": "2026-08-15", "due_minute": 900}
    )
    assert out == {"kind": "task", "id": 1, "title": "Review OOP"}
    task = db.added[0]
    assert task.title == "Review OOP"
    assert str(task.due_date) == "2026-08-15"
    assert task.due_minute == 900


async def test_execute_task_action_requires_title():
    from manabi_server.services import ai_actions

    with pytest.raises(ValueError):
        await ai_actions.execute_task_action(_ScriptedDB([]), _User(), {"title": "  "})


async def test_confirm_action_executes_and_marks_done(monkeypatch):
    from manabi_server.api import assistant as asst

    async def _fake_task(db, user, params):
        return {"kind": "task", "id": 9, "title": params["title"]}

    monkeypatch.setattr(asst, "execute_task_action", _fake_task)
    msg = types.SimpleNamespace(
        id=1,
        action={
            "status": "proposed",
            "items": [
                {"kind": "create_task", "summary": "A", "params": {"title": "A"}},
                {"kind": "create_task", "summary": "B", "params": {"title": "B"}},
            ],
        },
    )
    db = _ScriptedDB([])
    out = await asst.confirm_action(message=msg, user=_User(), db=db)
    assert out["status"] == "done"
    assert len(out["results"]) == 2  # BOTH items created
    assert {r["title"] for r in out["results"]} == {"A", "B"}
    assert msg.action["status"] == "done"  # reassigned so the ORM sees the change
    assert db.committed is True


async def test_confirm_action_rejects_when_no_pending():
    from fastapi import HTTPException
    from manabi_server.api import assistant as asst

    msg = types.SimpleNamespace(id=1, action=None)
    with pytest.raises(HTTPException) as exc:
        await asst.confirm_action(message=msg, user=_User(), db=_ScriptedDB([]))
    assert exc.value.status_code == 409


async def test_cancel_action_marks_cancelled():
    from manabi_server.api import assistant as asst

    msg = types.SimpleNamespace(
        id=1,
        action={
            "status": "proposed",
            "items": [{"kind": "create_event", "summary": "x", "params": {"title": "x"}}],
        },
    )
    db = _ScriptedDB([])
    out = await asst.cancel_action(message=msg, db=db)
    assert out["status"] == "cancelled"
    assert msg.action["status"] == "cancelled"
    assert db.committed is True


async def test_delete_message():
    from manabi_server.api import chat

    class _DelDB:
        def __init__(self):
            self.deleted = None
            self.committed = False

        async def delete(self, obj):
            self.deleted = obj

        async def commit(self):
            self.committed = True

    msg = types.SimpleNamespace(id=5)
    db = _DelDB()
    out = await chat.delete_message(message=msg, db=db)
    assert out == {"ok": True}
    assert db.deleted is msg
    assert db.committed is True


# ── Ask Steven across multiple pages ──────────────────────────────────────


def test_format_pages_compresses_runs():
    from manabi_server.api.chat import _format_pages

    assert _format_pages([1, 2, 3, 5]) == "1-3, 5"
    assert _format_pages([1]) == "1"
    assert _format_pages([2, 4, 6]) == "2, 4, 6"
    assert _format_pages([1, 2, 3, 4]) == "1-4"


async def test_discuss_stores_sorted_deduped_pages():
    from manabi_server.api import chat

    doc = types.SimpleNamespace(id=9, module_id=3, page_count=20)
    db = _ScriptedDB([])
    out = await chat.discuss_document(
        chat.DiscussIn(quote="", pages=[3, 1, 2, 2, 5]),  # unsorted + duplicate
        doc=doc, user=_User(), db=db,
    )
    thread = db.added[0]
    assert thread.source_pages == [1, 2, 3, 5]
    assert thread.source_page == 1  # first, for display/back-compat
    assert thread.title == "Pages 1-3, 5"
    assert out.source_pages == [1, 2, 3, 5]


async def test_discuss_clamps_pages_to_document():
    from manabi_server.api import chat

    doc = types.SimpleNamespace(id=9, module_id=3, page_count=4)
    db = _ScriptedDB([])
    await chat.discuss_document(
        chat.DiscussIn(quote="", pages=[2, 99]),  # 99 is past the last page
        doc=doc, user=_User(), db=db,
    )
    assert db.added[0].source_pages == [2]


async def test_discuss_without_pages_keeps_single_passage():
    from manabi_server.api import chat

    doc = types.SimpleNamespace(id=9, module_id=3, page_count=20)
    db = _ScriptedDB([])
    await chat.discuss_document(
        chat.DiscussIn(quote="a quoted passage", page=7),
        doc=doc, user=_User(), db=db,
    )
    thread = db.added[0]
    assert thread.source_pages is None
    assert thread.source_page == 7
    assert thread.source_quote == "a quoted passage"
