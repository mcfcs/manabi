"""Increment 8: boilerplate stripping, table rendering, Canvas import validation."""

import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from manabi_server.processing.pipeline import _strip_boilerplate
from manabi_server.processing.text_html import _table_html


def _synthetic_doc(pages: int = 10) -> list[dict]:
    """Each page: unique content line + copyright footer + 'Page N' footer."""
    elements = []
    for p in range(1, pages + 1):
        elements.append(
            {"page_no": p, "text": f"Unique lecture content for page {p} " * 3}
        )
        elements.append(
            {"page_no": p, "text": "©Copyright 2004-2021 Example University"}
        )
        elements.append({"page_no": p, "text": f"Page {p} of {pages}"})
    return elements


class TestStripBoilerplate:
    def test_repeating_footers_removed(self):
        out = _strip_boilerplate(_synthetic_doc())
        texts = [el["text"] for el in out]
        assert not any("Copyright" in t for t in texts)
        # 'Page 1 of 10' etc. normalize to the same key (digits -> #)
        assert not any(t.startswith("Page ") for t in texts)

    def test_content_survives(self):
        out = _strip_boilerplate(_synthetic_doc())
        content = [el for el in out if "Unique lecture content" in el["text"]]
        assert len(content) == 10

    def test_small_docs_untouched(self):
        elements = _synthetic_doc(pages=4)
        assert _strip_boilerplate(elements) == elements

    def test_long_repeated_lines_kept(self):
        # A paragraph repeated on every page is longer than the 80-char cap
        # and must never be treated as boilerplate.
        long_line = "This important definition is repeated on every page " * 3
        elements = [
            {"page_no": p, "text": t}
            for p in range(1, 11)
            for t in (long_line, f"filler {p}")
        ]
        out = _strip_boilerplate(elements)
        assert sum(1 for el in out if el["text"] == long_line) == 10

    def test_partial_repeats_kept(self):
        # Appears on 3/10 pages — below the 40% ratio.
        elements = _synthetic_doc()
        elements = [el for el in elements if "Copyright" not in el["text"]]
        for p in (1, 2, 3):
            elements.append({"page_no": p, "text": "Recap of last week"})
        out = _strip_boilerplate(elements)
        assert sum(1 for el in out if el["text"] == "Recap of last week") == 3


class TestTableHtml:
    def test_columns_and_data(self):
        html = _table_html(
            {
                "columns": ["Level", "Rate"],
                "data": [["DS-1", "1.544 Mbps"], ["DS-3", "44.736 Mbps"]],
            }
        )
        assert html is not None
        assert html.startswith("<table>")
        assert "<th>Level</th>" in html
        assert "<td>DS-1</td>" in html
        assert html.count("<tr>") == 3  # header + 2 rows

    def test_cells_escaped(self):
        html = _table_html({"columns": ["<b>x</b>"], "data": [["a < b"]]})
        assert "<b>" not in html
        assert "&lt;b&gt;x&lt;/b&gt;" in html
        assert "a &lt; b" in html

    def test_empty_and_malformed(self):
        assert _table_html({}) is None
        assert _table_html({"columns": None, "data": None}) is None
        assert _table_html({"data": "not-a-list"}) is None

    def test_headerless_table(self):
        html = _table_html({"columns": [], "data": [["only", "body"]]})
        assert "<th>" not in html
        assert "<td>only</td>" in html


class TestRepeatedKeys:
    def test_native_view_agrees_with_element_stripper(self):
        """The text-view path must classify the same lines as boilerplate."""
        from manabi_server.processing.text_html import repeat_key, repeated_keys

        per_page = {
            p: {repeat_key("©Copyright 2004-2021 Example U"), repeat_key(f"line {p}")}
            for p in range(1, 11)
        }
        keys = repeated_keys(per_page)
        assert repeat_key("©Copyright 2004-2021 Example U") in keys
        # 'line 1'…'line 10' also collapse (digits → #) — present on all pages
        assert repeat_key("line 1") in keys

    def test_small_docs_never_stripped(self):
        from manabi_server.processing.text_html import repeated_keys

        assert repeated_keys({1: {"x"}, 2: {"x"}, 3: {"x"}, 4: {"x"}}) == set()


class TestParseCache:
    def test_cache_hit_restores_types(self, tmp_path, monkeypatch):
        """JSON round-trip must restore int page keys and the pages set —
        and a cache hit must never touch Docling."""
        from manabi_server.processing import pipeline
        from manabi_server.storage import files

        monkeypatch.setattr(files, "storage_root", lambda: tmp_path)
        cache = pipeline._parse_cache_path("deadbeef")
        cache.parent.mkdir(parents=True)
        cache.write_text(
            json.dumps(
                {
                    "elements": [
                        {"type": "paragraph", "text": "hi", "page_no": 1, "bbox": None}
                    ],
                    "titles": {"2": "Intro"},
                    "pages": [1, 2],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            pipeline, "_get_converter", lambda: (_ for _ in ()).throw(AssertionError("cache miss"))
        )
        parsed = pipeline._docling_parse(Path("does-not-exist.pdf"), cache_key="deadbeef")
        assert parsed["titles"] == {2: "Intro"}
        assert parsed["pages"] == {1, 2}
        assert parsed["elements"][0]["text"] == "hi"


class TestCanvasImportValidation:
    async def test_rejects_non_document_extension(self, monkeypatch):
        """The import endpoint refuses anything that is not pdf/pptx before
        touching the network for the file body or the database."""
        from manabi_server.api import canvas

        async def fake_get(path, params=None):
            return {"url": "https://canvas.example/download", "display_name": "notes.zip"}

        monkeypatch.setattr(canvas, "_canvas_get", fake_get)

        class FakeModule:
            id = 1

        with pytest.raises(HTTPException) as exc:
            await canvas.canvas_import(
                canvas.ImportIn(file_id=42), module=FakeModule(), user=None, db=None
            )
        assert exc.value.status_code == 422

    async def test_rejects_wrong_magic_bytes(self, monkeypatch):
        """A file named .pdf whose bytes are not %PDF is refused (same magic
        check as manual uploads)."""
        from manabi_server.api import canvas

        async def fake_get(path, params=None):
            return {"url": "https://canvas.example/download", "display_name": "fake.pdf"}

        monkeypatch.setattr(canvas, "_canvas_get", fake_get)

        class FakeResponse:
            status_code = 200
            content = b"MZ\x90\x00 definitely not a pdf"

        class FakeClient:
            def __init__(self, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, **kw):
                return FakeResponse()

        monkeypatch.setattr(canvas.httpx, "AsyncClient", FakeClient)

        class FakeModule:
            id = 1

        with pytest.raises(HTTPException) as exc:
            await canvas.canvas_import(
                canvas.ImportIn(file_id=42), module=FakeModule(), user=None, db=None
            )
        assert exc.value.status_code == 422
        assert "does not look like" in exc.value.detail
