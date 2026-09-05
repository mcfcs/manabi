"""SRS review-queue behaviour: interval previews (and later: ordering, undo,
leeches) — pure functions, no DB."""

import types
from datetime import UTC, date, datetime, timedelta

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


# ── Session ordering ───────────────────────────────────────────────────────

from manabi_server.srs import QueueItem, order_queue  # noqa: E402


def _rev(card_id, module_id, days_overdue, ease=2.5):
    return QueueItem(card_id, module_id, TODAY - timedelta(days=days_overdue), ease)


def _new(card_id, module_id):
    return QueueItem(card_id, module_id, None)


def test_reviews_come_before_new_cards_and_interleave_modules():
    items = [
        _new(101, 1),
        _new(102, 1),
        _new(201, 2),
        _rev(1, 1, 3),
        _rev(2, 1, 2),
        _rev(3, 2, 1),
        _rev(4, 2, 5),
    ]
    ordered, new_total = order_queue(items)
    assert new_total == 3
    # module 2 holds the most overdue card (4, 5 days) so it leads the
    # round-robin; within a module, most overdue first.
    assert ordered[:4] == [4, 1, 3, 2]
    # new cards follow, interleaved across modules in creation order
    assert ordered[4:] == [101, 201, 102]


def test_weakest_ease_first_on_equal_due_dates():
    items = [_rev(1, 1, 2, ease=2.5), _rev(2, 1, 2, ease=1.3), _rev(3, 1, 2, ease=2.8)]
    ordered, _ = order_queue(items)
    assert ordered == [2, 1, 3]


def test_new_card_cap_and_offset_page_through_the_backlog():
    items = [_new(i, 1 + (i % 3)) for i in range(50)]
    first, total = order_queue(items, new_cap=20)
    assert total == 50 and len(first) == 20
    second, _ = order_queue(items, new_cap=20, new_offset=20)
    third, _ = order_queue(items, new_cap=20, new_offset=40)
    assert len(second) == 20 and len(third) == 10
    assert not (set(first) & set(second)) and not (set(second) & set(third))
    assert set(first) | set(second) | set(third) == {i for i in range(50)}
    # the interleave spreads the first page over all three modules
    assert {1 + (i % 3) for i in first} == {1, 2, 3}


def test_empty_queue():
    assert order_queue([]) == ([], 0)


# ── Leeches ────────────────────────────────────────────────────────────────

from manabi_server.srs import LEECH_LAPSES, is_leech  # noqa: E402


def test_leech_threshold_matches_anki_default():
    assert LEECH_LAPSES == 8
    assert not is_leech(ReviewState(lapses=7))
    assert is_leech(ReviewState(lapses=8))
    assert is_leech(ReviewState(lapses=20))


def test_eighth_again_crosses_the_leech_line():
    state = ReviewState(interval_days=1.0, ease=1.3, reps=1, lapses=7)
    new_state, _ = apply_rating(state, "again", TODAY)
    assert is_leech(new_state) and not is_leech(state)


def test_snapshot_carries_leech_flag_for_undo():
    review = types.SimpleNamespace(
        due_date=TODAY,
        interval_days=1.0,
        ease=1.3,
        reps=1,
        lapses=7,
        last_rating="again",
        reviewed_at=None,
        is_leech=False,
    )
    snap = snapshot_review(review)
    review.is_leech = True  # the rating that tipped it over
    restore_review(review, snap)
    assert review.is_leech is False
