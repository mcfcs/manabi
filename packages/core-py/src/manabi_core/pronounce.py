"""How Steven says terms: per-course respellings plus fixed rules, applied to
the text right before it is synthesized (the transcript keeps the real word).

The voice's English front end (GPT-SoVITS, g2p_en + CMUdict) decides a word's
sounds like this, which is what the rules below work around:
- a word in its dictionary is read from it;
- an unknown word of three letters or fewer is SPELLED OUT ("Huk" → H-U-K);
- a longer unknown word is guessed by a small model ("Quimpo" →
  kee-eh-m-pee-oh, "Akbayan" → ay-kay-bay-an);
- a hyphenated respelling is split and its short pieces spelled out, so a
  respelling must be space-separated syllables ("Keem Poe", not "keem-poh").
"""

import re
from dataclasses import dataclass

# A word as the voice tokenizes it: letters with inner apostrophes.
_WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")
# "NGOs", "POs", "CDs": the lowercase plural makes the voice read a word.
_PLURAL_ACRONYM = re.compile(r"\b([A-Z]{2,5})s\b")

# Symbols the voice drops or misreads (it says "C++" as just "C").
_SYMBOLS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?<![\w+])C\+\+(?![\w+])"), "C plus plus"),
    (re.compile(r"(?<![\w#])C#(?![\w#])"), "C sharp"),
    (re.compile(r"(?<![\w#])F#(?![\w#])"), "F sharp"),
    (re.compile(r"\s*->\s*"), " arrow "),
    (re.compile(r"\s*==\s*"), " equals equals "),
    (re.compile(r"\s*!=\s*"), " not equal to "),
    (re.compile(r"\s*<=\s*"), " less than or equal to "),
    (re.compile(r"\s*>=\s*"), " greater than or equal to "),
]


@dataclass(frozen=True)
class Entry:
    term: str
    say: str


def words(text: str) -> list[str]:
    """Distinct words in reading order, possessives stripped ("Marcos's" →
    "Marcos")."""
    seen: dict[str, None] = {}
    for m in _WORD.finditer(text or ""):
        w = re.sub(r"['’]s$", "", m.group(0))
        if len(w) >= 2:
            seen.setdefault(w, None)
    return list(seen)


def letters(term: str) -> str:
    """An acronym read letter by letter: "PDSP" → "P D S P"; a lowercase
    plural keeps its s as a possessive, which the voice says as a plain
    "z" sound ("NGOs" → "N G O's")."""
    m = re.fullmatch(r"([A-Z]+)s", term)  # "Gs" too: "the three Gs"
    if m:
        *head, last = m.group(1)
        return " ".join([*head, f"{last}'s"])
    return " ".join(term.replace(".", "").upper())


def _pattern(term: str) -> re.Pattern:
    # A lowercase-containing term matches any case ("Trapo", "trapo"); an
    # all-caps acronym only itself, so "Hook" never rewrites "HOOK" headings.
    flags = 0 if term.isupper() else re.IGNORECASE
    return re.compile(rf"(?<![A-Za-z]){re.escape(term)}(?:(['’]s))?(?![A-Za-z])", flags)


def apply(text: str, entries: list[Entry]) -> str:
    """The text Steven should be given: fixed symbol rules, the course's
    respellings (longest term first, so "utang na loob" beats "utang"), then
    plural acronyms."""
    out = text or ""
    for pattern, repl in _SYMBOLS:
        out = pattern.sub(repl, out)
    for e in sorted(entries, key=lambda e: -len(e.term)):
        if not e.term or not e.say or e.say == e.term:
            continue
        out = _pattern(e.term).sub(lambda m, say=e.say: say + (m.group(1) or ""), out)
    out = _PLURAL_ACRONYM.sub(lambda m: letters(m.group(0)), out)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def needs_respelling(word: str, known: bool) -> bool:
    """Should this word be looked at? Unknown to the voice's dictionary, or a
    plural acronym. Short all-caps acronyms are already spelled out right."""
    if _PLURAL_ACRONYM.fullmatch(word):
        return False  # handled by the fixed rule
    if known:
        return False
    return not (word.isupper() and len(word) <= 3)


def phone_distance(a: list[str], b: list[str]) -> float:
    """Edit distance between two phoneme strings, stress marks ignored, as a
    share of the longer one (0 = identical)."""
    x = [re.sub(r"\d", "", p) for p in a]
    y = [re.sub(r"\d", "", p) for p in b]
    if not x and not y:
        return 0.0
    prev = list(range(len(y) + 1))
    for i, pa in enumerate(x, 1):
        cur = [i]
        for j, pb in enumerate(y, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (pa != pb)))
        prev = cur
    return prev[-1] / max(len(x), len(y))
