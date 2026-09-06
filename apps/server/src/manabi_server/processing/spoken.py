"""Turn written academic prose into text that reads well aloud (pure).

Deterministic, no model: drop what a human reader skips (in-text citations,
URLs, footnote markers), expand abbreviations the way a lecturer would say
them, speak number ranges, un-shout ALL-CAPS headings, and make sure every
segment ends with a stop so the synthesizer pauses.
"""

from __future__ import annotations

import re

from manabi_server.processing.text_health import normalize_ligatures

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "„": '"', "«": '"', "»": '"'})

# (Author, 1990) · (Author and Other, 2004: 12–13) · (Author et al., 2009; Other, 2010)
# · (IMF, 2005: 126–127) · (see North, 1990) · (e.g. Knight, 1992)
_AUTHOR = (
    r"(?:see\s+|e\.g\.\s+|cf\.\s+)?[A-Z][\w'’.-]*"
    r"(?:\s(?:and|&)\s[A-Z][\w'’.-]*|,\s[A-Z][\w'’.-]*)*(?:\set\sal\.?)?"
)
_YEAR = r"(?:\d{4}[a-z]?|forthcoming|n\.d\.)"
_ONE_CITE = _AUTHOR + r",?\s" + _YEAR + r"(?:\s?[:,]\s?[\d–\-, ]+|,\s?p{1,2}\.\s?[\d–\-]+)?"
_PAREN_CITATION = re.compile(r"\((?:" + _ONE_CITE + r")(?:;\s*(?:" + _ONE_CITE + r"))*\)")
# a bare year citation after a name in running text: "North (1990) argues"
_INLINE_YEAR = re.compile(r"\s\((?:" + _YEAR + r")(?:\s?[:,]\s?[\d–\-, ]+)?\)")
_BRACKET_CITATION = re.compile(r"\s?\[\d{1,3}(?:\s?[,–-]\s?\d{1,3})*\]")
_URL = re.compile(r"(?:https?://|www\.)\S+|\b\S+@\S+\.\w+\b|\bdoi:\s*\S+", re.IGNORECASE)
_EMPTY_PARENS = re.compile(r"\(\s*\)")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?])")
_MULTI_PUNCT = re.compile(r"([,.;:])\1+")

_ABBREVIATIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\be\.g\.,?\s*", re.IGNORECASE), "for example, "),
    (re.compile(r"\bi\.e\.,?\s*", re.IGNORECASE), "that is, "),
    (re.compile(r"\bet\s+al\.?"), "and colleagues"),
    (re.compile(r"\bcf\.\s*"), "compare "),
    (re.compile(r"\bvs\.?\s"), "versus "),
    (re.compile(r"\bviz\.\s*"), "namely, "),
    (re.compile(r"\bFigs?\.\s*(?=\d)"), "Figure "),
    (re.compile(r"\bNo\.\s*(?=\d)"), "number "),
    (re.compile(r"\bpp\.\s*(?=\d)"), "pages "),
    (re.compile(r"\bp\.\s*(?=\d)"), "page "),
    (re.compile(r"\bibid\.?", re.IGNORECASE), "the same source"),
    (re.compile(r"\band/or\b"), "and or"),
    (re.compile(r"\s*&\s*"), " and "),
    (re.compile(r"(\d)\s*%"), r"\1 percent"),
    (re.compile(r"\bUS\$\s?(?=\d)"), "US dollars "),
]

_NUM_RANGE = re.compile(r"(?<!\w)(\d+(?:\.\d+)?)\s*[–—-]\s*(\d+(?:\.\d+)?)(?!\w)")
_HEADING_NUMBER = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?|[IVXLC]+\.|[A-Z]\.)\s+(?=\S)")
_CAPS_RUN = re.compile(r"\b(?:[A-Z][A-Z'’-]{1,}\s+){2,}[A-Z][A-Z'’-]{1,}\b")
_SMALL_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "but",
    "by",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "vs",
}
_ACRONYM = re.compile(r"^[A-Z]{2,5}$")


def _title_case(phrase: str) -> str:
    words = phrase.split()
    out = []
    for i, w in enumerate(words):
        core = w.strip("'’-")
        if (
            _ACRONYM.match(core)
            and len(core) <= 4
            and core in ("UK", "US", "USA", "EU", "UN", "IMF", "GDP")
        ):
            out.append(w)  # real acronyms stay
        elif i > 0 and w.lower() in _SMALL_WORDS:
            out.append(w.lower())
        else:
            # capitalise the first LETTER, so '"DON'T' → '"Don't'
            out.append(re.sub(r"[A-Za-z]", lambda m: m.group(0).upper(), w.lower(), count=1))
    return " ".join(out)


def unshout(text: str) -> str:
    """ALL-CAPS runs of three or more words read as spelled-out letters in TTS;
    give them normal casing. Short acronyms elsewhere are left alone."""
    return _CAPS_RUN.sub(lambda m: _title_case(m.group(0)), text)


def strip_citations(text: str) -> str:
    text = _PAREN_CITATION.sub("", text)
    text = _INLINE_YEAR.sub("", text)
    text = _BRACKET_CITATION.sub("", text)
    return _EMPTY_PARENS.sub("", text)


def speak_numbers(text: str) -> str:
    return _NUM_RANGE.sub(r"\1 to \2", text)


def expand_abbreviations(text: str) -> str:
    for pattern, repl in _ABBREVIATIONS:
        text = pattern.sub(repl, text)
    return text


def tidy(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    text = _MULTI_PUNCT.sub(r"\1", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    return text.strip()


def ensure_stop(text: str) -> str:
    if not text:
        return text
    return text if text[-1] in ".!?:;" else text + "."


_LEADING_BULLET = re.compile(r"^[!•·▪◦●■□◆»>*\-–]\s*(?=[A-Z\"'(])")
_DOUBLED_QUOTE = re.compile(r"''|``")
# a dagger/asterisk footnote mark rendered as a stray letter after a closing
# double quote or punctuation ("ORGANIZE''y"). Not after a single quote (DON'T)
# and never 'a'/'I', which are words.
_STRAY_MARK = re.compile(r"(?<=[\"?!.;:)])\s?[b-hj-zB-HJ-Z](?=\s|$)")


def clean_display_title(text: str) -> str:
    """Display form of a title: fold ligatures, straighten doubled quotes and
    drop stray footnote-mark letters, but keep the original casing."""
    s = normalize_ligatures(text).translate(_QUOTES)
    s = _DOUBLED_QUOTE.sub('"', s)
    s = _STRAY_MARK.sub("", s.strip())
    return tidy(s)


def to_spoken(text: str, kind: str = "paragraph") -> str:
    """The text a narrator would actually say for one segment."""
    s = normalize_ligatures(text).translate(_QUOTES)
    s = _DOUBLED_QUOTE.sub('"', s)
    s = _URL.sub("", s)
    s = strip_citations(s)
    s = _LEADING_BULLET.sub("", s.strip())
    if kind in ("heading", "title"):
        s = _HEADING_NUMBER.sub("", s)
        s = _STRAY_MARK.sub("", s.strip())
        s = s.rstrip(" .:")
        # "INTRODUCTION" → "Introduction" (acronym headings are shorter than 6)
        s = _title_case(s) if s.isupper() and len(s) > 5 else unshout(s)
    else:
        s = unshout(s)
    s = expand_abbreviations(s)
    s = speak_numbers(s)
    s = tidy(s)
    return ensure_stop(s)


def humanize_names(text: str) -> str:
    """Author lines are often typeset in caps ("ADRIAN LEFTWICH and KUNAL SEN");
    give each all-caps word normal casing, leaving initials alone."""
    return " ".join(
        w.capitalize() if w.isupper() and len(w.strip(".,")) >= 2 else w for w in text.split()
    )


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text))
