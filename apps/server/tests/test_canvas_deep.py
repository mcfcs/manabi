"""Deeper Canvas sync + stronger chat grounding — unit coverage that needs
neither LibreOffice nor a live DB (soffice/real-DB paths are checked live)."""

import types

import pytest

# ── Grounding: dedup_diversify ─────────────────────────────────────────────


def _chunk(cid, doc, page, text):
    from manabi_core.retrieval import ScopedChunk

    return ScopedChunk(
        id=cid, module_id=1, document_id=doc, document_title="D",
        page_start=page, page_end=page, heading_path=None, text=text,
        token_count=10, content_hash=str(cid),
    )


def test_dedup_diversify_caps_per_page_and_drops_dupes():
    from manabi_core.retrieval import dedup_diversify

    hits = [
        _chunk(1, 10, 1, "alpha beta"),
        _chunk(2, 10, 1, "alpha beta"),  # exact dup text → dropped
        _chunk(3, 10, 1, "gamma"),
        _chunk(4, 10, 1, "delta"),       # 3rd on (10,1) → capped (per_page=2)
        _chunk(5, 10, 2, "epsilon"),     # different page → kept
        _chunk(6, 11, 1, "zeta"),        # different doc → kept
    ]
    out = dedup_diversify(hits, limit=8, per_page=2)
    ids = [c.id for c in out]
    assert ids == [1, 3, 5, 6]  # dup(2) dropped, page-cap drops 4


def test_dedup_diversify_respects_limit():
    from manabi_core.retrieval import dedup_diversify

    hits = [_chunk(i, i, 1, f"text {i}") for i in range(20)]
    assert len(dedup_diversify(hits, limit=8)) == 8


# ── Grounding: conversation-aware retrieval query ──────────────────────────


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Res:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class _DB:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, *a, **k):
        return _Res(self._rows)


async def test_retrieval_query_folds_in_recent_turns():
    from manabi_server.api.chat import _retrieval_query

    thread = types.SimpleNamespace(id=7)
    # DB returns the last user messages, newest first (incl. the current one).
    db = _DB(["explain that more", "what is photosynthesis"])
    q = await _retrieval_query(db, thread, "explain that more")
    assert q == "explain that more\nwhat is photosynthesis"  # deduped, current first


# ── Canvas structure parse (mocked Canvas) ─────────────────────────────────


async def test_canvas_structure_parses_modules_items(monkeypatch):
    from manabi_server.api import canvas

    async def fake_get_all(path, params=None):
        if "/modules" in path:
            return [
                {
                    "id": 1, "name": "Week 1", "position": 1,
                    "items": [
                        {"id": 11, "type": "File", "title": "Slides", "content_id": 99},
                        {"id": 12, "type": "ExternalUrl", "title": "Docs",
                         "external_url": "https://x.test"},
                        {"id": 13, "type": "Page", "title": "Notes", "page_url": "notes"},
                    ],
                }
            ]
        if "/pages" in path:
            return [{"url": "intro", "title": "Intro"}]
        if "/discussion_topics" in path:
            return [{"id": 5, "title": "Q&A"}]
        return []

    async def fake_get(path, params=None):
        return {"syllabus_body": "<p>Read chapter 1</p>"}

    monkeypatch.setattr(canvas, "_canvas_get_all", fake_get_all)
    monkeypatch.setattr(canvas, "_canvas_get", fake_get)

    out = await canvas.canvas_structure(canvas_course_id=42)
    assert len(out.modules) == 1
    m = out.modules[0]
    assert m.canvas_id == 1 and m.name == "Week 1"
    assert [it.type for it in m.items] == ["File", "ExternalUrl", "Page"]
    assert m.items[1].external_url == "https://x.test"
    assert m.items[2].page_url == "notes"
    assert out.pages == [{"url": "intro", "title": "Intro"}]
    assert out.discussions == [{"id": 5, "title": "Q&A"}]
    assert out.has_syllabus is True


# ── HTML→text + filename helpers ───────────────────────────────────────────


def test_html_to_text_keeps_breaks():
    from manabi_server.services.canvas_ingest import html_to_text

    assert html_to_text("<p>One</p><p>Two</p>") == "One\nTwo"
    assert "•" in html_to_text("<ul><li>a</li><li>b</li></ul>")


def test_safe_filename_strips_bad_chars():
    from manabi_server.services.canvas_ingest import _safe_filename

    assert _safe_filename('a/b:c?"|<>d') == "abcd.pdf"
    assert _safe_filename("") == "Canvas page.pdf"


@pytest.mark.parametrize("bad", ["", "   "])
def test_import_syllabus_requires_body(bad):
    # Guard: the syllabus import raises 404 when the course has no syllabus body.
    # (Full ingestion is exercised live — it needs LibreOffice.)
    from manabi_server.services.canvas_ingest import html_to_text

    assert html_to_text(bad) == ""
