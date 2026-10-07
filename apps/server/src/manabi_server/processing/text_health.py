"""Text-layer healing for parsed PDFs (pure functions, injectable I/O).

Some PDFs (journal typesetting with custom-encoded fonts, e.g. Wiley's
AdvP* faces) come out of Docling with the spaces between words missing —
"Itisnowwidelyacceptedthat" — and with typographic ligatures (ﬁ, ﬂ) left as
single glyphs. The same pages read cleanly through PyMuPDF's span layer.
Docling keeps a bbox per element, so a glued page can be healed by re-reading
each element's box from PyMuPDF; ligatures are folded everywhere.

Runs as post-processing in ``pipeline._stage_structure`` (after the parse
cache), so cached parses are healed on the next Retry too.
"""

from __future__ import annotations

import re
from collections.abc import Callable

# ── Ligatures ───────────────────────────────────────────────────────────────

_LIGATURES = str.maketrans(
    {
        "ﬀ": "ff",
        "ﬁ": "fi",
        "ﬂ": "fl",
        "ﬃ": "ffi",
        "ﬄ": "ffl",
        "ﬅ": "ft",
        "ﬆ": "st",
    }
)


def normalize_ligatures(text: str) -> str:
    """Fold the Latin typographic ligature code points into their letters."""
    return text.translate(_LIGATURES)


# ── Glue detection ──────────────────────────────────────────────────────────

GLUE_TOKEN_MIN_LEN = 19  # longer than any common English word
GLUE_PAGE_RATIO = 0.015  # share of tokens that must be glued to heal a page
GLUE_PAGE_MIN_TOKENS = 3  # ...or at least this many glued tokens

_EDGE_PUNCT = "\"'‘’“”()[]{}.,;:!?—–-*"
_ALPHA_WORD = re.compile(r"^[A-Za-z’'‘]+$")
# letters on both sides of a comma/period/semicolon/colon with no space:
# "reduction,aswell" / "matter.Nowhere" — never legitimate in prose
_INNER_PUNCT_GLUE = re.compile(r"[a-z]{2,}[,.;:][A-Za-z]{2,}")
_SKIP_TOKEN = re.compile(r"https?://|www\.|@|/|\\|\d")


def is_glued_token(token: str) -> bool:
    core = token.strip(_EDGE_PUNCT)
    if not core or _SKIP_TOKEN.search(core) or "-" in core:
        return False
    if len(core) >= GLUE_TOKEN_MIN_LEN and _ALPHA_WORD.match(core):
        return True
    return bool(_INNER_PUNCT_GLUE.search(core))


def glued_tokens(text: str) -> list[str]:
    return [t for t in text.split() if is_glued_token(t)]


def glue_ratio(text: str) -> float:
    tokens = text.split()
    if not tokens:
        return 0.0
    return sum(1 for t in tokens if is_glued_token(t)) / len(tokens)


def page_needs_healing(texts: list[str]) -> bool:
    joined = " ".join(t for t in texts if t)
    tokens = joined.split()
    if not tokens:
        return False
    glued = sum(1 for t in tokens if is_glued_token(t))
    return glued >= GLUE_PAGE_MIN_TOKENS or glued / len(tokens) > GLUE_PAGE_RATIO


# ── Line joining for text re-read from the PDF ──────────────────────────────

# A line-end hyphen is a real hyphen (keep) when the left part is one of these
# prefixes or the right part is capitalised; otherwise it is hyphenation (drop).
_HYPHEN_KEEP_PREFIXES = {
    "self",
    "non",
    "pre",
    "co",
    "post",
    "anti",
    "inter",
    "semi",
    "multi",
    "re",
    "pro",
    "sub",
    "cross",
    "ex",
    "de",
    "pseudo",
    "quasi",
    "socio",
    "neo",
    "well",
}


def join_hyphenated(left: str, right: str) -> str:
    """Join two consecutive lines where `left` ends with a hyphen."""
    left = left.rstrip()
    right = right.lstrip()
    stem = left[:-1]
    last_word = re.split(r"\s", stem)[-1] if stem else ""
    if (
        not right
        or not right[0].islower()
        or last_word.lower() in _HYPHEN_KEEP_PREFIXES
        or not last_word
    ):
        return stem + "-" + right
    return stem + right


def join_lines(text: str) -> str:
    """PyMuPDF clip text → one flowing paragraph: de-hyphenate line breaks,
    collapse whitespace, drop empty lines."""
    lines = [ln.strip() for ln in text.replace("\r", "").split("\n")]
    lines = [ln for ln in lines if ln]
    if not lines:
        return ""
    out = lines[0]
    for ln in lines[1:]:
        out = join_hyphenated(out, ln) if out.endswith("-") else out + " " + ln
    return re.sub(r"\s+", " ", out).strip()


# ── Healing ─────────────────────────────────────────────────────────────────

ClipText = Callable[[int, dict], str]  # (page_no, bbox{l,t,r,b}) -> raw text

HEAL_MIN_LETTER_RATIO = 0.6  # healed text must keep most of the letters...
HEAL_MAX_LETTER_RATIO = 1.6  # ...and not swallow neighbouring elements


def _letters(text: str) -> int:
    return sum(1 for ch in text if ch.isalpha())


def heal_elements(elements: list[dict], clip_text: ClipText | None) -> list[dict]:
    """Return elements with ligatures folded everywhere and, on pages whose
    Docling text is glued, each boxed text element re-read through
    `clip_text(page_no, bbox)`. Tables and figures are left alone. Returns the
    same list (mutated) for convenience."""
    for el in elements:
        if el.get("text"):
            el["text"] = normalize_ligatures(el["text"])
    if clip_text is None:
        return elements

    by_page: dict[int, list[dict]] = {}
    for el in elements:
        by_page.setdefault(int(el["page_no"]), []).append(el)

    for page_no, page_els in by_page.items():
        texts = [e.get("text") or "" for e in page_els if e.get("type") not in ("table", "figure")]
        if not page_needs_healing(texts):
            continue
        for el in page_els:
            if el.get("type") in ("table", "figure") or not el.get("bbox") or not el.get("text"):
                continue
            try:
                raw = clip_text(page_no, el["bbox"])
            except Exception:  # noqa: BLE001 — healing is best-effort
                continue
            healed = normalize_ligatures(join_lines(raw or ""))
            if not healed:
                continue
            before, after = _letters(el["text"]), _letters(healed)
            if before == 0:
                continue
            ratio = after / before
            if HEAL_MIN_LETTER_RATIO <= ratio <= HEAL_MAX_LETTER_RATIO:
                el["text"] = healed
                el["healed"] = True
    return elements


def pymupdf_clip_text(pdf_doc) -> ClipText:
    """ClipText backed by an open PyMuPDF document. Docling bboxes are in PDF
    points with a bottom-left origin (t > b); PyMuPDF wants top-left."""
    import pymupdf

    def clip(page_no: int, bbox: dict) -> str:
        page = pdf_doc[page_no - 1]
        height = page.rect.height
        top = height - float(bbox["t"])
        bottom = height - float(bbox["b"])
        rect = pymupdf.Rect(float(bbox["l"]), min(top, bottom), float(bbox["r"]), max(top, bottom))
        # a hair of tolerance so glyphs on the box edge are not cut
        rect = pymupdf.Rect(rect.x0 - 1, rect.y0 - 1, rect.x1 + 1, rect.y1 + 1)
        return page.get_text("text", clip=rect, sort=True)

    return clip
