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
    """Fold the Latin typographic ligature code points into their letters, and
    map Symbol-font private-use glyphs (U+F0xx) to the real Unicode symbols."""
    text = text.translate(_LIGATURES)
    if _PUA_ANY.search(text):
        text = fold_symbol_pua(text)
    return text


# ── Symbol-font private-use glyphs ─────────────────────────────────────────
# PowerPoint/Word set math in the "Symbol" font; its glyphs reach the text
# layer as U+F000 + <Adobe Symbol code> ("An alphabet  is…" for Σ,
# "S  i" for "S → i"), which neither an LLM nor TTS can read. Map them
# via the standard Adobe Symbol encoding. Codes whose Symbol meaning is
# commonly wrong in practice (Wingdings shares the same PUA block: ™/®/©,
# card suits, bracket-building pieces) are left untouched.
_SYMBOL_ENCODING: dict[int, str] = {
    0x20: " ", 0x21: "!", 0x22: "∀", 0x23: "#", 0x24: "∃", 0x25: "%", 0x26: "&",
    0x27: "∋", 0x28: "(", 0x29: ")", 0x2A: "∗", 0x2B: "+", 0x2C: ",", 0x2D: "−",
    0x2E: ".", 0x2F: "/",
    **{0x30 + d: str(d) for d in range(10)},
    0x3A: ":", 0x3B: ";", 0x3C: "<", 0x3D: "=", 0x3E: ">", 0x3F: "?", 0x40: "≅",
    0x41: "Α", 0x42: "Β", 0x43: "Χ", 0x44: "Δ", 0x45: "Ε", 0x46: "Φ", 0x47: "Γ",
    0x48: "Η", 0x49: "Ι", 0x4A: "ϑ", 0x4B: "Κ", 0x4C: "Λ", 0x4D: "Μ", 0x4E: "Ν",
    0x4F: "Ο", 0x50: "Π", 0x51: "Θ", 0x52: "Ρ", 0x53: "Σ", 0x54: "Τ", 0x55: "Υ",
    0x56: "ς", 0x57: "Ω", 0x58: "Ξ", 0x59: "Ψ", 0x5A: "Ζ", 0x5B: "[", 0x5C: "∴",
    0x5D: "]", 0x5E: "⊥", 0x5F: "_",
    0x61: "α", 0x62: "β", 0x63: "χ", 0x64: "δ", 0x65: "ε", 0x66: "φ", 0x67: "γ",
    0x68: "η", 0x69: "ι", 0x6A: "ϕ", 0x6B: "κ", 0x6C: "λ", 0x6D: "μ", 0x6E: "ν",
    0x6F: "ο", 0x70: "π", 0x71: "θ", 0x72: "ρ", 0x73: "σ", 0x74: "τ", 0x75: "υ",
    0x76: "ϖ", 0x77: "ω", 0x78: "ξ", 0x79: "ψ", 0x7A: "ζ", 0x7B: "{", 0x7C: "|",
    0x7D: "}", 0x7E: "∼",
    0xA1: "ϒ", 0xA2: "′", 0xA3: "≤", 0xA4: "⁄", 0xA5: "∞", 0xA6: "ƒ",
    0xAB: "↔", 0xAC: "←", 0xAD: "↑", 0xAE: "→", 0xAF: "↓",
    0xB0: "°", 0xB1: "±", 0xB2: "″", 0xB3: "≥", 0xB4: "×", 0xB5: "∝", 0xB6: "∂",
    0xB7: "•", 0xB8: "÷", 0xB9: "≠", 0xBA: "≡", 0xBB: "≈", 0xBC: "…", 0xBF: "↵",
    0xC0: "ℵ", 0xC1: "ℑ", 0xC2: "ℜ", 0xC3: "℘", 0xC4: "⊗", 0xC5: "⊕", 0xC6: "∅",
    0xC7: "∩", 0xC8: "∪", 0xC9: "⊃", 0xCA: "⊇", 0xCB: "⊄", 0xCC: "⊂", 0xCD: "⊆",
    0xCE: "∈", 0xCF: "∉", 0xD0: "∠", 0xD1: "∇", 0xD5: "∏", 0xD6: "√", 0xD7: "⋅",
    0xD8: "¬", 0xD9: "∧", 0xDA: "∨", 0xDB: "⇔", 0xDC: "⇐", 0xDD: "⇑", 0xDE: "⇒",
    0xDF: "⇓", 0xE0: "◊", 0xE1: "⟨", 0xE5: "∑", 0xF1: "⟩", 0xF2: "∫",
}
_SYMBOL_PUA = str.maketrans({0xF000 + code: ch for code, ch in _SYMBOL_ENCODING.items()})
_PUA_ANY = re.compile("[-]")
# Wingdings/Symbol glyphs used as list bullets: only at the start of a line or
# item are they bullets (mid-text they are Symbol math, e.g. F0D8 = ¬). Greek
# letters that double as Wingdings bullets (F06C l/λ, F06E n/ν) are NOT treated
# as bullets: a line-leading λ is real notation in a PL course.
_PUA_BULLET_LEAD = re.compile("(^|\n)([ \t]*)[]")


def fold_symbol_pua(text: str) -> str:
    """Map Symbol-font private-use code points to Unicode (see table above)."""
    text = _PUA_BULLET_LEAD.sub(r"\1\2•", text)
    return text.translate(_SYMBOL_PUA)


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


def heal_elements(
    elements: list[dict],
    clip_text: ClipText | None,
    clip_code: ClipText | None = None,
) -> list[dict]:
    """Return elements with ligatures folded everywhere and, on pages whose
    Docling text is glued, each boxed text element re-read through
    `clip_text(page_no, bbox)`. Tables and figures are left alone.

    Code (a Docling ``code`` label or text that looks like source) is retyped
    ``code``; with `clip_code` (native PDFs) consecutive code elements on a
    page are merged and re-read from the PDF's own text layer with line
    breaks, indentation and quotes intact. Returns the list (possibly a new
    one when code elements were merged)."""
    for el in elements:
        if el.get("text"):
            el["text"] = normalize_ligatures(el["text"])
    if clip_text is not None:
        _heal_glued_pages(elements, clip_text)
    return heal_code(elements, clip_code, clip_text)


def _heal_glued_pages(elements: list[dict], clip_text: ClipText) -> None:
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


# ── Code fidelity ───────────────────────────────────────────────────────────
# Docling assembles every text cluster by joining its lines with spaces and
# normalizing quotes, and docling-parse splits escapes into separate cells, so
# `printf( “%d\n”, x );` comes out as `printf ( '%d \ n', x );` on one line and
# an indented line can land in its own cluster (moving it out of its `if`).
# The PDF's own text layer has the exact characters; re-read code from it.

# Unambiguous source-code markers (C/C++ teaching material dominates).
_CODE_STRONG = re.compile(
    r"#\s?include\b|#\s?define\b|\b(?:printf|scanf|malloc|strcpy|strlen|fprintf|sizeof)\s*\("
    r"|\bcout\s*<<|\bcin\s*>>|\bint\s+main\s*\(|\b(?:public|private|protected)\s*:"
)
_CODE_DECL = re.compile(
    r"\b(?:int|char|float|double|void|long|short|struct|bool|const|static|unsigned)"
    r"\s+\**\s*[A-Za-z_]\w*\s*(?:[=;,\[(])"
)
_CODE_OPS = re.compile(r"->|==|!=|\+\+|--(?=[A-Za-z_\[(])|&&|\|\||<<|>>")
_CODE_CALL_STMT = re.compile(r"[A-Za-z_]\w*\s*\([^()]*\)\s*;")
# A statement-ending ';' — at a line end, before '}', or before another
# statement-looking token. A mid-sentence ';' ("is finite; it has") is prose.
_CODE_SEMI = re.compile(
    r"[\w)\]'\"]\s*;[ \t]*(?:$|\n|\}|(?=[A-Za-z_]\w*\s*(?:[=(\[]|\+\+|--)))", re.M
)
_CODE_SYMBOLS = set(";{}()=<>*&[]#")
CODE_MIN_SYMBOL_DENSITY = 0.04  # prose with a stray ';' sits far below this


def looks_like_code(text: str) -> bool:
    """Heuristic: does this (possibly line-joined) element text read as source
    code? Needs two independent signals plus a code-like symbol density, so
    prose with semicolons and set notation ('{ a, b }') stay prose."""
    t = (text or "").strip()
    if len(t) < 6:
        return False
    strong = bool(_CODE_STRONG.search(t))
    score = 2 if strong else 0
    if "{" in t and "}" in t:
        score += 1
    if _CODE_SEMI.search(t):
        score += 1
    if _CODE_DECL.search(t):
        score += 1
    if _CODE_CALL_STMT.search(t):
        score += 1
    if _CODE_OPS.search(t):
        score += 1
    if score < 2:
        return False
    density = sum(1 for ch in t if ch in _CODE_SYMBOLS) / len(t)
    return strong or density >= CODE_MIN_SYMBOL_DENSITY


# `\ n` / `' \ 0'`: docling-parse emits the backslash and the escape letter as
# separate cells, which assembly re-joins with a space.
_SPLIT_ESCAPE = re.compile(r"\\ (?=[ntr0abfv\\'\"](?:\b|\W|$))")
_CODE_QUOTES = str.maketrans({"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "′": "'"})
_LEAD_BULLET = re.compile(r"^[ \t]*[•·▪◦‣∙]\s*")


def fix_split_escapes(text: str) -> str:
    """Re-attach a backslash to its escape letter ('\\ n' → '\\n')."""
    return _SPLIT_ESCAPE.sub(r"\\", text)


def normalize_code(text: str) -> str:
    """Final form of a code block: straight quotes (curly quotes in a PDF code
    sample are typography, not syntax), escapes re-joined, list bullets the
    slide put in front of a code line dropped, trailing blanks trimmed."""
    lines = []
    for line in normalize_ligatures(text).replace("\r", "").split("\n"):
        line = _LEAD_BULLET.sub("", line.translate(_CODE_QUOTES)).rstrip()
        lines.append(fix_split_escapes(line))
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _union_bbox(a: dict, b: dict) -> dict:
    # Docling bottom-left origin: t is the larger y.
    return {
        "l": min(a["l"], b["l"]),
        "r": max(a["r"], b["r"]),
        "t": max(a["t"], b["t"]),
        "b": min(a["b"], b["b"]),
    }


def heal_code(
    elements: list[dict],
    clip_code: ClipText | None,
    clip_text: ClipText | None = None,
) -> list[dict]:
    """Retype code elements as ``code`` and, when the PDF text layer is
    available (`clip_code`), merge runs of consecutive code elements on the
    same page and re-read them from it, keeping newlines and indentation.
    Non-code elements carrying a split escape ('\\ n') are re-read as prose
    through `clip_text`, or repaired textually when there is no text layer."""
    out: list[dict] = []
    for el in elements:
        etype = el.get("type")
        text = el.get("text") or ""
        if etype in ("table", "figure", "heading", "caption") or not text:
            out.append(el)
            continue
        if etype == "code" or looks_like_code(text):
            el["type"] = "code"
            prev = out[-1] if out else None
            if (
                clip_code is not None
                and prev is not None
                and prev.get("type") == "code"
                and prev.get("page_no") == el.get("page_no")
                and prev.get("bbox")
                and el.get("bbox")
            ):
                # Docling often splits one code listing into several clusters
                # (an indented line becomes its own); re-read them as one.
                prev["bbox"] = _union_bbox(prev["bbox"], el["bbox"])
                prev["text"] = (prev.get("text") or "") + "\n" + text
                continue
            out.append(el)
            continue
        if _SPLIT_ESCAPE.search(text):
            healed = None
            if clip_text is not None and el.get("bbox"):
                try:
                    raw = clip_text(int(el["page_no"]), el["bbox"]) or ""
                    healed = normalize_ligatures(join_lines(raw))
                except Exception:  # noqa: BLE001 — best-effort
                    healed = None
                if healed and not _ratio_ok(text, healed):
                    healed = None
            el["text"] = healed or fix_split_escapes(text)
        out.append(el)

    for el in out:
        if el.get("type") != "code":
            continue
        reread = None
        if clip_code is not None and el.get("bbox"):
            try:
                reread = clip_code(int(el["page_no"]), el["bbox"])
            except Exception:  # noqa: BLE001 — best-effort
                reread = None
        if reread and _ratio_ok(el["text"], reread):
            el["text"] = normalize_code(reread)
            el["healed"] = True
        else:
            el["text"] = normalize_code(el["text"])
    return out


def _ratio_ok(before_text: str, after_text: str) -> bool:
    before, after = _letters(before_text), _letters(after_text)
    if before == 0:
        return False
    return HEAL_MIN_LETTER_RATIO <= after / before <= HEAL_MAX_LETTER_RATIO


# PyMuPDF span → code line reconstruction. Bullets drawn by the slide are not
# part of the listing.
_BULLET_ONLY = re.compile(r"^[\s•·▪◦‣∙]*$")


def code_lines_from_dict(data: dict) -> str:
    """Rebuild a code listing from a PyMuPDF ``get_text('dict')`` result:
    spans are grouped into visual lines by their vertical centre (PyMuPDF often
    splits `printf` and `( “x” );` into separate lines), joined left→right,
    and indented by their x offset in average character widths."""
    spans: list[tuple[float, float, float, float, str]] = []  # x0, x1, yc, h, text
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text or _BULLET_ONLY.match(text):
                    continue
                x0, y0, x1, y1 = (float(v) for v in span["bbox"])
                spans.append((x0, x1, (y0 + y1) / 2, max(1.0, y1 - y0), text))
    if not spans:
        return ""
    chars = sum(len(s[4]) for s in spans)
    width = sum(s[1] - s[0] for s in spans)
    cw = max(1.0, width / max(1, chars))  # average character width

    spans.sort(key=lambda s: (s[2], s[0]))
    rows: list[list[tuple[float, float, float, float, str]]] = []
    for s in spans:
        if rows:
            row = rows[-1]
            yc = sum(r[2] for r in row) / len(row)
            if abs(s[2] - yc) < 0.5 * min(s[3], row[0][3]):
                row.append(s)
                continue
        rows.append([s])

    built: list[tuple[float, str]] = []
    for row in rows:
        row.sort(key=lambda s: s[0])
        text = ""
        prev_x1 = None
        for x0, x1, _yc, _h, t in row:
            gap = x0 - prev_x1 if prev_x1 is not None else 0.0
            if gap > 0.3 * cw and not text.endswith(" ") and not t.startswith(" "):
                text += " "
            text += t
            prev_x1 = x1
        first_x0, first_x1, _yc, _h, first_t = row[0]
        lead = len(first_t) - len(first_t.lstrip(" "))
        span_cw = (first_x1 - first_x0) / max(1, len(first_t))
        start_x = first_x0 + lead * span_cw
        built.append((start_x, text.strip()))
    base = min(x for x, _ in built)
    lines = [" " * min(32, int(round((x - base) / cw))) + t for x, t in built]
    return "\n".join(lines)


def _docling_rect(page, bbox: dict):
    import pymupdf

    height = page.rect.height
    top = height - float(bbox["t"])
    bottom = height - float(bbox["b"])
    rect = pymupdf.Rect(float(bbox["l"]), min(top, bottom), float(bbox["r"]), max(top, bottom))
    # a hair of tolerance so glyphs on the box edge are not cut
    return pymupdf.Rect(rect.x0 - 1, rect.y0 - 1, rect.x1 + 1, rect.y1 + 1)


# Same rule as text_html.sanitize (kept local: text_html imports this module).
# Some decks' embedded fonts leak NUL/control characters into the text layer,
# and Postgres text columns reject NUL — a re-read must be cleaned like every
# other extraction path or the whole document fails to save.
_LAYER_CONTROL = re.compile(r"[\x00-\x08\x0c\x0e-\x1f]")


def _clean_layer_text(text: str) -> str:
    return _LAYER_CONTROL.sub("", (text or "").replace("\x0b", "\n"))


def pymupdf_clip_text(pdf_doc) -> ClipText:
    """ClipText backed by an open PyMuPDF document. Docling bboxes are in PDF
    points with a bottom-left origin (t > b); PyMuPDF wants top-left."""

    def clip(page_no: int, bbox: dict) -> str:
        page = pdf_doc[page_no - 1]
        return _clean_layer_text(page.get_text("text", clip=_docling_rect(page, bbox), sort=True))

    return clip


def pymupdf_clip_code(pdf_doc) -> ClipText:
    """Like `pymupdf_clip_text`, but rebuilds the clipped region as a code
    listing (line breaks + indentation kept) via `code_lines_from_dict`."""

    def clip(page_no: int, bbox: dict) -> str:
        page = pdf_doc[page_no - 1]
        return _clean_layer_text(
            code_lines_from_dict(page.get_text("dict", clip=_docling_rect(page, bbox)))
        )

    return clip
