"""SM-2-lite spaced repetition scheduling (pure functions, easily tested).

Ratings: again (lapse, back to today), hard (×1.2, ease −0.15),
good (×ease), easy (×ease×1.3, ease +0.15). Ease clamped 1.3–2.8,
interval capped at 365 days.
"""

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

EASE_MIN = 1.3
EASE_MAX = 2.8
INTERVAL_CAP = 365.0

RATINGS = ("again", "hard", "good", "easy")

# A card that keeps lapsing is a "leech" (Anki's default threshold): it is
# suspended and surfaced on the Review page for a rewrite or a reset instead
# of soaking up sessions.
LEECH_LAPSES = 8


def is_leech(state: "ReviewState") -> bool:
    return state.lapses >= LEECH_LAPSES


@dataclass
class ReviewState:
    interval_days: float = 0.0
    ease: float = 2.5
    reps: int = 0
    lapses: int = 0


def apply_rating(state: ReviewState, rating: str, today: date) -> tuple[ReviewState, date]:
    """Returns (new_state, next_due_date)."""
    interval, ease = state.interval_days, state.ease
    reps, lapses = state.reps, state.lapses

    if rating == "again":
        lapses += 1
        reps = 0
        interval = 0.0
        ease = max(EASE_MIN, ease - 0.2)
    elif rating == "hard":
        reps += 1
        interval = max(1.0, interval * 1.2) if interval else 1.0
        ease = max(EASE_MIN, ease - 0.15)
    elif rating == "good":
        reps += 1
        interval = interval * ease if interval else 1.0
    elif rating == "easy":
        reps += 1
        interval = interval * ease * 1.3 if interval else 2.0
        ease = min(EASE_MAX, ease + 0.15)
    else:
        raise ValueError(f"unknown rating {rating!r}")

    interval = min(interval, INTERVAL_CAP)
    new_state = ReviewState(interval_days=interval, ease=ease, reps=reps, lapses=lapses)
    due = today + timedelta(days=round(interval))
    return new_state, due


def snapshot_review(review) -> dict:
    """JSON-safe copy of a CardReview's scheduling fields, stored on the row
    before a rating overwrites it so the rating can be undone."""
    return {
        "due_date": review.due_date.isoformat(),
        "interval_days": review.interval_days,
        "ease": review.ease,
        "reps": review.reps,
        "lapses": review.lapses,
        "last_rating": review.last_rating,
        "reviewed_at": review.reviewed_at.isoformat() if review.reviewed_at else None,
        "is_leech": bool(getattr(review, "is_leech", False)),
    }


def restore_review(review, snap: dict) -> None:
    """Inverse of snapshot_review: write the saved fields back onto the row."""
    review.due_date = date.fromisoformat(snap["due_date"])
    review.interval_days = float(snap["interval_days"])
    review.ease = float(snap["ease"])
    review.reps = int(snap["reps"])
    review.lapses = int(snap["lapses"])
    review.last_rating = snap.get("last_rating")
    review.reviewed_at = (
        datetime.fromisoformat(snap["reviewed_at"]) if snap.get("reviewed_at") else None
    )
    review.is_leech = bool(snap.get("is_leech", False))


def preview_intervals(state: ReviewState, today: date) -> dict[str, int]:
    """Days until the next review for each rating — shown on the rating
    buttons so the choice is informed (Anki-style "4d / 12d")."""
    return {rating: (apply_rating(state, rating, today)[1] - today).days for rating in RATINGS}


# ── Session ordering ────────────────────────────────────────────────────────

NEW_CARDS_PER_LOAD = 20


@dataclass(frozen=True)
class QueueItem:
    card_id: int
    module_id: int
    due_date: date | None  # None = never reviewed
    ease: float = 2.5


def _round_robin(groups: list[list[int]]) -> list[int]:
    """Interleave lists element by element, preserving each list's order."""
    queues = [deque(g) for g in groups if g]
    out: list[int] = []
    while queues:
        for q in list(queues):
            out.append(q.popleft())
            if not q:
                queues.remove(q)
    return out


def _interleave_by_module(items: list[QueueItem]) -> list[int]:
    """Group by module in the order the modules first appear in `items`
    (which is already sorted by priority), then round-robin across them."""
    by_module: dict[int, list[int]] = {}
    for it in items:
        by_module.setdefault(it.module_id, []).append(it.card_id)
    return _round_robin(list(by_module.values()))


def order_queue(
    items: Iterable[QueueItem],
    *,
    new_cap: int = NEW_CARDS_PER_LOAD,
    new_offset: int = 0,
) -> tuple[list[int], int]:
    """Session order for the due queue.

    Reviews (cards with a due date) come first, most overdue first and the
    weakest ease first on ties; never-reviewed cards follow, capped at
    ``new_cap`` after skipping ``new_offset`` (so a freshly generated deck
    cannot flood a session). Within both groups cards round-robin across
    modules so one deck never monopolises the run.

    Returns (ordered card ids, total number of never-reviewed cards).
    """
    items = list(items)
    reviews = sorted(
        (i for i in items if i.due_date is not None),
        key=lambda i: (i.due_date, i.ease, i.card_id),
    )
    fresh = sorted((i for i in items if i.due_date is None), key=lambda i: i.card_id)
    ordered_new = _interleave_by_module(fresh)
    start = max(0, new_offset)
    return _interleave_by_module(reviews) + ordered_new[start : start + max(0, new_cap)], len(fresh)


# ── Stats helpers ───────────────────────────────────────────────────────────


def forecast(today: date, due_dates: Iterable[date | None], days: int = 7) -> list[int]:
    """Cards due on each of the next ``days`` days. Day 0 bundles everything
    due today or earlier (and never-reviewed cards, which are due now)."""
    counts = [0] * days
    for d in due_dates:
        if d is None or d <= today:
            counts[0] += 1
            continue
        offset = (d - today).days
        if offset < days:
            counts[offset] += 1
    return counts


def retention(last_ratings: Iterable[str | None]) -> float | None:
    """Share of recent reviews rated good/easy; None when there were none.
    (Approximation: card_reviews keeps only each card's LAST rating.)"""
    ratings = [r for r in last_ratings if r]
    if not ratings:
        return None
    return sum(1 for r in ratings if r in ("good", "easy")) / len(ratings)
