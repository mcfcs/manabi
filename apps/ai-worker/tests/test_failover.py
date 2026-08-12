"""Ollama failover: when the primary node (phillmyeol) is unreachable, the
worker retries against the local backup Ollama with the small backup model.
A slow-but-reachable primary must NOT trigger failover, and with no backup
configured the failure surfaces as a clean GenerationError."""

import types

import httpx
import pytest

from manabi_ai import ollama_client as oc


def _settings(*, backup=False):
    return types.SimpleNamespace(
        ollama_url="http://phillmyeol:11434",
        generation_model="qwen3.5:27b",
        ollama_backup_url="http://127.0.0.1:11434" if backup else "",
        ollama_backup_model="qwen2.5:7b-instruct" if backup else "",
        backup_enabled=backup,
    )


def _record_stream(monkeypatch, primary_exc=None, backup_content="BACKUP", primary_content="PRIMARY"):
    """Patch _stream_once to record (url, model) calls; primary raises
    primary_exc if given, otherwise returns primary_content."""
    calls: list[tuple[str, str]] = []

    async def fake_stream_once(url, model, system, user, schema, on_preview):
        calls.append((url, model))
        if url == "http://phillmyeol:11434" and primary_exc is not None:
            raise primary_exc
        return backup_content if "127.0.0.1" in url else primary_content

    monkeypatch.setattr(oc, "_stream_once", fake_stream_once)
    return calls


async def test_primary_success_never_touches_backup(monkeypatch):
    calls = _record_stream(monkeypatch)
    out = await oc._stream_chat(_settings(backup=True), "s", "u", {}, None, model="gpt-oss:20b")
    assert out == "PRIMARY"
    assert calls == [("http://phillmyeol:11434", "gpt-oss:20b")]  # backup untouched


async def test_failover_uses_backup_url_and_model(monkeypatch):
    calls = _record_stream(monkeypatch, primary_exc=httpx.ConnectError("down"))
    out = await oc._stream_chat(_settings(backup=True), "s", "u", {}, None, model="gpt-oss:20b")
    assert out == "BACKUP"
    # requested (phillmyeol-only) model is ignored on the backup path
    assert calls == [
        ("http://phillmyeol:11434", "gpt-oss:20b"),
        ("http://127.0.0.1:11434", "qwen2.5:7b-instruct"),
    ]


async def test_no_backup_reraises_connection_error(monkeypatch):
    _record_stream(monkeypatch, primary_exc=httpx.ConnectError("down"))
    with pytest.raises(httpx.ConnectError):
        await oc._stream_chat(_settings(backup=False), "s", "u", {}, None)


async def test_read_timeout_does_not_fail_over(monkeypatch):
    # A slow but reachable primary should propagate, NOT silently downgrade.
    _record_stream(monkeypatch, primary_exc=httpx.ReadTimeout("slow"))
    with pytest.raises(httpx.ReadTimeout):
        await oc._stream_chat(_settings(backup=True), "s", "u", {}, None)


async def test_generate_structured_wraps_node_down_when_no_backup(monkeypatch):
    monkeypatch.setattr(oc, "get_settings", lambda: _settings(backup=False))

    async def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(oc, "_stream_chat", boom)
    with pytest.raises(oc.GenerationError) as exc:
        await oc.generate_structured("s", "u", {})
    assert "unreachable" in str(exc.value).lower()


async def test_generate_structured_succeeds_via_backup(monkeypatch):
    monkeypatch.setattr(oc, "get_settings", lambda: _settings(backup=True))
    _record_stream(monkeypatch, primary_exc=httpx.ConnectError("down"), backup_content='{"ok": true}')
    out = await oc.generate_structured("s", "u", {}, model="gpt-oss:20b")
    assert out == {"ok": True}
