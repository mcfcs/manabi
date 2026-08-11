"""Increment 12.2 backend tests: course-file render-only upload path.

The manual upload endpoint gained an optional `processing_mode` form field so a
syllabus uploaded to a course's files is stored + viewable but never extracted
or fed to AI (ai_included=False), matching the Canvas course-files behaviour."""

import pytest
from fastapi import HTTPException


class _Result:
    def scalar_one_or_none(self):
        return None  # no existing doc → dedup passes


class _FakeDB:
    def __init__(self):
        self.added = []

    async def execute(self, *a, **k):
        return _Result()

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for o in self.added:
            if getattr(o, "id", None) is None:
                o.id = 1

    async def commit(self):
        pass


class _FakeUpload:
    def __init__(self, data, filename):
        self._data = data
        self.filename = filename

    async def read(self):
        return self._data


class _Module:
    id = 5


class _User:
    id = 1


def _patch(monkeypatch):
    from manabi_server.api import documents
    from manabi_server.storage import files

    monkeypatch.setattr(files, "new_original_path", lambda ext: f"originals/x.{ext}")
    monkeypatch.setattr(files, "write_atomic", lambda rel, data: None)
    monkeypatch.setattr(documents, "_doc_out", lambda doc, job_id=None, progress=None: doc)

    async def fake_enqueue(db, user_id, doc):
        class _Job:
            id = 99

        return _Job()

    monkeypatch.setattr(documents, "_enqueue_processing", fake_enqueue)
    return documents


async def test_course_file_upload_is_render_only(monkeypatch):
    documents = _patch(monkeypatch)
    doc = await documents.upload_document(
        file=_FakeUpload(b"%PDF-1.4 minimal body", "syllabus.pdf"),
        processing_mode="render_only",
        module=_Module(),
        user=_User(),
        db=_FakeDB(),
    )
    assert doc.processing_mode == "render_only"
    assert doc.ai_included is False


async def test_regular_upload_defaults_to_full(monkeypatch):
    documents = _patch(monkeypatch)
    doc = await documents.upload_document(
        file=_FakeUpload(b"%PDF-1.4 minimal body", "lecture.pdf"),
        processing_mode="full",
        module=_Module(),
        user=_User(),
        db=_FakeDB(),
    )
    assert doc.processing_mode == "full"
    assert doc.ai_included is True


async def test_upload_rejects_bad_processing_mode(monkeypatch):
    documents = _patch(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        await documents.upload_document(
            file=_FakeUpload(b"%PDF-1.4", "x.pdf"),
            processing_mode="bogus",
            module=_Module(),
            user=_User(),
            db=_FakeDB(),
        )
    assert exc.value.status_code == 422
