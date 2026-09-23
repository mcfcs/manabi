"""Lossless text import, with deterministic reading pages shared by TTS and retrieval.

No PDF/OCR or scholarly-paper filtering: numbered clauses, references and
repeated provisions are all source material and must survive.
"""

import html
import re

MAX_TEXT_BYTES = 2 * 1024 * 1024
PAGE_CHARS = 6000
BLOCK_CHARS = 1800
_ROMAN_ARTICLES = dict(
    zip(
        (
            "I",
            "II",
            "III",
            "IV",
            "V",
            "VI",
            "VII",
            "VIII",
            "IX",
            "X",
            "XI",
            "XII",
            "XIII",
            "XIV",
            "XV",
            "XVI",
            "XVII",
            "XVIII",
            "XIX",
            "XX",
        ),
        range(1, 21),
        strict=True,
    )
)


def decode_text(content: bytes) -> str:
    if len(content) > MAX_TEXT_BYTES:
        raise ValueError("Text exceeds the 2 MB limit")
    encoding = "utf-16" if content.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    try:
        text = content.decode(encoding)
    except UnicodeError as exc:
        raise ValueError("Save the text file as UTF-8 or UTF-16 and try again") from exc
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if re.search(r"[\x00-\x08\x0b\x0e-\x1f\x7f]", text):
        raise ValueError("This file contains binary or unsupported control characters")
    if not text.strip():
        raise ValueError("Add some text before saving the material")
    return text


def text_pages(text: str) -> list[list[str]]:
    """Keep paragraph/line breaks; split long blocks only at whitespace if possible."""
    pages: list[list[str]] = [[]]
    size = 0
    for paragraph in re.split(r"\n[ \t]*\n|\f", text):
        rest = paragraph.strip()
        while rest:
            end = len(rest)
            if end > BLOCK_CHARS:
                breaks = list(re.finditer(r"\s+", rest[: BLOCK_CHARS + 1]))
                end = breaks[-1].start() if breaks else BLOCK_CHARS
            block, rest = rest[:end].strip(), rest[end:].strip()
            if pages[-1] and size + len(block) > PAGE_CHARS:
                pages.append([])
                size = 0
            pages[-1].append(block)
            size += len(block)
    return pages


def page_html(blocks: list[str]) -> str:
    return "".join("<p>" + html.escape(b).replace("\n", "<br>") + "</p>" for b in blocks)


def build_text_script(text: str):
    from manabi_server.processing.narration_script import Script, Segment
    from manabi_server.processing.spoken import ensure_stop, unshout

    segments = []
    for page_no, blocks in enumerate(text_pages(text), start=1):
        for block in blocks:
            # Preserve subsection numbers, dates and parenthetical clauses.
            # PDF narration's citation stripping would remove legitimate text.
            spoken = re.sub(r"\s+", " ", block).strip()
            spoken = re.sub(
                r"\bArticle\s+([IVX]+)\b",
                lambda m: (
                    "Article " + str(_ROMAN_ARTICLES[m[1].upper()])
                    if m[1].upper() in _ROMAN_ARTICLES
                    else m[0]
                ),
                spoken,
                flags=re.IGNORECASE,
            )
            segments.append(
                Segment(
                    ord=len(segments),
                    page_no=page_no,
                    kind="paragraph",
                    text=block,
                    spoken_text=ensure_stop(unshout(spoken)),
                )
            )
    return Script(segments=segments, blocks=[], body_size=0, body_font="", title=None, authors=None)
