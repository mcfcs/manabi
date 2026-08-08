from manabi_server.processing.chunking import (
    MAX_CHUNK_TOKENS,
    ChunkOut,
    ElementIn,
    PageIn,
    chunk_pdf,
    chunk_pptx,
)


def _el(id: int, page: int, etype: str, text: str) -> ElementIn:
    return ElementIn(id=id, page_no=page, element_type=etype, text=text)


def test_pptx_one_chunk_per_slide():
    pages = [
        PageIn(page_no=1, title="Intro", speaker_notes="welcome everyone"),
        PageIn(page_no=2, title="Cache basics"),
    ]
    elements = [
        _el(
            1,
            1,
            "paragraph",
            "This lecture covers memory hierarchies, caching strategies, and the "
            "performance implications of locality in modern computer architectures",
        ),
        _el(2, 2, "paragraph", "A cache hit occurs when requested data is already present"),
        _el(3, 2, "paragraph", "A cache miss requires fetching from main memory instead"),
    ]
    chunks = chunk_pptx(pages, elements)
    assert len(chunks) == 2
    assert chunks[0].page_start == 1 and chunks[0].page_end == 1
    assert "[Speaker notes] welcome everyone" in chunks[0].text
    assert chunks[1].heading_path == "Cache basics"
    assert chunks[1].element_ids == [2, 3]


def test_pptx_near_empty_slide_merges_forward():
    pages = [PageIn(page_no=1, title="Agenda"), PageIn(page_no=2, title="Content")]
    elements = [
        _el(1, 1, "paragraph", "Topics"),  # near-empty slide
        _el(2, 2, "paragraph", "The full content of this slide has plenty of words to stand alone"),
    ]
    chunks = chunk_pptx(pages, elements)
    assert len(chunks) == 1
    assert chunks[0].page_start == 1 and chunks[0].page_end == 2
    assert set(chunks[0].element_ids) == {1, 2}


def test_pdf_heading_bounded_sections():
    intro = "Computers execute instructions in sequence, fetching and decoding. " * 5
    memory = "Memory stores program data across several levels of hierarchy. " * 5
    elements = [
        _el(1, 1, "heading", "1. Introduction"),
        _el(2, 1, "paragraph", intro),
        _el(3, 2, "heading", "2. Memory"),
        _el(4, 2, "paragraph", memory),
        _el(5, 3, "paragraph", "It trades capacity against access latency at each level."),
    ]
    chunks = chunk_pdf(elements)
    assert len(chunks) == 2
    assert chunks[0].heading_path == "1. Introduction"
    assert chunks[1].heading_path == "2. Memory"
    assert chunks[1].page_start == 2 and chunks[1].page_end == 3


def test_pdf_oversized_section_splits_with_heading_prefix():
    big_paragraph = "word " * 800  # ~1000 approx-tokens each
    elements = [
        _el(1, 1, "heading", "3. Cache"),
        _el(2, 1, "paragraph", big_paragraph),
        _el(3, 2, "paragraph", big_paragraph),
    ]
    chunks = chunk_pdf(elements)
    assert len(chunks) >= 2
    for c in chunks:
        assert c.token_count <= MAX_CHUNK_TOKENS * 1.5  # single elements may overshoot
    # split pieces carry the heading path prefix in their text
    assert any(c.text.startswith("3. Cache — ") for c in chunks)
    assert all(c.heading_path == "3. Cache" for c in chunks)


def test_pdf_tiny_fragment_merges_into_previous():
    elements = [
        _el(1, 1, "heading", "1. Data Abstraction"),
        _el(2, 1, "paragraph", "Modules are better expressed as user-defined types. " * 20),
        _el(3, 2, "heading", "1. Data Abstraction"),  # repeated heading fragment
        _el(4, 2, "paragraph", "Short remnant line."),
    ]
    chunks = chunk_pdf(elements)
    assert len(chunks) == 1
    assert chunks[0].page_end == 2
    assert "Short remnant line." in chunks[0].text


def test_chunk_hash_stable():
    a = ChunkOut(page_start=1, page_end=1, element_ids=[1], text="same text")
    b = ChunkOut(page_start=2, page_end=2, element_ids=[9], text="same text")
    assert a.content_hash == b.content_hash
