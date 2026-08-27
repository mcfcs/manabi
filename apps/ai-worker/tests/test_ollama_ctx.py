"""num_ctx sizing — grows with the prompt (conservative 3.5 chars/token so big
page-range / whole-doc asks aren't silently truncated) and respects the cap."""

from manabi_ai.ollama_client import _num_ctx


def test_num_ctx_grows_with_prompt_and_respects_cap():
    assert _num_ctx("hi", "there", 24576) == 4096  # tiny → smallest tier
    # ~40k chars ≈ 11.4k tokens + headroom → 16384 tier
    assert _num_ctx("", "x" * 40000, 24576) == 16384
    # ~70k chars ≈ 20k tokens → the new 24576 tier
    assert _num_ctx("", "x" * 70000, 24576) == 24576
    # cap clamps below the needed tier
    assert _num_ctx("", "x" * 70000, 8192) == 8192


def test_num_ctx_conservative_estimate():
    # A prompt that /4 would call 8192-worthy but /3.5 pushes into 16384 —
    # the whole point: never undersize and drop the tail of the material.
    p = "x" * 32000  # /4 = 8000 (+1024=9024 → 16384 anyway); /3.5 = 9142 (+1024)
    assert _num_ctx("", p, 24576) == 16384


def test_num_ctx_headroom_reserves_answer_space():
    # ~4k-token prompt with the chat-sized default fits 8192…
    assert _num_ctx("s", "u" * 14_000, 24_576) == 8192
    # …but a quiz's worth of step-by-step output needs a bigger reservation,
    # or the window fills mid-answer and the JSON is cut off mid-string.
    assert _num_ctx("s", "u" * 14_000, 24_576, headroom=6144) == 16_384
    # Even a tiny prompt escapes the 4096 tier once real output space is asked.
    assert _num_ctx("s", "u", 24_576, headroom=6144) == 8192
