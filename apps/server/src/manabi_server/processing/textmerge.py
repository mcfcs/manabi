"""OCR fragment reconstruction — pure functions, shared by the text view
builder and chunk assembly.

OCR splits sentences at line breaks and hyphenation points; these helpers
join fragments back into paragraphs ("pro-" + "vided" → "provided")."""

TERMINAL = (".", "?", "!", ":", ";", '"', "'", ")")


def should_join(prev: str, nxt: str) -> bool:
    prev = prev.rstrip()
    nxt = nxt.lstrip()
    if not prev or not nxt:
        return False
    if prev.endswith("-"):
        return True
    if prev.endswith(TERMINAL):
        return False
    first = nxt[0]
    return first.islower() or first.isdigit() or first in "(\"'"


def join_pair(prev: str, nxt: str) -> str:
    prev = prev.rstrip()
    nxt = nxt.lstrip()
    if prev.endswith("-"):
        return prev[:-1] + nxt  # dehyphenate
    return prev + " " + nxt


def merge_fragments(texts: list[str]) -> list[str]:
    """Collapse a sequence of line/paragraph fragments into full paragraphs."""
    merged: list[str] = []
    for text in texts:
        t = text.strip()
        if not t:
            continue
        if merged and should_join(merged[-1], t):
            merged[-1] = join_pair(merged[-1], t)
        else:
            merged.append(t)
    return merged
