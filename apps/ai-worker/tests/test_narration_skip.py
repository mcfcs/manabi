"""A paragraph the voice cannot say is left out; it no longer fails the whole
document (a line of Python failed all 70 paragraphs of an NLP deck)."""

import asyncio
from types import SimpleNamespace

from manabi_ai import tasks_tts
from manabi_ai.tts_client import TTSQualityError


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self.value))

    def all(self):
        return list(self.value)


class _Session:
    def __init__(self, job, narration, segments):
        self.results = [job, narration, segments, [(s.id,) for s in segments]]
        self.deleted = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, _stmt):
        return _Result(self.results.pop(0))

    async def delete(self, obj):
        self.deleted.append(obj)

    async def commit(self):
        pass

    async def rollback(self):
        pass


def _run(monkeypatch, texts, unsayable):
    job = SimpleNamespace(status=None, progress_note=None, result=None, error=None)
    narration = SimpleNamespace(status=None, error=None)
    segments = [
        SimpleNamespace(id=i, ord=i, spoken_text=t, audio=None) for i, t in enumerate(texts)
    ]
    session = _Session(job, narration, segments)
    monkeypatch.setattr(tasks_tts, "session_factory", lambda: lambda: session)
    monkeypatch.setattr(
        tasks_tts,
        "get_settings",
        lambda: SimpleNamespace(tts_enabled=True, tts_verify_speech=True, tts_voice="steven"),
    )

    async def fake_synthesize(text, verify=False):
        if text in unsayable:
            raise TTSQualityError("Voice transcript contains too little of the requested sentence")
        return b"mp3", 1000

    monkeypatch.setattr(tasks_tts, "synthesize", fake_synthesize)
    asyncio.run(tasks_tts.narrate_document.func(None, job_id=1, narration_id=1))
    return job, narration, segments, session


def test_one_unsayable_paragraph_is_left_out(monkeypatch):
    code = "processed_text = re.sub(r'[^\\x00-\\x7f]', r'', raw_text)."
    texts = ["Text cleaning.", code, "Lowercasing words is next."]
    job, narration, segments, session = _run(monkeypatch, texts, {code})
    assert narration.status == "ready"
    assert job.result == {"skipped_ords": [1]}
    assert [s.ord for s in session.deleted] == [1]
    assert segments[0].audio == b"mp3" and segments[2].audio == b"mp3"


def test_many_failures_still_fail_the_job(monkeypatch):
    texts = [f"Paragraph number {i} reads fine." for i in range(8)]
    job, narration, _segments, _session = _run(monkeypatch, texts, set(texts))
    assert narration.status == "failed"
    assert "TTSQualityError" in (job.error or "")
