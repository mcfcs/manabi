"""Increment 10: SM-2-lite scheduling + lecture spoken-text sanitizer."""

import sys
from datetime import date
from pathlib import Path

from manabi_server.srs import EASE_MAX, EASE_MIN, ReviewState, apply_rating

sys.path.insert(
    0, str(Path(__file__).resolve().parents[3] / "apps" / "ai-worker" / "src")
)
from manabi_ai.tasks_gen import sanitize_spoken  # noqa: E402

TODAY = date(2026, 8, 10)


class TestSm2Lite:
    def test_first_good_is_one_day(self):
        state, due = apply_rating(ReviewState(), "good", TODAY)
        assert state.interval_days == 1.0
        assert due == date(2026, 8, 11)
        assert state.reps == 1

    def test_good_growth_uses_ease(self):
        s = ReviewState(interval_days=1.0, ease=2.5, reps=1)
        s, due = apply_rating(s, "good", TODAY)
        assert s.interval_days == 2.5
        s, due = apply_rating(s, "good", TODAY)
        assert s.interval_days == 6.25
        assert due == date(2026, 8, 16)

    def test_again_resets_and_penalizes(self):
        s = ReviewState(interval_days=10, ease=2.5, reps=4)
        s, due = apply_rating(s, "again", TODAY)
        assert s.interval_days == 0
        assert s.reps == 0
        assert s.lapses == 1
        assert s.ease == 2.3
        assert due == TODAY  # back into today's queue

    def test_hard_slows_growth(self):
        s = ReviewState(interval_days=10, ease=2.5)
        s, _ = apply_rating(s, "hard", TODAY)
        assert s.interval_days == 12.0  # ×1.2
        assert s.ease == 2.35

    def test_easy_boosts(self):
        s = ReviewState(interval_days=2, ease=2.5)
        s, _ = apply_rating(s, "easy", TODAY)
        assert s.interval_days == 2 * 2.5 * 1.3
        assert s.ease == 2.65

    def test_ease_clamped(self):
        s = ReviewState(ease=EASE_MIN)
        s, _ = apply_rating(s, "again", TODAY)
        assert s.ease == EASE_MIN
        s = ReviewState(ease=EASE_MAX)
        s, _ = apply_rating(s, "easy", TODAY)
        assert s.ease == EASE_MAX

    def test_interval_capped(self):
        s = ReviewState(interval_days=300, ease=2.8)
        s, _ = apply_rating(s, "good", TODAY)
        assert s.interval_days == 365


class TestSpokenSanitizer:
    def test_strips_markdown(self):
        out = sanitize_spoken("This is **bold** and `code` and [a link](x).")
        assert "*" not in out and "`" not in out and "[" not in out
        assert "bold" in out

    def test_drops_code_lines(self):
        text = "The function works like this.\n    def f(x): return {x: 1};\nSimple."
        out = sanitize_spoken(text)
        assert "def f" not in out
        assert "Simple." in out

    def test_plain_prose_untouched(self):
        prose = "Attenuation means the signal weakens with distance."
        assert sanitize_spoken(prose) == prose
