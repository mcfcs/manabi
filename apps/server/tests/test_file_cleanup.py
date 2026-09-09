"""delete_files_for_documents runs after the rows are already gone, so it must
never raise — a missing file cannot be allowed to turn a successful delete into
a failed request."""

import os
import tempfile

import pytest

from manabi_server.config import get_settings
from manabi_server.storage import files


@pytest.fixture
def storage(monkeypatch):
    with tempfile.TemporaryDirectory() as root:
        monkeypatch.setenv("FILE_STORAGE_ROOT", root)
        get_settings.cache_clear()
        yield root
        get_settings.cache_clear()


def _touch(rel: str) -> None:
    p = files.resolve(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")


def test_it_removes_every_directory_a_document_owns(storage):
    _touch("originals/ab/doc7.pdf")
    _touch("renders/7/p1.png")
    _touch("thumbs/7/p1.jpg")
    _touch("assets/7/img.png")
    _touch("normalized/7.pdf")

    assert files.delete_files_for_documents([(7, "originals/ab/doc7.pdf")]) == 1

    for rel in ("originals/ab/doc7.pdf", "renders/7", "thumbs/7", "assets/7", "normalized/7.pdf"):
        assert not files.resolve(rel).exists(), rel


def test_a_shared_parse_cache_entry_is_left_alone(storage):
    # parse-cache is keyed by content hash and shared between identical
    # uploads; evicting it here would cost another document its cache.
    _touch("parse-cache/v3-deadbeef.json")
    _touch("originals/ab/doc7.pdf")
    files.delete_files_for_documents([(7, "originals/ab/doc7.pdf")])
    assert files.resolve("parse-cache/v3-deadbeef.json").exists()


def test_missing_files_are_not_an_error(storage):
    assert files.delete_files_for_documents([(99, "originals/zz/gone.pdf")]) == 1


def test_one_bad_row_does_not_stop_the_others(storage):
    _touch("renders/5/p1.png")
    _touch("renders/6/p1.png")
    # A directory where a file path is expected: unlink raises, and the loop
    # must carry on to document 6 regardless.
    os.makedirs(files.resolve("originals/dir-not-a-file"), exist_ok=True)
    files.delete_files_for_documents(
        [(5, "originals/dir-not-a-file"), (6, "originals/ab/doc6.pdf")]
    )
    assert not files.resolve("renders/6").exists()


def test_an_empty_batch_is_fine(storage):
    assert files.delete_files_for_documents([]) == 0
