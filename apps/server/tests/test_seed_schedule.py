"""seed_schedule reads its (personal) data from JSON, never from code."""

import json

import pytest
from manabi_server import seed_schedule as ss


def test_example_file_parses_into_typed_seed():
    seed = ss.load_seed(ss.EXAMPLE_SEED)
    assert seed.source == ss.EXAMPLE_SEED
    assert seed.term
    assert len(seed.courses) >= 1
    first = seed.courses[0]
    assert isinstance(first.code, str) and first.code
    assert isinstance(first.canvas_course_id, int)
    for block in first.blocks:
        assert 0 <= block.day <= 6
        assert block.start < block.end
    # a TBA course keeps an empty block tuple and null optionals
    tba = seed.courses[-1]
    assert tba.blocks == ()
    assert tba.instructor is None and tba.canvas_course_id is None


def test_env_override_wins(tmp_path, monkeypatch):
    path = tmp_path / "seed.json"
    path.write_text(
        json.dumps({"term": "T", "courses": [{"code": "X 1", "name": "N"}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("MANABI_SEED_FILE", str(path))
    assert ss.seed_path() == path
    seed = ss.load_seed()
    assert seed.courses[0].blocks == ()
    assert seed.courses[0].instructor is None


def test_missing_local_file_refuses_unless_example_allowed(tmp_path, monkeypatch):
    monkeypatch.delenv("MANABI_SEED_FILE", raising=False)
    monkeypatch.setattr(ss, "LOCAL_SEED", tmp_path / "absent.json")
    with pytest.raises(SystemExit):
        ss.seed_path()
    assert ss.seed_path(allow_example=True) == ss.EXAMPLE_SEED


def test_block_validation(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "term": "T",
                "courses": [
                    {
                        "code": "X",
                        "name": "N",
                        "blocks": [{"day": 7, "start": 0, "end": 10}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        ss.load_seed(bad)
