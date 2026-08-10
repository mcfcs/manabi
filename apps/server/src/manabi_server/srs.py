"""SM-2-lite spaced repetition scheduling (pure functions, easily tested).

Ratings: again (lapse, back to today), hard (×1.2, ease −0.15),
good (×ease), easy (×ease×1.3, ease +0.15). Ease clamped 1.3–2.8,
interval capped at 365 days.
"""

from dataclasses import dataclass
from datetime import date, timedelta

EASE_MIN = 1.3
EASE_MAX = 2.8
INTERVAL_CAP = 365.0

RATINGS = ("again", "hard", "good", "easy")


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
    new_state = ReviewState(
        interval_days=interval, ease=ease, reps=reps, lapses=lapses
    )
    due = today + timedelta(days=round(interval))
    return new_state, due
