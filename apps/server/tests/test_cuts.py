"""Cuts & lates: totals math (late = 0.5) and endpoint guards."""

import types

import pytest
from fastapi import HTTPException
from manabi_server.api.cuts import CutIn, add_cut, cuts_used


def test_cuts_used_weights():
    assert cuts_used([]) == 0
    assert cuts_used(["cut"]) == 1.0
    assert cuts_used(["late"]) == 0.5
    assert cuts_used(["cut", "late", "late"]) == 2.0
    assert cuts_used(["bogus"]) == 0  # junk rows never crash the total


class _FakeDB:
    def __init__(self, course=None):
        self.course = course
        self.added = []

    async def get(self, model, pk):
        return self.course

    def add(self, obj):
        self.added.append(obj)
        obj.id = 1

    async def commit(self):
        pass


class _User:
    id = 1


async def test_add_cut_rejects_bad_kind():
    with pytest.raises(HTTPException) as exc:
        await add_cut(
            CutIn(course_id=1, date="2026-08-29", kind="absent"),
            user=_User(),
            db=_FakeDB(),
        )
    assert exc.value.status_code == 422


async def test_add_cut_foreign_course_404():
    foreign = types.SimpleNamespace(id=1, user_id=999)
    with pytest.raises(HTTPException) as exc:
        await add_cut(
            CutIn(course_id=1, date="2026-08-29"),
            user=_User(),
            db=_FakeDB(foreign),
        )
    assert exc.value.status_code == 404


async def test_add_cut_trims_reason_and_returns_shape():
    mine = types.SimpleNamespace(id=1, user_id=1)
    db = _FakeDB(mine)
    out = await add_cut(
        CutIn(course_id=1, date="2026-08-29", kind="late", reason="  traffic  "),
        user=_User(),
        db=db,
    )
    assert out.kind == "late"
    assert out.reason == "traffic"
    assert str(out.date) == "2026-08-29"
    assert db.added[0].reason == "traffic"
