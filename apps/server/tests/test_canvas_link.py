"""Canvas ↔ course linking: canvas_course_id is a first-class course field."""

import types

import pytest
from fastapi import HTTPException
from manabi_server.api.courses import (
    CourseIn,
    CourseOut,
    CoursePatch,
    _commit_course,
    _course_out,
    canvas_link_conflict,
)
from sqlalchemy.exc import IntegrityError


def test_patch_distinguishes_unset_from_null():
    assert "canvas_course_id" not in CoursePatch(name="x").model_dump(exclude_unset=True)
    assert CoursePatch(canvas_course_id=None).model_dump(exclude_unset=True) == {
        "canvas_course_id": None
    }
    assert CoursePatch(canvas_course_id=70265).canvas_course_id == 70265


def test_course_in_accepts_optional_canvas_id():
    assert CourseIn(code="A", name="B").canvas_course_id is None
    assert CourseIn(code="A", name="B", canvas_course_id=7).model_dump()["canvas_course_id"] == 7


def test_course_out_carries_id_and_derived_url():
    course = types.SimpleNamespace(
        id=1,
        code="CSCI 70",
        name="SIPL",
        description=None,
        instructor=None,
        term=None,
        accent_color=None,
        position=0,
        canvas_course_id=67328,
        meeting_url=None,
        cover_image_path=None,
        units=3.0,
        cut_allowance=None,
        archived_at=None,
    )
    out = _course_out(course, module_count=2)
    assert isinstance(out, CourseOut)
    assert out.canvas_course_id == 67328
    assert out.units == 3.0
    assert out.canvas_url is not None and out.canvas_url.endswith("/courses/67328")
    course.canvas_course_id = None
    unlinked = _course_out(course, module_count=2)
    assert unlinked.canvas_course_id is None and unlinked.canvas_url is None


def test_conflict_detail_names_other_course():
    other = types.SimpleNamespace(code="CSCI 60")
    detail = canvas_link_conflict(other)
    assert detail["conflict"] == "canvas_course_id"
    assert detail["course_code"] == "CSCI 60"
    assert "CSCI 60" in detail["message"]
    assert canvas_link_conflict(None)["course_code"] is None


class _Result:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _Db:
    def __init__(self, error, other=None):
        self._error = error
        self._other = other
        self.rolled_back = False

    async def commit(self):
        if self._error is not None:
            raise self._error

    async def rollback(self):
        self.rolled_back = True

    async def execute(self, _stmt):
        return _Result(self._other)


def _integrity(msg: str) -> IntegrityError:
    return IntegrityError("INSERT …", {}, Exception(msg))


@pytest.mark.asyncio
async def test_commit_maps_canvas_unique_violation_to_409():
    user = types.SimpleNamespace(id=1)
    other = types.SimpleNamespace(code="CSCI 60")
    msg = 'duplicate key value violates unique constraint "uq_courses_canvas_course_id"'
    db = _Db(_integrity(msg), other)
    with pytest.raises(HTTPException) as exc:
        await _commit_course(db, user, 67302)
    assert exc.value.status_code == 409
    assert exc.value.detail["course_code"] == "CSCI 60"
    assert db.rolled_back


@pytest.mark.asyncio
async def test_commit_reraises_other_integrity_errors():
    db = _Db(_integrity("null value in column code violates not-null constraint"))
    with pytest.raises(IntegrityError):
        await _commit_course(db, types.SimpleNamespace(id=1), None)
    assert db.rolled_back


@pytest.mark.asyncio
async def test_commit_passes_through_on_success():
    db = _Db(None)
    await _commit_course(db, types.SimpleNamespace(id=1), 5)
    assert not db.rolled_back
