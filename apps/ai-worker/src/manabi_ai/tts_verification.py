"""Conservative, local completeness checks for verbatim document readings.

Recognition is not an exact transcript oracle. Flag substantial omissions,
not isolated pronunciation differences, punctuation, or number formatting.
"""

import io
import re
from difflib import SequenceMatcher
from functools import lru_cache
from threading import Lock

from manabi_ai.config import get_settings

_lock = Lock()
_NUMBER_WORDS = set(
    [
        "zero",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
        "twenty",
        "thirty",
        "forty",
        "fifty",
        "sixty",
        "seventy",
        "eighty",
        "ninety",
        "hundred",
        "thousand",
        "million",
        "billion",
        "trillion",
        "first",
        "second",
        "third",
        "fourth",
        "fifth",
        "sixth",
        "seventh",
        "eighth",
        "ninth",
        "tenth",
        "eleventh",
        "twelfth",
        "thirteenth",
        "fourteenth",
        "fifteenth",
        "sixteenth",
        "seventeenth",
        "eighteenth",
        "nineteenth",
        "twentieth",
        "thirtieth",
        "fortieth",
        "fiftieth",
        "sixtieth",
        "seventieth",
        "eightieth",
        "ninetieth",
        "hundredth",
        "thousandth",
        "millionth",
        "billionth",
    ]
)


def _words(text: str) -> list[str]:
    # ASR freely converts "thirty-five" to "35" and vice versa. Numeric
    # fidelity needs a different check; don't reject otherwise complete prose.
    words = re.findall(r"[a-z]+(?:'[a-z]+)?", text.lower().replace("’", "'"))
    return [w for w in words if w not in _NUMBER_WORDS]


def transcript_problem(expected: str, heard: str) -> str | None:
    source, spoken = _words(expected), _words(heard)
    if len(source) < 5:
        return None  # recognition of tiny headings is too noisy
    matcher = SequenceMatcher(None, source, spoken, autojunk=False)
    coverage = sum(m.size for m in matcher.get_matching_blocks()) / len(source)
    if coverage < 0.6:
        return "Voice transcript contains too little of the requested sentence"
    for tag, a, b, c, d in matcher.get_opcodes():
        if tag == "delete" and b - a >= 4:
            return "Voice transcript omits a phrase from the requested sentence"
        if tag == "replace" and b - a >= 6 and d - c <= (b - a) // 3:
            return "Voice transcript loses a substantial part of the requested sentence"
    return None


@lru_cache(maxsize=1)
def _model():
    from faster_whisper import WhisperModel

    return WhisperModel(
        get_settings().tts_verification_model,
        device="cpu",
        compute_type="int8",
        cpu_threads=4,
    )


def verify_wav(audio: bytes, expected: str) -> str | None:
    if len(_words(expected)) < 5:
        return None
    with _lock:
        segments, _ = _model().transcribe(
            io.BytesIO(audio),
            language="en",
            beam_size=5,
            condition_on_previous_text=False,
            vad_filter=False,
        )
        # Do not prime ASR with the requested text: it can hallucinate missing
        # words from that prompt and defeat the completeness check.
        heard = " ".join(segment.text for segment in segments)
    return transcript_problem(expected, heard)
