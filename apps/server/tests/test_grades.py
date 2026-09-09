"""Syllabus-weighted grade math — pure functions, no DB."""

import pytest
from manabi_server.grades import (
    DEFAULT_CUTOFFS,
    GRADED_LETTERS,
    LETTERS,
    QPI_POINTS,
    Component,
    Item,
    component_percent,
    item_percent,
    letter_for,
    needed_on_remaining,
    standing,
    term_qpi,
    validate_cutoffs,
)

# The user's own SocSc example: A at 93, B+ at 88.
SOCSC = {"A": 93.0, "B+": 88.0, "B": 83.0, "C+": 78.0, "C": 73.0, "D": 65.0}


def test_letter_ladder_is_fixed():
    assert LETTERS == ("A", "B+", "B", "C+", "C", "D", "F")
    assert GRADED_LETTERS == ("A", "B+", "B", "C+", "C", "D")
    assert QPI_POINTS == {"A": 4.0, "B+": 3.5, "B": 3.0, "C+": 2.5, "C": 2.0, "D": 1.0, "F": 0.0}


# ── Items ───────────────────────────────────────────────────────────────────


def test_item_percent_handles_points_percent_and_ungraded():
    assert item_percent(Item(earned=18, possible=20)) == 90.0
    assert item_percent(Item(percent=95)) == 95.0
    assert item_percent(Item(earned=None, possible=20)) is None  # not graded yet
    assert item_percent(Item()) is None
    assert item_percent(Item(earned=5, possible=0)) is None  # never divide by zero


def test_item_percent_allows_extra_credit_over_100():
    assert item_percent(Item(earned=22, possible=20)) == 110.0


# ── Components ──────────────────────────────────────────────────────────────


def test_component_totals_points_not_the_mean_of_percents():
    # 7/10.01, 9/10.01, 9.01/10.01 — CSCI 60's real quiz scores
    items = [Item(7, 10.01), Item(9, 10.01), Item(9.01, 10.01)]
    assert component_percent(items) == pytest.approx(100 * 25.01 / 30.03, rel=1e-9)


def test_component_ignores_ungraded_items_until_they_are_scored():
    graded_only = [Item(20, 20), Item(None, 20)]
    assert component_percent(graded_only) == 100.0
    assert component_percent([Item(None, 20), Item(None, 10)]) is None
    assert component_percent([]) is None


def test_component_mixes_percent_rows_as_hundred_point_items():
    assert component_percent([Item(percent=95)]) == 95.0
    # 18/20 plus a 90% row → (18 + 90) / (20 + 100)
    assert component_percent([Item(18, 20), Item(percent=90)]) == pytest.approx(90.0)


# ── Standing (the renormalisation rule) ─────────────────────────────────────


def _socsc_components():
    """The user's example: Project has nothing yet, so 80% of the weight counts."""
    return [
        Component("Participation", 10, (Item(percent=95),)),
        Component("Quizzes", 30, (Item(27, 30), Item(24, 30))),  # 85%
        Component("Paper", 40, (Item(88, 100),)),
        Component("Project", 20, ()),  # untouched
    ]


def test_standing_renormalises_over_graded_weight_only():
    result = standing(_socsc_components())
    assert result.counted_weight == 80.0
    assert result.total_weight == 100.0
    # (95*10 + 85*30 + 88*40) / 80 — NOT divided by 100
    assert result.percent == pytest.approx((950 + 2550 + 3520) / 80)
    assert result.percent == pytest.approx(87.75)


def test_standing_is_none_until_something_is_graded():
    result = standing([Component("Paper", 100, ()), Component("Exam", 0, ())])
    assert result.percent is None
    assert result.counted_weight == 0.0
    assert result.total_weight == 100.0


def test_standing_ignores_zero_weight_components():
    result = standing(
        [Component("Graded", 50, (Item(9, 10),)), Component("Zero", 0, (Item(1, 10),))]
    )
    assert result.percent == 90.0
    assert result.counted_weight == 50.0


# ── Letters ─────────────────────────────────────────────────────────────────


def test_letter_boundaries_are_inclusive_at_the_cutoff():
    assert letter_for(93.0, SOCSC) == "A"  # exactly the cutoff
    assert letter_for(92.99, SOCSC) == "B+"
    assert letter_for(92.5, SOCSC) == "B+"  # the user's example
    assert letter_for(90.0, SOCSC) == "B+"  # the user's example
    assert letter_for(88.0, SOCSC) == "B+"
    assert letter_for(87.99, SOCSC) == "B"
    assert letter_for(64.9, SOCSC) == "F"
    assert letter_for(0.0, SOCSC) == "F"


def test_letter_needs_a_percent_and_a_scheme():
    assert letter_for(None, SOCSC) is None
    assert letter_for(90.0, None) is None
    assert letter_for(90.0, {}) is None


def test_letter_above_one_hundred_is_still_the_top_grade():
    assert letter_for(104.0, DEFAULT_CUTOFFS) == "A"


# ── Target calculator ───────────────────────────────────────────────────────


def test_needed_on_remaining_matches_the_arithmetic():
    result = standing(_socsc_components())
    # to finish at 93 (an A) with 87.75 over 80% counted and 20% remaining
    needed = needed_on_remaining(93.0, result.percent, result.counted_weight, result.total_weight)
    assert needed == pytest.approx((93 * 100 - 87.75 * 80) / 20)
    assert needed == pytest.approx(114.0)  # unreachable — caller flags it


def test_needed_on_remaining_can_be_already_secured_or_impossible():
    # 100% so far over 80% of the weight; a B+ at 88 needs only 40 on the rest
    assert needed_on_remaining(88.0, 100.0, 80.0, 100.0) == pytest.approx(40.0)
    # nothing left to earn
    assert needed_on_remaining(93.0, 90.0, 100.0, 100.0) is None
    assert needed_on_remaining(93.0, None, 0.0, 0.0) is None
    # nothing graded yet: the whole weight must average the target
    assert needed_on_remaining(93.0, None, 0.0, 100.0) == pytest.approx(93.0)


# ── QPI ─────────────────────────────────────────────────────────────────────


def test_term_qpi_weights_letters_by_units():
    # A(4.0)×3 + B+(3.5)×3 + B(3.0)×1 = 12 + 10.5 + 3 = 25.5 over 7 units
    assert term_qpi([("A", 3), ("B+", 3), ("B", 1)]) == pytest.approx(25.5 / 7)


def test_term_qpi_skips_courses_without_a_letter_or_units():
    assert term_qpi([("A", 3), (None, 3), ("B", 0)]) == 4.0
    assert term_qpi([(None, 3)]) is None
    assert term_qpi([]) is None
    assert term_qpi([("F", 3), ("A", 3)]) == pytest.approx(2.0)


# ── Cutoff validation ───────────────────────────────────────────────────────


def test_validate_cutoffs_accepts_a_descending_scheme():
    assert validate_cutoffs(dict(SOCSC)) == SOCSC
    assert validate_cutoffs({k: str(v) for k, v in SOCSC.items()}) == SOCSC  # coerces


def test_validate_cutoffs_rejects_bad_schemes():
    with pytest.raises(ValueError, match="missing cutoffs for D"):
        validate_cutoffs({k: v for k, v in SOCSC.items() if k != "D"})
    with pytest.raises(ValueError, match="unknown letters: B-"):
        validate_cutoffs({**SOCSC, "B-": 70})
    with pytest.raises(ValueError, match="B\\+ cutoff must be below"):
        validate_cutoffs({**SOCSC, "B+": 93.0})  # equal to A
    with pytest.raises(ValueError, match="between 0 and 100"):
        validate_cutoffs({**SOCSC, "A": 101.0})
    with pytest.raises(ValueError, match="must be a number"):
        validate_cutoffs({**SOCSC, "A": "high"})
