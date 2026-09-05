"""SRS review-queue behaviour: interval previews (and later: ordering, undo,
leeches) — pure functions, no DB."""

import types
from datetime import UTC, date, datetime

from manabi_server.srs import (
    RATINGS,
    ReviewState,
    apply_rating,
    preview_intervals,
    restore_review,
    snapshot_review,
)

TODAY = date(2026, 9, 6)


def test_snapshot_restore_roundtrip_is_json_safe():
    review = types.SimpleNamespace(
        due_date=date(2026, 9, 10),
        interval_days=6.25,
        ease=2.65,
        reps=4,
        lapses=1,
        last_rating="good",
        reviewed_at=datetime(2026, 9, 4, 8, 30, tzinfo=UTC),
    )
    snap = snapshot_review(review)
    assert all(isinstance(v, (str, int, float, type(None))) for v in snap.values())

    # overwrite as a rating would, then restore
    review.due_date, review.interval_days, review.ease = date(2026, 9, 20), 15.6, 2.8
    review.reps, review.lapses, review.last_rating = 5, 1, "easy"
    review.reviewed_at = datetime(2026, 9, 6, 9, 0, tzinfo=UTC)
    restore_review(review, snap)
    assert (review.due_date, review.interval_days, review.ease) == (date(2026, 9, 10), 6.25, 2.65)
    assert (review.reps, review.lapses, review.last_rating) == (4, 1, "good")
    assert review.reviewed_at == datetime(2026, 9, 4, 8, 30, tzinfo=UTC)


def test_snapshot_handles_never_reviewed_timestamp():
    review = types.SimpleNamespace(
        due_date=TODAY,
        interval_days=0.0,
        ease=2.5,
        reps=0,
        lapses=0,
        last_rating=None,
        reviewed_at=None,
    )
    snap = snapshot_review(review)
    assert snap["reviewed_at"] is None
    restore_review(review, snap)
    assert review.reviewed_at is None and review.last_rating is None


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
