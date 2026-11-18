"""Download a reading's narration as one MP3 (Steven's per-paragraph clips
joined with the Listen bar's pauses). Runs real ffmpeg on tiny clips in the
stored format (mono 96 kbps MP3, 32 kHz) because the point is the file a phone
plays: its length header must cover the whole reading, not the first clip."""

import json
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException
from manabi_server.services import narration_export as nx

try:
    FFMPEG = nx.tool("ffmpeg")
    FFPROBE = nx.tool("ffprobe")
except RuntimeError:  # pragma: no cover - CI without ffmpeg
    FFMPEG = FFPROBE = None

needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")


def _clip(path: Path, seconds: float, freq: int = 440) -> Path:
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i",
         f"sine=frequency={freq}:sample_rate=32000:duration={seconds}",
         "-ac", "1", "-b:a", "96k", str(path)],
        check=True,
    )
    return path


def _probe(path: Path) -> dict:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        check=True, capture_output=True,
    )
    return json.loads(out.stdout)


# ── pure rules ────────────────────────────────────────────────────────────


def test_pauses_match_the_listen_bar():
    # NarrationBar: 250 ms between paragraphs, 500 ms before a heading/title
    plan = nx.concat_plan(["title", "paragraph", "heading", "paragraph"])
    assert plan == [
        ("segment", 0),
        ("silence", 250),
        ("segment", 1),
        ("silence", 500),
        ("segment", 2),
        ("silence", 250),
        ("segment", 3),
    ]
    assert nx.concat_plan(["paragraph"]) == [("segment", 0)]


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("Sen - Development as Freedom ch6.pdf", "Sen - Development as Freedom ch6.mp3"),
        ('Kerkvliet: "Everyday Politics" / Ch. 1?.pdf', "Kerkvliet Everyday Politics Ch. 1.mp3"),
        ("Pagsusuri ng Akdâ.pptx", "Pagsusuri ng Akdâ.mp3"),  # non-ASCII kept
        ("...pdf", "reading.mp3"),
    ],
)
def test_download_name_is_the_reading_and_safe_on_every_os(filename, expected):
    assert nx.download_filename(filename) == expected


def test_the_cache_key_follows_the_audio():
    a = nx.export_key([(1, 1000), (2, 2000)])
    assert a == nx.export_key([(1, 1000), (2, 2000)])
    assert a != nx.export_key([(1, 1000), (2, 2001)])  # a paragraph re-recorded
    assert a != nx.export_key([(1, 1000), (3, 2000)])  # re-scripted (new rows)


# ── the file itself ───────────────────────────────────────────────────────


@needs_ffmpeg
def test_one_file_with_the_whole_length_and_tags(tmp_path):
    clips = [_clip(tmp_path / "a.mp3", 1.0), _clip(tmp_path / "b.mp3", 1.0, 660)]
    out = tmp_path / "out.mp3"
    nx.build_mp3(clips, ["paragraph", "heading"], out, title="Sen ch6", album="SocSc 14")
    info = _probe(out)
    stream = info["streams"][0]
    assert stream["codec_name"] == "mp3" and stream["sample_rate"] == "32000"
    assert stream["channels"] == 1
    # 1 s + 0.5 s pause before the heading + 1 s. A per-clip length header
    # would make phones show ~1 s here.
    assert float(info["format"]["duration"]) == pytest.approx(2.5, abs=0.15)
    tags = {k.lower(): v for k, v in info["format"].get("tags", {}).items()}
    assert tags["title"] == "Sen ch6" and tags["album"] == "SocSc 14"
    assert tags["artist"] == "Steven"


class FakeDB:
    """Answers the segment index query, then one audio fetch per segment."""

    def __init__(self, rows, audio):
        self.rows = rows  # (id, kind, audio_len)
        self.audio = audio  # id -> bytes

    async def execute(self, *a, **k):
        rows = self.rows

        class _R:
            def all(self):
                return rows

        return _R()

    async def scalar(self, stmt):
        seg_id = stmt.compile().params["id_1"]
        return self.audio[seg_id]


@pytest.fixture
def storage(tmp_path, monkeypatch):
    from manabi_server.config import get_settings

    monkeypatch.setattr(get_settings(), "file_storage_root", str(tmp_path / "storage"))
    return tmp_path / "storage"


@needs_ffmpeg
async def test_built_once_then_served_from_the_cache(tmp_path, storage, monkeypatch):
    a = _clip(tmp_path / "a.mp3", 0.5).read_bytes()
    b = _clip(tmp_path / "b.mp3", 0.5, 660).read_bytes()
    db = FakeDB([(11, "title", len(a)), (12, "paragraph", len(b))], {11: a, 12: b})
    builds = []
    real_build = nx.build_mp3
    monkeypatch.setattr(
        nx, "build_mp3", lambda *args, **kw: (builds.append(1), real_build(*args, **kw))
    )

    first = await nx.ensure_mp3(db, narration_id=5, document_id=84, title="t", album=None)
    again = await nx.ensure_mp3(db, narration_id=5, document_id=84, title="t", album=None)
    assert first == again and first.exists() and len(builds) == 1
    assert float(_probe(first)["format"]["duration"]) == pytest.approx(1.25, abs=0.15)

    # Re-recorded paragraph → new key → rebuilt, and the stale file is removed
    db.rows = [(11, "title", len(a)), (13, "paragraph", len(b))]
    db.audio[13] = b
    newer = await nx.ensure_mp3(db, narration_id=5, document_id=84, title="t", album=None)
    assert newer != first and newer.exists() and not first.exists()
    assert sorted(p.name for p in (storage / "narration-downloads").iterdir()) == [newer.name]


async def test_a_reading_still_being_recorded_is_refused(storage):
    db = FakeDB([(11, "title", 900), (12, "paragraph", None), (13, "paragraph", None)], {})
    with pytest.raises(nx.NarrationNotReady) as exc:
        await nx.ensure_mp3(db, narration_id=5, document_id=84, title="t", album=None)
    assert exc.value.missing == 2


async def test_deleting_the_narration_drops_its_download(storage):
    from manabi_core.models import Document
    from manabi_server.api import narration as api

    folder = storage / "narration-downloads"
    folder.mkdir(parents=True)
    (folder / "84-0123456789ab.mp3").write_bytes(b"x")
    (folder / "841-0123456789ab.mp3").write_bytes(b"x")

    class DB:
        async def execute(self, *a, **k):
            return None

        async def commit(self):
            pass

    await api.delete_narration(doc=Document(id=84, filename="x.pdf"), db=DB())
    assert sorted(p.name for p in folder.iterdir()) == ["841-0123456789ab.mp3"]


# ── the endpoint ──────────────────────────────────────────────────────────


async def test_endpoint_sends_an_attachment_named_after_the_reading(tmp_path, monkeypatch):
    from manabi_core.models import Document, Narration
    from manabi_server.api import narration as api

    mp3 = tmp_path / "84-abc.mp3"
    mp3.write_bytes(b"ID3")

    async def fake_ensure(db, **kw):
        assert kw["narration_id"] == 5 and kw["title"] == "Sen ch6"
        return mp3

    async def fake_lookup(db, doc):
        return Narration(id=5, document_id=84, status="ready"), "SocSc 14"

    monkeypatch.setattr(api, "ensure_mp3", fake_ensure)
    monkeypatch.setattr(api, "_narration_and_course", fake_lookup)
    doc = Document(id=84, filename="Sen ch6.pdf")
    resp = await api.download_narration(doc=doc, db=None)
    assert resp.media_type == "audio/mpeg"
    # Both forms (RFC 6266): plain filename for older Android download
    # managers, filename* for the exact UTF-8 name on iOS / modern browsers.
    assert resp.headers["content-disposition"] == (
        "attachment; filename=\"Sen ch6.mp3\"; filename*=UTF-8''Sen%20ch6.mp3"
    )


def test_disposition_keeps_an_ascii_fallback_for_non_ascii_names():
    from manabi_server.api import narration as api

    assert api.attachment_disposition("Pagsusuri ng Akdâ.mp3") == (
        "attachment; filename=\"Pagsusuri ng Akda.mp3\"; "
        "filename*=UTF-8''Pagsusuri%20ng%20Akd%C3%A2.mp3"
    )


async def test_endpoint_explains_an_unfinished_recording(monkeypatch):
    from manabi_core.models import Document, Narration
    from manabi_server.api import narration as api

    async def not_ready(db, **kw):
        raise nx.NarrationNotReady(3)

    async def fake_lookup(db, doc):
        return Narration(id=5, document_id=84, status="synthesizing"), None

    monkeypatch.setattr(api, "ensure_mp3", not_ready)
    monkeypatch.setattr(api, "_narration_and_course", fake_lookup)
    with pytest.raises(HTTPException) as exc:
        await api.download_narration(doc=Document(id=84, filename="x.pdf"), db=None)
    assert exc.value.status_code == 409
    assert "3 paragraphs" in exc.value.detail

    async def none_yet(db, doc):
        return None, None

    monkeypatch.setattr(api, "_narration_and_course", none_yet)
    with pytest.raises(HTTPException) as exc:
        await api.download_narration(doc=Document(id=84, filename="x.pdf"), db=None)
    assert exc.value.status_code == 404
