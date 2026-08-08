"""Structure-aware chunking (master plan §F). Pure functions — no DB, no IO.

PPTX: one chunk per slide (title + body + speaker notes); near-empty slides
merge into the next slide's chunk.
PDF: heading-bounded sections; oversized sections split at paragraph
boundaries, each piece prefixed with its heading path. Never fixed windows.
"""

import hashlib
from dataclasses import dataclass, field

MAX_CHUNK_TOKENS = 900
MIN_SLIDE_WORDS = 15
MIN_PDF_CHUNK_TOKENS = 60  # smaller fragments merge into the previous chunk
HEADING_TYPES = {"heading", "section_header", "title"}


@dataclass
class ElementIn:
    id: int
    page_no: int
    element_type: str
    text: str


@dataclass
class PageIn:
    page_no: int
    title: str | None = None
    speaker_notes: str | None = None


@dataclass
class ChunkOut:
    page_start: int
    page_end: int
    element_ids: list[int] = field(default_factory=list)
    heading_path: str | None = None
    text: str = ""

    @property
    def token_count(self) -> int:
        return approx_tokens(self.text)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def chunk_pptx(pages: list[PageIn], elements: list[ElementIn]) -> list[ChunkOut]:
    by_page: dict[int, list[ElementIn]] = {}
    for el in elements:
        by_page.setdefault(el.page_no, []).append(el)

    chunks: list[ChunkOut] = []
    carry: ChunkOut | None = None  # near-empty slide waiting to merge forward

    for page in sorted(pages, key=lambda p: p.page_no):
        els = by_page.get(page.page_no, [])
        parts: list[str] = []
        if page.title:
            parts.append(page.title)
        parts.extend(el.text for el in els if el.text and el.text != page.title)
        if page.speaker_notes:
            parts.append(f"[Speaker notes] {page.speaker_notes}")
        text = "\n".join(p.strip() for p in parts if p.strip())

        chunk = ChunkOut(
            page_start=page.page_no,
            page_end=page.page_no,
            element_ids=[el.id for el in els],
            heading_path=page.title,
            text=text,
        )
        if carry is not None:
            chunk = ChunkOut(
                page_start=carry.page_start,
                page_end=chunk.page_end,
                element_ids=carry.element_ids + chunk.element_ids,
                heading_path=carry.heading_path or chunk.heading_path,
                text=(carry.text + "\n" + chunk.text).strip(),
            )
            carry = None
        if len(chunk.text.split()) < MIN_SLIDE_WORDS:
            carry = chunk
            continue
        chunks.append(chunk)

    if carry is not None and carry.text.strip():
        if chunks:
            last = chunks[-1]
            chunks[-1] = ChunkOut(
                page_start=last.page_start,
                page_end=carry.page_end,
                element_ids=last.element_ids + carry.element_ids,
                heading_path=last.heading_path,
                text=(last.text + "\n" + carry.text).strip(),
            )
        else:
            chunks.append(carry)
    return [c for c in chunks if c.text.strip()]


def chunk_pdf(elements: list[ElementIn]) -> list[ChunkOut]:
    sections: list[tuple[str | None, list[ElementIn]]] = []
    current_heading: str | None = None
    current: list[ElementIn] = []
    for el in sorted(elements, key=lambda e: e.id):
        if el.element_type in HEADING_TYPES:
            if current:
                sections.append((current_heading, current))
            current_heading = el.text.strip() or current_heading
            current = [el]
        else:
            current.append(el)
    if current:
        sections.append((current_heading, current))

    chunks: list[ChunkOut] = []
    for heading, els in sections:
        body = [el for el in els if el.text and el.text.strip()]
        if not body:
            continue
        pieces = _split_by_tokens(body, MAX_CHUNK_TOKENS)
        for piece in pieces:
            prefix = f"{heading} — " if heading and len(pieces) > 1 else ""
            text = "\n".join(el.text.strip() for el in piece)
            chunks.append(
                ChunkOut(
                    page_start=min(el.page_no for el in piece),
                    page_end=max(el.page_no for el in piece),
                    element_ids=[el.id for el in piece],
                    heading_path=heading,
                    text=(prefix + text).strip(),
                )
            )
    return _merge_tiny_pdf_chunks([c for c in chunks if c.text.strip()])


def _merge_tiny_pdf_chunks(chunks: list[ChunkOut]) -> list[ChunkOut]:
    """Fold fragments (split remnants, stray lines) into the previous chunk."""
    merged: list[ChunkOut] = []
    for c in chunks:
        if merged and c.token_count < MIN_PDF_CHUNK_TOKENS:
            prev = merged[-1]
            merged[-1] = ChunkOut(
                page_start=prev.page_start,
                page_end=max(prev.page_end, c.page_end),
                element_ids=prev.element_ids + c.element_ids,
                heading_path=prev.heading_path,
                text=(prev.text + "\n" + c.text).strip(),
            )
        else:
            merged.append(c)
    return merged


def _split_by_tokens(elements: list[ElementIn], budget: int) -> list[list[ElementIn]]:
    pieces: list[list[ElementIn]] = []
    piece: list[ElementIn] = []
    used = 0
    for el in elements:
        cost = approx_tokens(el.text)
        if piece and used + cost > budget:
            pieces.append(piece)
            piece, used = [], 0
        piece.append(el)
        used += cost
    if piece:
        pieces.append(piece)
    return pieces
