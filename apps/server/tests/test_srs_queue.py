"""SRS review-queue behaviour: interval previews (and later: ordering, undo,
leeches) — pure functions, no DB."""

from datetime import date

from manabi_server.srs import RATINGS, ReviewState, apply_rating, preview_intervals

TODAY = date(2026, 9, 6)


def test_preview_intervals_for_a_new_card():
    previews = preview_intervals(ReviewState(), TODAY)
    assert set(previews) == set(RATINGS)
    assert previews == {"again": 0, "hard": 1, "good": 1, "easy": 2}


def test_preview_intervals_match_apply_rating_and_grow_with_rating():
    state = ReviewState(interval_days=10, ease=2.5, reps=3)
    previews = preview_intervals(state, TODAY)
    for rating in RATINGS:
        _, due = apply_rating(state, rating, TODAY)
        assert previews[rating] == (due - TODAY).days
    assert previews["again"] == 0
    assert previews["again"] < previews["hard"] < previews["good"] < previews["easy"]
