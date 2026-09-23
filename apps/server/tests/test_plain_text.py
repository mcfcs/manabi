"""Text materials must keep all provisions through reading, retrieval and speech."""

import re
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, UploadFile
from manabi_core.models import DocElement, Document, DocumentKind, DocumentPage
from manabi_server.api import documents
from manabi_server.processing.pipeline import _stage_chunk, _stage_render, _stage_structure
from manabi_server.processing.plain_text import (
    MAX_TEXT_BYTES,
    PAGE_CHARS,
    build_text_script,
    decode_text,
    page_html,
    text_pages,
)
from manabi_server.services.narration import build_for_document, narratable, segment_rows

READING = (
    "ARTICLE VI\nThe Legislative Department\n\nSection 1. (1) First clause. [2]\n(2) Next clause."
)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "utf-16-be"])
def test_unicode_and_windows_newlines(encoding):
    text = "Article VII\r\nPeople’s rights — café"
    data = text.encode(encoding)
    if encoding == "utf-16-be":
        data = b"\xfe\xff" + data
    assert decode_text(data) == text.replace("\r\n", "\n")


@pytest.mark.parametrize("data", [b"", b" \r\n\t", b"a\0b", b"\xffbroken", b"a\x07b"])
def test_reject_empty_binary_or_invalid_encoding(data):
    with pytest.raises(ValueError):
        decode_text(data)


def test_reject_oversized_text():
    with pytest.raises(ValueError, match="2 MB"):
        decode_text(b"a" * (MAX_TEXT_BYTES + 1))


def test_html_is_plain_text_and_preserves_line_breaks():
    assert page_html(["<script>alert(1)</script>\nA & B"]) == (
        "<p>&lt;script&gt;alert(1)&lt;/script&gt;<br>A &amp; B</p>"
    )


def test_long_reading_retains_all_words_and_narration_page_anchors():
    source = (READING + "\n\nReferences\n\n(1987) This must still be read.\n\n") * 120
    pages = text_pages(source)
    assert len(pages) > 1
    assert all(sum(map(len, blocks)) <= PAGE_CHARS for blocks in pages)
    assert " ".join(b for blocks in pages for b in blocks).split() == source.split()
    segments = segment_rows(build_text_script(source))
    assert [s["ord"] for s in segments] == list(range(len(segments)))
    assert [s["page_no"] for s in segments] == [
        no for no, blocks in enumerate(pages, 1) for _ in blocks
    ]
    spoken = " ".join(s["spoken_text"] for s in segments)
    assert spoken.count("(1987)") == 120
    assert spoken.count("(1)") == 120
    assert spoken.count("[2]") == 120
    assert "Article 6" in spoken
    assert "References" in spoken


def test_single_giant_paragraph_is_not_truncated():
    source = "provision " * 10000
    blocks = [b for page in text_pages(source) for b in page]
    assert " ".join(blocks).split() == source.split()
    assert len(text_pages(source)) > 1


def test_article_numbers_are_spoken_without_changing_display():
    script = build_text_script("ARTICLE VII\n\nArticle XVIII. Section 2. (1) A clause.")
    assert script.segments[0].text == "ARTICLE VII"
    assert script.segments[0].spoken_text == "Article 7."
    assert "Article 18. Section 2. (1)" in script.segments[1].spoken_text


def test_text_pipeline_and_narration_share_source(monkeypatch, tmp_path):
    path = tmp_path / "reading.txt"
    path.write_text(READING, encoding="utf-8")
    monkeypatch.setattr(documents.files, "resolve", lambda _: path)
    doc = Document(
        id=1, module_id=2, kind=DocumentKind.txt, storage_path="reading.txt", processing_mode="full"
    )
    db = MagicMock()
    rows = []

    def add(row):
        row.id = len(rows) + 1
        rows.append(row)

    db.add.side_effect = add
    _stage_structure(db, doc)
    pages = [r for r in rows if isinstance(r, DocumentPage)]
    elements = [r for r in rows if isinstance(r, DocElement)]
    assert doc.page_count == len(pages) == 1
    assert "Section 1. (1)" in pages[0].text_html
    assert " ".join(e.text_content for e in elements).split() == READING.split()
    assert all(e.page_id == pages[0].id for e in elements)
    db.execute.return_value.scalars.return_value.all.side_effect = [pages, elements]
    _stage_chunk(db, doc)
    chunks = [r for r in rows if not isinstance(r, (DocumentPage, DocElement))]
    assert chunks and "Section 1. (1)" in " ".join(c.text for c in chunks)
    _stage_render(db, doc, None)  # Must never open the TXT as a PDF.
    assert narratable(doc)
    script = build_for_document(doc)
    assert " ".join(s.text for s in script.segments).split() == READING.split()
    doc.processing_mode = "render_only"
    assert not narratable(doc)


@pytest.mark.asyncio
async def test_upload_uses_existing_module_and_queue(monkeypatch):
    doc = Document(id=7, module_id=2, kind=DocumentKind.txt, filename="law.txt")
    ingest = AsyncMock(return_value=(doc, SimpleNamespace(id=9)))
    monkeypatch.setattr(documents, "ingest_bytes", ingest)
    monkeypatch.setattr(documents, "_doc_out", lambda doc, job_id: (doc, job_id))
    db = AsyncMock()
    module, user = SimpleNamespace(id=2), SimpleNamespace(id=1)
    result = await documents.upload_document(
        UploadFile(filename="law.TXT", file=BytesIO(READING.encode())),
        processing_mode="full",
        module=module,
        user=user,
        db=db,
    )
    assert result == (doc, 9)
    assert ingest.call_args.args == (db, user, module)
    assert ingest.call_args.kwargs["content"] == READING.encode()
    assert ingest.call_args.kwargs["ext"] == "txt"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingest_stores_original_text_and_enqueues(monkeypatch, tmp_path):
    monkeypatch.setattr(
        documents.files, "get_settings", lambda: SimpleNamespace(file_storage_root=str(tmp_path))
    )
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.return_value = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    enqueue = AsyncMock(return_value=SimpleNamespace(id=9))
    monkeypatch.setattr(documents, "_enqueue_processing", enqueue)
    doc, job = await documents.ingest_bytes(
        db,
        SimpleNamespace(id=1),
        SimpleNamespace(id=2),
        filename="reading.txt",
        ext="txt",
        content=READING.encode(),
    )
    assert doc.kind == DocumentKind.txt and doc.module_id == 2
    assert documents.files.resolve(doc.storage_path).read_bytes() == READING.encode()
    assert doc.storage_path.endswith(".txt")
    enqueue.assert_awaited_once_with(db, 1, doc)
    assert job.id == 9


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data,status",
    [(b" ", 422), (b"\0binary", 422), (b"x" * (MAX_TEXT_BYTES + 1), 413)],
    ids=["empty", "binary", "oversized"],
)
async def test_invalid_upload_never_stores_or_queues(data, status, monkeypatch):
    write = MagicMock()
    monkeypatch.setattr(documents.files, "write_atomic", write)
    with pytest.raises(HTTPException) as error:
        await documents.ingest_bytes(
            AsyncMock(),
            SimpleNamespace(id=1),
            SimpleNamespace(id=2),
            filename="bad.txt",
            ext="txt",
            content=data,
        )
    assert error.value.status_code == status
    write.assert_not_called()


@pytest.mark.asyncio
async def test_reader_does_not_merge_numbered_clauses():
    db = AsyncMock()
    db.execute.return_value = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = [
        "<p>Section 1</p>",
        "<p>(1) first</p><p>(2) second</p>",
    ]
    out = await documents.document_reader(SimpleNamespace(kind=DocumentKind.txt, id=1), db)
    assert len(re.findall("<p>", out.html)) == 3
