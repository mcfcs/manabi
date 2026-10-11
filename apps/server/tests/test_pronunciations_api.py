"""Pronunciation list endpoints: respellings are stored the way the voice can say them."""

import types

import pytest
from fastapi import HTTPException
from manabi_server.api.pronunciations import PronunciationIn, _clean_say, add_pronunciation


def test_hyphens_become_spaces():
    # the voice spells out the short pieces of a hyphenated respelling
    assert _clean_say("trah-poh") == "trah poh"
    assert _clean_say("  Keem   Poe ") == "Keem Poe"


class _DB:
    def __init__(self, course):
        self.course = course
        self.added = []

    async def get(self, model, pk):
        return self.course

    async def execute(self, stmt):
        return types.SimpleNamespace(scalar_one_or_none=lambda: None)

    def add(self, obj):
        obj.id = 1
        self.added.append(obj)

    async def commit(self):
        pass


async def test_a_typed_term_is_the_users():
    db = _DB(types.SimpleNamespace(id=4, user_id=1))
    out = await add_pronunciation(
        4, PronunciationIn(term="Quimpo", say="Keem-Poe"), user=types.SimpleNamespace(id=1), db=db
    )
    assert (out.say, out.source, out.match) == ("Keem Poe", "user", None)


async def test_someone_elses_course_is_404():
    db = _DB(types.SimpleNamespace(id=4, user_id=9))
    with pytest.raises(HTTPException) as exc:
        await add_pronunciation(
            4, PronunciationIn(term="x1", say="y"), user=types.SimpleNamespace(id=1), db=db
        )
    assert exc.value.status_code == 404
