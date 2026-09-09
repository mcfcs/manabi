"""Syllabus-weighted grade math (pure functions, easily tested).

The syllabus, not Canvas, owns the breakdown: a course is a set of weighted
components ("Quizzes 30%") and each component holds scored items. Two rules
drive everything:

- **Only graded work counts.** A component with nothing graded yet is left out
  and the remaining weights are renormalised, so an untouched Project never
  reads as a zero.
- **Nothing is capped.** Extra credit may push a component (and the standing)
  above 100.

Letters are always exactly A / B+ / B / C+ / C / D / F; only the cutoffs vary,
per course, from its syllabus.
"""

from dataclasses import dataclass

# Fixed letter ladder, best first. F is implicit: below the D cutoff.
LETTERS = ("A", "B+", "B", "C+", "C", "D", "F")
GRADED_LETTERS = LETTERS[:-1]  # the six that carry a cutoff

# Ateneo 4.0 scale — quality points per letter, for QPI.
QPI_POINTS = {"A": 4.0, "B+": 3.5, "B": 3.0, "C+": 2.5, "C": 2.0, "D": 1.0, "F": 0.0}

# Starting point for a course that has no scheme yet; the user edits it to
# match the syllabus.
DEFAULT_CUTOFFS = {"A": 93.0, "B+": 87.0, "B": 81.0, "C+": 75.0, "C": 69.0, "D": 60.0}


@dataclass(frozen=True)
class Item:
    """One score. Either points (earned/possible) or a straight percent;
    `earned is None` means Canvas has not graded it yet."""

    earned: float | None = None
    possible: float | None = None
    percent: float | None = None


@dataclass(frozen=True)
class Component:
    """One weighted section of the syllabus breakdown."""

    name: str
    weight: float
    items: tuple[Item, ...] = ()


@dataclass(frozen=True)
class Standing:
    percent: float | None  # None until something is graded
    counted_weight: float  # weight of the components that have a grade
    total_weight: float  # weight of every component, graded or not


# ── One item ────────────────────────────────────────────────────────────────


def item_percent(item: Item) -> float | None:
    """The item as a percent, or None when it is not graded yet."""
    if item.percent is not None:
        return float(item.percent)
    if item.earned is None or item.possible is None or item.possible <= 0:
        return None
    return 100.0 * float(item.earned) / float(item.possible)


def item_points(item: Item) -> tuple[float, float] | None:
    """(earned, possible) for totalling, or None when not graded. A percent
    row counts as that many points out of 100."""
    if item.percent is not None:
        return float(item.percent), 100.0
    if item.earned is None or item.possible is None or item.possible <= 0:
        return None
    return float(item.earned), float(item.possible)


# ── One component ───────────────────────────────────────────────────────────


def component_percent(items) -> float | None:
    """Total points across the graded items: sum(earned) / sum(possible).
    None when nothing in the component is graded. Never capped."""
    earned = possible = 0.0
    graded = False
    for item in items:
        pts = item_points(item)
        if pts is None:
            continue
        graded = True
        earned += pts[0]
        possible += pts[1]
    if not graded or possible <= 0:
        return None
    return 100.0 * earned / possible


# ── The course ──────────────────────────────────────────────────────────────


def standing(components) -> Standing:
    """Weighted percent over the components that have a grade, renormalised by
    their own weight sum."""
    total = 0.0
    counted = 0.0
    weighted = 0.0
    for comp in components:
        weight = float(comp.weight)
        total += weight
        pct = component_percent(comp.items)
        if pct is None or weight <= 0:
            continue
        counted += weight
        weighted += pct * weight
    percent = weighted / counted if counted > 0 else None
    return Standing(percent=percent, counted_weight=counted, total_weight=total)


def letter_for(percent: float | None, cutoffs: dict[str, float] | None) -> str | None:
    """First letter whose cutoff the percent reaches; F below them all."""
    if percent is None or not cutoffs:
        return None
    for letter in GRADED_LETTERS:
        minimum = cutoffs.get(letter)
        if minimum is not None and percent >= float(minimum):
            return letter
    return "F"


def cutoff_for(letter: str, cutoffs: dict[str, float] | None) -> float | None:
    if not cutoffs or letter == "F":
        return None
    value = cutoffs.get(letter)
    return float(value) if value is not None else None


def needed_on_remaining(
    target_percent: float,
    standing_percent: float | None,
    counted_weight: float,
    total_weight: float,
) -> float | None:
    """The average mark the ungraded weight must earn to finish at
    `target_percent` overall. None when no weight remains (or none exists).
    May come back above 100 (unreachable) or at/below 0 (already secured)."""
    remaining = total_weight - counted_weight
    if remaining <= 0 or total_weight <= 0:
        return None
    have = (standing_percent or 0.0) * counted_weight
    return (target_percent * total_weight - have) / remaining


# ── QPI ─────────────────────────────────────────────────────────────────────


def quality_points(letter: str | None) -> float | None:
    return QPI_POINTS.get(letter) if letter else None


def term_qpi(entries) -> float | None:
    """Σ(quality points × units) / Σ(units) over (letter, units) pairs that
    have a letter and positive units. None when nothing qualifies."""
    points = 0.0
    units_total = 0.0
    for letter, units in entries:
        pts = quality_points(letter)
        unit_value = float(units or 0)
        if pts is None or unit_value <= 0:
            continue
        points += pts * unit_value
        units_total += unit_value
    return points / units_total if units_total > 0 else None


# ── Validation ──────────────────────────────────────────────────────────────


def validate_cutoffs(cutoffs: dict[str, float]) -> dict[str, float]:
    """Normalise and check a scheme: exactly the six graded letters, each
    0–100, strictly descending down the ladder. Raises ValueError."""
    missing = [letter for letter in GRADED_LETTERS if letter not in cutoffs]
    if missing:
        raise ValueError(f"missing cutoffs for {', '.join(missing)}")
    extra = [key for key in cutoffs if key not in GRADED_LETTERS]
    if extra:
        raise ValueError(f"unknown letters: {', '.join(sorted(extra))}")
    clean: dict[str, float] = {}
    previous: float | None = None
    for letter in GRADED_LETTERS:
        try:
            value = float(cutoffs[letter])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{letter} cutoff must be a number") from exc
        if not 0 <= value <= 100:
            raise ValueError(f"{letter} cutoff must be between 0 and 100")
        if previous is not None and value >= previous:
            raise ValueError(f"{letter} cutoff must be below the one above it")
        clean[letter] = value
        previous = value
    return clean
