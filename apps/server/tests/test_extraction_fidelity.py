"""Extraction fidelity (2026-10-08 audit): partial Docling parses, code
listings, Symbol-font glyphs, table headers, oversized elements."""

from types import SimpleNamespace

import pytest

from manabi_server.processing import chunking, pipeline
from manabi_server.processing.text_health import (
    code_lines_from_dict,
    fix_split_escapes,
    looks_like_code,
    normalize_code,
    normalize_ligatures,
)

# ── Partial Docling conversions ─────────────────────────────────────────────


def _pdf(tmp_path, pages: list[str]):
    import pymupdf

    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=11)
    path = tmp_path / "doc.pdf"
    doc.save(str(path))
    return path


class _FakeItem:
    def __init__(self, text: str, page_no: int):
        self.label = "text"
        self.text = text
        self.prov = [SimpleNamespace(page_no=page_no, bbox=None)]


class _FakeConverter:
    """First call: PARTIAL_SUCCESS with only page 1. Page retries: nothing."""

    def __init__(self):
        self.calls: list[dict] = []

    def convert(self, source, **kwargs):
        self.calls.append(kwargs)
        items = [] if kwargs.get("page_range") else [(_FakeItem("Page one words here.", 1), 0)]
        return SimpleNamespace(
            status=SimpleNamespace(value="partial_success"),
            errors=[SimpleNamespace(page_no=2)],
            document=SimpleNamespace(iterate_items=lambda items=items: iter(items)),
        )


def test_a_page_docling_dropped_is_retried_then_filled_from_the_pdf(tmp_path, monkeypatch):
    path = _pdf(
        tmp_path,
        [
            "Page one words here.",
            "Page two has many words that Docling silently dropped from its output today.",
        ],
    )
    fake = _FakeConverter()
    monkeypatch.setattr(pipeline, "_get_converter", lambda full_page_ocr=False: fake)
    monkeypatch.setattr(pipeline.files, "storage_root", lambda: tmp_path)

    out = pipeline._docling_parse(path, cache_key="abc")

    pages = {el["page_no"] for el in out["elements"] if el["text"].strip()}
    assert pages == {1, 2}
    page2 = [el for el in out["elements"] if el["page_no"] == 2]
    assert page2 and page2[0].get("fallback") is True
    assert "silently dropped" in page2[0]["text"]
    # page 2 was retried on its own before falling back
    assert any(c.get("page_range") == (2, 2) for c in fake.calls)
    # a parse with an unrecovered Docling failure is never cached
    assert not list((tmp_path / "parse-cache").glob("*.json"))


def test_coverage_gaps_flag_pages_missing_most_of_their_words():
    gaps = pipeline.page_coverage_gaps({1: 100, 2: 3}, {1: 110, 2: 200, 3: 4})
    assert gaps == [(2, 3, 200)]


# ── Code listings ───────────────────────────────────────────────────────────


def test_code_is_recognised_and_prose_is_not():
    assert looks_like_code('int x = 5;\nprintf("%d", x);')
    assert looks_like_code("cout << x << endl;")
    assert not looks_like_code("The set { a, b } is finite; it has two members.")
    assert not looks_like_code("Pointers hold addresses.")


def test_code_quotes_and_split_escapes_are_repaired():
    assert fix_split_escapes(r"printf('%d \ n', x);") == r"printf('%d \n', x);"
    fixed = normalize_code("printf( “%d pesos\\ n”, x );")
    assert fixed == 'printf( "%d pesos\\n", x );'


def test_a_code_listing_keeps_its_lines_and_indentation():
    def span(x0, y0, text, w=6.0):
        return {"text": text, "bbox": (x0, y0, x0 + w * len(text), y0 + 10)}

    data = {
        "blocks": [
            {
                "type": 0,
                "lines": [
                    {"spans": [span(10, 0, "if (top < MAX) {")]},
                    {"spans": [span(34, 14, "Store[top++] = x;")]},
                    {"spans": [span(10, 28, "}")]},
                ],
            }
        ]
    }
    text = code_lines_from_dict(data)
    assert text.split("\n") == ["if (top < MAX) {", "    Store[top++] = x;", "}"]


def test_code_elements_become_one_fenced_block_in_a_chunk():
    els = [
        chunking.ElementIn(id=1, page_no=1, element_type="paragraph", text="A push routine:"),
        chunking.ElementIn(id=2, page_no=1, element_type="code", text="void push(char x) {"),
        chunking.ElementIn(id=3, page_no=1, element_type="code", text="    Store[top++] = x;\n}"),
        chunking.ElementIn(id=4, page_no=1, element_type="paragraph", text="It never checks."),
    ]
    [chunk] = chunking.chunk_pdf(els)
    assert "```\nvoid push(char x) {\n    Store[top++] = x;\n}\n```" in chunk.text
    assert chunk.text.index("A push routine") < chunk.text.index("```")


# ── Symbols, tables, oversized elements ─────────────────────────────────────


def test_symbol_font_glyphs_become_real_unicode():
    assert normalize_ligatures("An alphabet  is finite") == "An alphabet Σ is finite"
    assert normalize_ligatures("S  i = E") == "S → i = E"
    assert normalize_ligatures("x  A,  done") == "x ∈ A, ⇒ done"


def test_pandas_index_headers_and_duplicate_rows_are_dropped():
    table = {"columns": [0, 1, 2], "data": [["a", "b", "c"], ["a", "b", "c"], ["d", "", ""]]}
    assert pipeline._linearize_table(table) == "a | b | c\nd"


def test_a_vertical_tab_is_a_line_break():
    from manabi_server.processing.text_html import sanitize

    assert sanitize("E → E + T\x0bT → T * F") == "E → E + T\nT → T * F"


@pytest.mark.parametrize("code", [False, True])
def test_one_huge_element_is_split_under_the_chunk_budget(code):
    sentence = ("int x = 1;\n" if code else "This is a fairly ordinary sentence. ") * 600
    els = [
        chunking.ElementIn(
            id=1, page_no=1, element_type="code" if code else "paragraph", text=sentence
        )
    ]
    chunks = chunking.chunk_pdf(els)
    assert len(chunks) > 1
    assert all(chunking.approx_tokens(c.text) <= chunking.MAX_CHUNK_TOKENS + 40 for c in chunks)
