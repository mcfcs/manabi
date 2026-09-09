"""Grades endpoints: ownership guards, score validation, Canvas mapping."""

import types

import pytest
from fastapi import HTTPException
from manabi_core.models import GradeItem
from manabi_server.api.grades import (
    ComponentIn,
    CutoffsIn,
    ItemIn,
    _canvas_score,
    _component_out,
    _course_grades_out,
    _validated_score,
    add_component,
    set_cutoffs,
)

SOCSC = {"A": 93.0, "B+": 88.0, "B": 83.0, "C+": 78.0, "C": 73.0, "D": 65.0}


class _User:
    id = 1


class _FakeDB:
    """Enough of AsyncSession for the endpoints that only touch one course."""

    def __init__(self, course=None, count=0):
        self.course = course
        self.count = count
        self.added = []
        self.committed = False

    async def get(self, model, pk):
        return self.course

    async def execute(self, _stmt):
        return types.SimpleNamespace(scalar_one=lambda: self.count)

    def add(self, obj):
        self.added.append(obj)
        obj.id = 1

    async def commit(self):
        self.committed = True


def _course(**kw):
    fields = {
        "id": 1,
        "user_id": 1,
        "code": "SocSc 14",
        "name": "Politics",
        "accent_color": "#C93A2E",
        "units": 3.0,
        "canvas_course_id": 70265,
        "grade_cutoffs": None,
    }
    return types.SimpleNamespace(**{**fields, **kw})


# ── Score validation ────────────────────────────────────────────────────────


def test_a_score_is_points_or_a_percent_never_both():
    assert _validated_score(18, 20, None) == (18, 20, None)
    assert _validated_score(None, None, 95) == (None, None, 95)
    assert _validated_score(None, 20, None) == (None, 20, None)  # linked, ungraded
    with pytest.raises(HTTPException) as exc:
        _validated_score(18, 20, 90)
    assert exc.value.status_code == 422


def test_points_need_a_positive_possible():
    with pytest.raises(HTTPException) as exc:
        _validated_score(5, 0, None)
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        _validated_score(5, None, None)  # earned without possible
    assert exc.value.status_code == 422


# ── Ownership + component guards ────────────────────────────────────────────


async def test_add_component_on_a_foreign_course_is_404():
    with pytest.raises(HTTPException) as exc:
        await add_component(
            1,
            ComponentIn(name="Quizzes", weight=30),
            user=_User(),
            db=_FakeDB(_course(user_id=999)),
        )
    assert exc.value.status_code == 404


async def test_add_component_rejects_a_blank_name_or_zero_weight():
    for payload in (ComponentIn(name="   ", weight=30), ComponentIn(name="Quizzes", weight=0)):
        with pytest.raises(HTTPException) as exc:
            await add_component(1, payload, user=_User(), db=_FakeDB(_course()))
        assert exc.value.status_code == 422


async def test_add_component_positions_after_the_existing_ones():
    db = _FakeDB(_course(), count=2)
    out = await add_component(1, ComponentIn(name="  Quizzes  ", weight=30), user=_User(), db=db)
    assert out.name == "Quizzes" and out.weight == 30.0 and out.position == 2
    assert out.percent is None and out.item_count == 0
    assert db.committed


# ── Cutoffs ─────────────────────────────────────────────────────────────────


async def test_set_cutoffs_rejects_a_non_descending_scheme():
    db = _FakeDB(_course())
    with pytest.raises(HTTPException) as exc:
        await set_cutoffs(1, CutoffsIn(cutoffs={**SOCSC, "B+": 95.0}), user=_User(), db=db)
    assert exc.value.status_code == 422
    assert "below" in exc.value.detail


# ── Serialisation ───────────────────────────────────────────────────────────


def _item(**kw):
    return types.SimpleNamespace(
        id=kw.pop("id", 1),
        title=kw.pop("title", "Quiz 1"),
        earned=kw.pop("earned", None),
        possible=kw.pop("possible", None),
        percent=kw.pop("percent", None),
        canvas_assignment_id=kw.pop("canvas_assignment_id", None),
        **kw,
    )


def test_component_out_marks_ungraded_rows_and_rounds_the_percent():
    comp = types.SimpleNamespace(id=1, name="Quizzes", weight=30.0, position=0)
    items = [
        _item(id=1, title="Quiz 1", earned=7, possible=10.01),
        _item(id=2, title="Quiz 2", earned=None, possible=10.01),  # not graded yet
    ]
    out = _component_out(comp, items)
    assert out.graded_count == 1 and out.item_count == 2
    assert out.items[1].graded is False and out.items[1].value_percent is None
    assert out.percent == pytest.approx(69.93, abs=0.01)  # 7 / 10.01


def test_course_grades_out_renormalises_and_offers_only_reachable_targets():
    course = _course(grade_cutoffs=SOCSC)
    pairs = [
        (
            types.SimpleNamespace(id=1, name="Quizzes", weight=30.0, position=0),
            [_item(earned=27, possible=30)],  # 90%
        ),
        (
            types.SimpleNamespace(id=2, name="Project", weight=20.0, position=1),
            [],  # nothing graded — must not drag the standing down
        ),
    ]
    out = _course_grades_out(course, pairs)
    assert out.percent == 90.0  # not 90*30/50
    assert out.letter == "B+"
    assert out.counted_weight == 30.0 and out.total_weight == 50.0
    assert out.units == 3.0
    # only letters above the current standing are chased
    assert [t.letter for t in out.targets] == ["A"]
    target = out.targets[0]
    assert target.cutoff == 93.0
    assert target.needed == pytest.approx((93 * 50 - 90 * 30) / 20)  # 97.5
    assert target.reachable is True


def test_course_grades_out_without_cutoffs_has_no_letter_or_targets():
    out = _course_grades_out(_course(), [])
    assert out.letter is None and out.targets == [] and out.percent is None
    assert out.default_cutoffs["A"] == 93.0  # the template to start from


# ── Canvas mapping ──────────────────────────────────────────────────────────


def test_canvas_score_reads_the_submission_and_treats_excused_as_ungraded():
    graded = {"points_possible": 10.01, "submission": {"score": 9.01, "workflow_state": "graded"}}
    assert _canvas_score(graded) == (9.01, 10.01)

    submitted = {
        "points_possible": 20.0,
        "submission": {"score": None, "workflow_state": "submitted"},
    }
    assert _canvas_score(submitted) == (None, 20.0)

    excused = {"points_possible": 20.0, "submission": {"score": 15, "excused": True}}
    assert _canvas_score(excused) == (None, 20.0)  # excused never counts

    assert _canvas_score({"points_possible": None}) == (None, None)  # no submission at all


def test_grade_item_model_accepts_a_canvas_link():
    item = GradeItem(
        component_id=1, title="Quiz 1", earned=7, possible=10.01, canvas_assignment_id=99
    )
    assert item.canvas_assignment_id == 99 and item.percent is None


def test_item_in_defaults_to_an_ungraded_row():
    payload = ItemIn(title="Long Exam 2", possible=130)
    assert payload.earned is None and payload.percent is None
