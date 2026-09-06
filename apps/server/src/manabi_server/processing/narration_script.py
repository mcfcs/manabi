"""Layout-aware narration script for a PDF (PyMuPDF, no model).

Reads the PDF's span layer directly (font size, face and position per block)
to decide what a narrator reads and what they skip:

- running headers / footers / page numbers (position + repetition),
- footnotes (small type, low on the page, numbered),
- the bibliography (everything after a References-style heading),
- front matter (affiliations, correspondence, journal line, keywords),

while keeping the title, the authors, the abstract, headings (as short
announcements) and the body. Run-in subheadings ("2.1.1 Formal and informal
institutions It is common…") are split off their paragraph, and a paragraph
that continues across a page break is merged back into one. Each kept block
becomes a Segment whose ``spoken_text`` comes from ``spoken.to_spoken``.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from manabi_server.processing.spoken import humanize_names, to_spoken, word_count
from manabi_server.processing.text_health import join_lines, normalize_ligatures
from manabi_server.processing.text_html import repeat_key

HEADER_TOP = 0.075  # a block that STARTS within the top 7.5% of the page
FOOTER_TOP = 0.86  # a block that starts within the bottom 14%
FOOTNOTE_ZONE = 0.55  # footnotes live in the lower part of the page
SUPERSCRIPT_RATIO = 0.75  # spans this much smaller than body are markers
SMALL_DELTA = 0.6  # body_size - this = "small type"
LARGE_DELTA = 1.5  # body_size + this = "display type"
REPEAT_PAGE_RATIO = 0.4
MAX_HEADING_CHARS = 120
MAX_RUNIN_WORDS = 14

KEPT_KINDS = ("title", "author", "abstract", "heading", "paragraph", "caption")
SKIPPED_KINDS = ("header", "footer", "footnote", "front_matter", "reference", "boilerplate", "junk")

_REFERENCE_HEADINGS = re.compile(
    r"^(?:\d+\.?\s*)?(references?|bibliography|works cited|reference list|sources|"
    r"literature cited|notes and references|endnotes|notes)\s*:?$",
    re.IGNORECASE,
)
_FOOTNOTE_START = re.compile(r"^(?:\d{1,2}|[*†‡§¶])\s?\S")
_CAPTION = re.compile(r"^(?:Figure|Fig\.|Table|Chart|Box|Plate|Exhibit)\s*\d+", re.IGNORECASE)
_FRONT_MATTER = re.compile(
    r"^(?:\*?\s*Correspondence|Keywords?\s*:|Key\s?words\s*:|Copyright|©|Journal of|"
    r"E-?mail|Received|Accepted|Published online|DOI\b|doi:|JEL\b|Citation:|How to cite|"
    r"This article|Downloaded from|All rights reserved|ISSN|ISBN|Vol\.|Volume\s\d)",
    re.IGNORECASE,
)
_AFFILIATION = re.compile(
    r"\b(University|Institute|Department|School of|College|Faculty|Centre|Center|Laboratory|"
    r"Ministry|Bank|Foundation|Programme|Program\b)",
    re.IGNORECASE,
)
_ABSTRACT = re.compile(r"^(?:abstract|summary)\s*[:.—–-]?\s*", re.IGNORECASE)
_CITATION_LINE = re.compile(r"^[A-Z][\w'’-]+,?\s+[A-Z]{1,3}[,.].*\b(?:19|20)\d{2}\b")
_NUMBERED = re.compile(r"^\d+(?:\.\d+)+\.?\s")
_PAGE_NUMBERISH = re.compile(r"^\d{1,4}$|^\d{1,4}\s|\s\d{1,4}$")
_TERMINAL = ".?!:;\"'”’)"


@dataclass
class Span:
    text: str
    size: float
    font: str
    flags: int


@dataclass
class Line:
    spans: list[Span]
    bbox: tuple[float, float, float, float]

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", "".join(s.text for s in self.spans)).strip()


@dataclass
class Block:
    page_no: int
    page_height: float
    bbox: tuple[float, float, float, float]
    lines: list[Line]
    kind: str = "paragraph"
    merged_from: list[int] = field(default_factory=list)  # page numbers folded in

    @property
    def text(self) -> str:
        return join_lines("\n".join(ln.text for ln in self.lines))

    @property
    def size(self) -> float:
        counts: Counter[float] = Counter()
        for ln in self.lines:
            for s in ln.spans:
                counts[round(s.size, 1)] += len(s.text.strip())
        return counts.most_common(1)[0][0] if counts else 0.0

    @property
    def font(self) -> str:
        counts: Counter[str] = Counter()
        for ln in self.lines:
            for s in ln.spans:
                counts[s.font] += len(s.text.strip())
        return counts.most_common(1)[0][0] if counts else ""

    @property
    def rel_top(self) -> float:
        return self.bbox[1] / self.page_height if self.page_height else 0.0

    @property
    def rel_bottom(self) -> float:
        return self.bbox[3] / self.page_height if self.page_height else 0.0


@dataclass
class Segment:
    ord: int
    page_no: int
    kind: str
    text: str
    spoken_text: str


@dataclass
class Script:
    segments: list[Segment]
    blocks: list[Block]
    body_size: float
    body_font: str
    title: str | None
    authors: str | None

    def counts(self) -> dict[str, int]:
        return dict(Counter(b.kind for b in self.blocks))


# ── 1. Layout extraction ───────────────────────────────────────────────────


def _body_metrics(pages: list[list[Block]]) -> tuple[float, str]:
    sizes: Counter[float] = Counter()
    fonts: Counter[str] = Counter()
    for blocks in pages:
        for b in blocks:
            for ln in b.lines:
                for s in ln.spans:
                    sizes[round(s.size, 1)] += len(s.text.strip())
    body_size = sizes.most_common(1)[0][0] if sizes else 10.0
    for blocks in pages:
        for b in blocks:
            for ln in b.lines:
                for s in ln.spans:
                    if abs(round(s.size, 1) - body_size) < SMALL_DELTA:
                        fonts[s.font] += len(s.text.strip())
    body_font = fonts.most_common(1)[0][0] if fonts else ""
    return body_size, body_font


def extract_layout(pdf_doc) -> list[list[Block]]:
    """Per page: text blocks with their lines and spans (PyMuPDF dict mode)."""
    pages: list[list[Block]] = []
    for pno, page in enumerate(pdf_doc, start=1):
        height = float(page.rect.height)
        blocks: list[Block] = []
        for b in page.get_text("dict").get("blocks", []):
            if b.get("type") != 0:
                continue
            lines: list[Line] = []
            for ln in b.get("lines", []):
                spans = [
                    Span(
                        text=normalize_ligatures(s.get("text", "")),
                        size=float(s.get("size", 0.0)),
                        font=str(s.get("font", "")),
                        flags=int(s.get("flags", 0)),
                    )
                    for s in ln.get("spans", [])
                ]
                if any(s.text.strip() for s in spans):
                    lines.append(Line(spans=spans, bbox=tuple(ln["bbox"])))
            if lines:
                blocks.append(
                    Block(page_no=pno, page_height=height, bbox=tuple(b["bbox"]), lines=lines)
                )
        pages.append(blocks)
    return pages


def _drop_superscripts(pages: list[list[Block]], body_size: float) -> None:
    """Footnote markers / daggers: tiny spans of 1–3 characters."""
    limit = body_size * SUPERSCRIPT_RATIO
    for blocks in pages:
        for b in blocks:
            for ln in b.lines:
                ln.spans = [
                    s
                    for s in ln.spans
                    if not (s.size < limit and len(s.text.strip()) <= 3 and s.text.strip())
                ]


# ── 2. Classification ──────────────────────────────────────────────────────


def _repeated_short_keys(pages: list[list[Block]]) -> set[str]:
    if len(pages) < 5:
        return set()
    per_page: list[set[str]] = []
    for blocks in pages:
        keys = set()
        for b in blocks:
            t = b.text
            if 0 < len(t) <= 80:
                keys.add(repeat_key(t))
        per_page.append(keys)
    counts: Counter[str] = Counter(k for keys in per_page for k in keys)
    return {k for k, c in counts.items() if c / len(pages) >= REPEAT_PAGE_RATIO}


def _is_heading(b: Block, body_size: float, body_font: str) -> bool:
    t = b.text
    if not t or len(t) > MAX_HEADING_CHARS or len(b.lines) > 3:
        return False
    if t[-1] in ".,;" or t[0].islower():
        return False
    large = b.size >= body_size + LARGE_DELTA
    boldish = b.font != body_font and b.size >= body_size - SMALL_DELTA
    return large or boldish


def _split_runin_heading(b: Block, body_size: float, body_font: str) -> tuple[Block, Block] | None:
    """A subheading set in the heading face at the start of a body paragraph
    ("2.1.1 Formal and informal institutions It is common for…"): return
    (heading block, remaining paragraph block) or None."""
    if len(b.lines) < 2 or abs(b.size - body_size) >= SMALL_DELTA:
        return None

    def _heading_face(line: Line) -> bool:
        words = [s for s in line.spans if s.text.strip()]
        return bool(words) and all(s.font != body_font for s in words)

    # Whole leading lines set in the heading face ("2.1.1" / "Formal and
    # informal institutions"), at most three of them.
    head_lines: list[Line] = []
    for ln in b.lines[:3]:
        if _heading_face(ln):
            head_lines.append(ln)
        else:
            break
    rest_lines = b.lines[len(head_lines) :]
    if not head_lines:
        # Inline run-in: the heading face only at the start of the first line.
        first = b.lines[0]
        head_spans: list[Span] = []
        rest_spans: list[Span] = []
        for s in first.spans:
            if not rest_spans and (s.font != body_font or not s.text.strip()):
                head_spans.append(s)
            else:
                rest_spans.append(s)
        if not rest_spans or not any(s.text.strip() for s in head_spans):
            return None
        head_lines = [Line(head_spans, first.bbox)]
        rest_lines = [Line(rest_spans, first.bbox), *b.lines[1:]]
    if not rest_lines or not any(ln.text for ln in rest_lines):
        return None
    head_text = re.sub(r"\s+", " ", " ".join(ln.text for ln in head_lines)).strip()
    words = word_count(head_text)
    if words == 0 or words > MAX_RUNIN_WORDS or head_text[-1] in ".,;":
        return None
    if not (_NUMBERED.match(head_text) or head_text[0].isupper()):
        return None
    heading = Block(b.page_no, b.page_height, b.bbox, head_lines, "heading")
    rest = Block(b.page_no, b.page_height, b.bbox, rest_lines, "paragraph")
    return heading, rest


def classify(pages: list[list[Block]]) -> tuple[list[Block], float, str]:
    body_size, body_font = _body_metrics(pages)
    _drop_superscripts(pages, body_size)
    repeats = _repeated_short_keys(pages)

    ordered: list[Block] = []
    in_references = False
    seen_body_on_page1 = False
    seen_abstract = False
    for pno, blocks in enumerate(pages, start=1):
        blocks = sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0]))
        last_body_bottom = max(
            (
                b.bbox[3]
                for b in blocks
                if abs(b.size - body_size) < SMALL_DELTA and b.rel_top < FOOTER_TOP
            ),
            default=0.0,
        )
        for b in blocks:
            t = b.text
            small = b.size <= body_size - SMALL_DELTA
            large = b.size >= body_size + LARGE_DELTA
            key = repeat_key(t) if len(t) <= 80 else None
            short = len(b.lines) <= 4

            if not t or word_count(t) == 0:
                b.kind = "junk"
            elif b.rel_top <= HEADER_TOP and short and not large:
                b.kind = "header"
            elif key in repeats:
                b.kind = "boilerplate"
            elif b.rel_top >= FOOTER_TOP and short and (small or _PAGE_NUMBERISH.search(t)):
                b.kind = "footer"
            elif _is_heading(b, body_size, body_font) and not small:
                if _REFERENCE_HEADINGS.match(t):
                    in_references = True
                    b.kind = "reference"
                else:
                    in_references = False  # an appendix after the references resumes
                    b.kind = "title" if (pno == 1 and large) else "heading"
            elif in_references:
                b.kind = "reference"
            elif _FRONT_MATTER.match(t) and (pno == 1 or small):
                b.kind = "front_matter"
            elif pno == 1 and _ABSTRACT.match(t) and not seen_abstract:
                b.kind = "abstract"
                seen_abstract = True
            elif (
                small
                and b.rel_top >= FOOTNOTE_ZONE
                and (_FOOTNOTE_START.match(t) or b.bbox[1] >= last_body_bottom)
            ):
                b.kind = "footnote"
            elif pno == 1 and small and not seen_body_on_page1:
                # between title and body: the author line, then affiliations
                if (
                    not any(x.kind == "author" for x in ordered)
                    and not _AFFILIATION.search(t)
                    and word_count(t) <= 16
                ):
                    b.kind = "author"
                else:
                    b.kind = "front_matter"
            elif _CAPTION.match(t):
                b.kind = "caption"
            elif not in_references and _looks_like_bibliography_page(blocks, body_size):
                b.kind = "reference"
            else:
                split = _split_runin_heading(b, body_size, body_font)
                if split:
                    heading, rest = split
                    ordered.append(heading)
                    b = rest
                b.kind = "paragraph"
                if pno == 1 and not small:
                    seen_body_on_page1 = True
            ordered.append(b)
    return ordered, body_size, body_font


def _looks_like_bibliography_page(blocks: list[Block], body_size: float) -> bool:
    """Fallback when no References heading exists: a page whose text blocks are
    mostly citation-shaped ("Author X. 2004. Title…")."""
    texts = [b.text for b in blocks if b.text and b.size <= body_size + SMALL_DELTA]
    if len(texts) < 4:
        return False
    hits = sum(1 for t in texts if _CITATION_LINE.match(t))
    return hits / len(texts) >= 0.6


# ── 3. Assembly ────────────────────────────────────────────────────────────


def _previous_kept(out: list[Block]) -> Block | None:
    """The last block a narrator would read, looking past skipped ones."""
    for b in reversed(out):
        if b.kind in SKIPPED_KINDS:
            continue
        return b
    return None


def _merge_continuations(blocks: list[Block]) -> list[Block]:
    """Fold a paragraph that continues across a block/page break (past any
    footers, headers or footnotes in between) into the previous paragraph:
    the previous lacks terminal punctuation and the next starts lowercase, or
    the previous ends with a hyphen."""
    out: list[Block] = []
    for b in blocks:
        if b.kind == "paragraph":
            prev = _previous_kept(out)
            if prev is not None and prev.kind == "paragraph":
                pt, nt = prev.text, b.text
                if (
                    pt
                    and nt
                    and (pt.endswith("-") or (pt[-1] not in _TERMINAL and nt[0].islower()))
                ):
                    prev.lines.extend(b.lines)
                    prev.merged_from.append(b.page_no)
                    continue
        out.append(b)
    return out


def _title_and_authors(blocks: list[Block]) -> tuple[str | None, str | None]:
    titles = [b.text for b in blocks if b.kind == "title"]
    title = " ".join(titles).strip() or None
    author_block = next((b for b in blocks if b.kind == "author"), None)
    authors = None
    if author_block:
        a = re.sub(r"[\d*†‡§]+", " ", author_block.text)
        a = re.sub(r"\s+", " ", a).strip(" ,;")
        a = re.sub(r"\s,", ",", a)
        authors = humanize_names(to_spoken(a, "heading").rstrip(".")) if a else None
    return title, authors


def build_script(pdf_doc) -> Script:
    pages = extract_layout(pdf_doc)
    ordered, body_size, body_font = classify(pages)
    merged = _merge_continuations(ordered)
    title, authors = _title_and_authors(merged)

    segments: list[Segment] = []
    if title:
        intro = to_spoken(title, "title")
        if authors:
            intro = intro.rstrip(".") + ". By " + authors + "."
        shown = title + (f" — {authors}" if authors else "")
        segments.append(Segment(0, 1, "title", shown, intro))
    for b in merged:
        if b.kind not in ("abstract", "heading", "paragraph", "caption"):
            continue
        text = b.text
        if b.kind == "abstract":
            spoken = "Abstract. " + to_spoken(_ABSTRACT.sub("", text), "paragraph")
        else:
            spoken = to_spoken(text, b.kind)
        if word_count(spoken) == 0 or (b.kind != "heading" and word_count(spoken) < 3):
            continue  # stray fragments (page numbers that slipped through, etc.)
        segments.append(Segment(len(segments), b.page_no, b.kind, text, spoken))
    return Script(
        segments=segments,
        blocks=merged,
        body_size=body_size,
        body_font=body_font,
        title=title,
        authors=authors,
    )


def build_script_from_path(pdf_path: str) -> Script:
    import pymupdf

    with pymupdf.open(pdf_path) as doc:
        return build_script(doc)
