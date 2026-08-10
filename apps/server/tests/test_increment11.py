"""Increment 11 unit tests: canvas sync cadence, note image sniffing,
chat-scope PATCH semantics, retrieval scope filter."""

from datetime import UTC, datetime, timedelta

from manabi_core.retrieval import _scope_filter
from manabi_server.api.chat import ThreadPatch
from manabi_server.api.notes import (
    ASSET_NAME_RE,
    derive_plain_text,
    sniff_image_ext,
)
from manabi_server.services.scheduler import canvas_sync_due
from manabi_server.storage.files import note_asset_path

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


# ── Canvas sync cadence ───────────────────────────────────────────────────


def test_canvas_sync_due_when_never_synced():
    assert canvas_sync_due(None, NOW) is True


def test_canvas_sync_not_due_when_fresh():
    assert canvas_sync_due(NOW - timedelta(minutes=9), NOW) is False


def test_canvas_sync_due_when_stale():
    assert canvas_sync_due(NOW - timedelta(minutes=11), NOW) is True


# ── Note image sniffing ───────────────────────────────────────────────────


def test_sniff_accepts_real_image_magic():
    assert sniff_image_ext(b"\x89PNG\r\n\x1a\n rest") == "png"
    assert sniff_image_ext(b"\xff\xd8\xff\xe0 jpeg") == "jpg"
    assert sniff_image_ext(b"GIF89a data") == "gif"
    assert sniff_image_ext(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "webp"


def test_sniff_rejects_non_images():
    assert sniff_image_ext(b"<svg xmlns='...'>") is None
    assert sniff_image_ext(b"<html><script>") is None
    assert sniff_image_ext(b"%PDF-1.7") is None
    assert sniff_image_ext(b"") is None


def test_note_asset_path_shape_matches_serving_regex():
    rel = note_asset_path(42, "png")
    prefix, name = rel.rsplit("/", 1)
    assert prefix == "note_assets/42"
    assert ASSET_NAME_RE.fullmatch(name)


def test_asset_name_regex_rejects_traversal_and_other_types():
    assert not ASSET_NAME_RE.fullmatch("../secret.png")
    assert not ASSET_NAME_RE.fullmatch("a" * 32 + ".svg")
    assert not ASSET_NAME_RE.fullmatch("0" * 31 + ".png")


# ── ProseMirror walker ignores image nodes ────────────────────────────────


def test_plain_text_ignores_image_nodes():
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "before"}],
            },
            {"type": "image", "attrs": {"src": "/api/notes/1/images/x.png"}},
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "after"}],
            },
        ],
    }
    assert derive_plain_text(doc) == "before\nafter"


# ── ThreadPatch scope semantics (absent vs null vs list) ──────────────────


def test_thread_patch_absent_field_not_in_fields_set():
    patch = ThreadPatch.model_validate({"teacher_mode": True})
    assert "scope_document_ids" not in patch.model_fields_set


def test_thread_patch_explicit_null_means_all():
    patch = ThreadPatch.model_validate({"scope_document_ids": None})
    assert "scope_document_ids" in patch.model_fields_set
    assert patch.scope_document_ids is None


def test_thread_patch_explicit_lists():
    patch = ThreadPatch.model_validate(
        {"scope_document_ids": [1, 2], "scope_note_ids": []}
    )
    assert patch.scope_document_ids == [1, 2]
    assert patch.scope_note_ids == []
    assert "scope_note_ids" in patch.model_fields_set


# ── Retrieval scope filter SQL ────────────────────────────────────────────


def test_scope_filter_unchanged_without_documents():
    assert "document_id = ANY(:document_ids)" not in _scope_filter(None)


def test_scope_filter_narrows_to_documents():
    sql = _scope_filter([3, 4])
    assert "c.document_id = ANY(:document_ids)" in sql
    assert "c.module_id = ANY(:module_ids)" in sql
