"""When each displayed word is spoken, for highlighting along with Steven.

The audio says the *spoken* form (citations dropped, abbreviations expanded,
respellings), while the reader shows the extracted `text`. Recognition's word
timestamps are matched to the displayed words in order; a word that was not
said (a citation) or not recognised (a Tagalog name) gets a time interpolated
between its neighbours by length, so the highlight passes over it smoothly.
"""

import io
import re
from difflib import SequenceMatcher

from manabi_ai import tts_verification


def _norm(token: str) -> str:
    return re.sub(r"[^a-z0-9]", "", token.lower())


def align_starts(tokens: list[str], heard: list[tuple[str, int]], duration_ms: int) -> list[int]:
    """Start time (ms) for each of `tokens`, given recognised (word, start_ms)."""
    n = len(tokens)
    if n == 0:
        return []
    starts: list[int | None] = [None] * n
    a = [_norm(t) for t in tokens]
    b = [_norm(w) for w, _ in heard]
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                starts[i1 + k] = heard[j1 + k][1]
        elif tag == "replace" and i2 - i1 <= 2 * (j2 - j1) and j2 - j1 <= 2 * (i2 - i1):
            # roughly the same words heard differently ("Keem Poe" for Quimpo)
            for k in range(i1, i2):
                starts[k] = heard[j1 + (k - i1) * (j2 - j1) // (i2 - i1)][1]

    # Interpolate the rest by character length between the known neighbours.
    weight = [max(1, len(t)) for t in tokens]
    i = 0
    while i < n:
        if starts[i] is not None:
            i += 1
            continue
        j = i
        while j < n and starts[j] is None:
            j += 1
        lo = starts[i - 1] if i > 0 else 0
        hi = starts[j] if j < n else duration_ms
        span_w = sum(weight[i - 1 : j]) if i > 0 else sum(weight[i:j]) or 1
        acc = weight[i - 1] if i > 0 else 0
        for k in range(i, j):
            starts[k] = int(lo + (hi - lo) * acc / max(1, span_w))
            acc += weight[k]
        i = j
    out: list[int] = []
    for s in starts:
        out.append(max(int(s or 0), out[-1] if out else 0))  # never backwards
    return out


def word_starts(audio: bytes, text: str, duration_ms: int) -> list[int] | None:
    """Recognise the segment's audio with word timestamps and align it to the
    whitespace tokens of `text`. None when recognition is unavailable."""
    tokens = text.split()
    if not tokens:
        return []
    try:
        with tts_verification._lock:
            segments, _ = tts_verification._model().transcribe(
                io.BytesIO(audio),
                language="en",
                beam_size=1,
                word_timestamps=True,
                condition_on_previous_text=False,
                vad_filter=False,
            )
            heard = [
                (w.word.strip(), int(w.start * 1000))
                for seg in segments
                for w in (seg.words or [])
                if w.word.strip()
            ]
    except Exception:  # noqa: BLE001 — highlighting is a nicety, never fatal
        return None
    return align_starts(tokens, heard, duration_ms)
