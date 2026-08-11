"""Increment 12 unit tests: spread detection/split, column-aware reading order,
margin stripping, parse-source indirection, cancel plumbing, grounding prompt."""

import sys
from pathlib import Path

import pymupdf
import pytest
from manabi_server.processing import layout, pipeline
from manabi_server.storage import files

# ── Two-page-spread detection + splitting ─────────────────────────────────


def _spread_pdf(tmp: Path) -> pymupdf.Document:
    """A synthetic landscape spread: two text blocks with a clear centre gutter."""
    doc = pymupdf.open()
    for _ in range(6):
        page = doc.new_page(width=792, height=612)
        page.insert_textbox(pymupdf.Rect(40, 60, 340, 560), "Left page. " * 80, fontsize=11)
        page.insert_textbox(pymupdf.Rect(452, 60, 752, 560), "Right page. " * 80, fontsize=11)
    return doc


def _single_pdf() -> pymupdf.Document:
    doc = pymupdf.open()
    for _ in range(4):
        page = doc.new_page(width=612, height=792)  # portrait
        page.insert_textbox(pymupdf.Rect(72, 72, 540, 720), "Body text. " * 120, fontsize=11)
    return doc


def test_detect_spread_flags_landscape_two_column(tmp_path):
    doc = _spread_pdf(tmp_path)
    is_spread, gutters = layout.detect_spread(doc)
    assert is_spread is True
    assert sum(1 for g in gutters if g is not None) >= 3
    # gutter sits near the centre
    for g in gutters:
        if g is not None:
            assert 300 < g < 490


def test_detect_single_for_portrait_body():
    doc = _single_pdf()
    is_spread, gutters = layout.detect_spread(doc)
    assert is_spread is False


def test_split_doubles_page_count_and_halves_width(tmp_path):
    doc = _spread_pdf(tmp_path)
    _, gutters = layout.detect_spread(doc)
    out = layout.split_spread_pdf(doc, gutters)
    assert out.page_count == doc.page_count * 2
    # each half is portrait-ish (narrower than the source)
    assert out[0].rect.width < doc[0].rect.width


def test_has_native_text_gate():
    doc = _single_pdf()
    assert layout.has_native_text(doc) is True
    blank = pymupdf.open()
    blank.new_page(width=792, height=612)
    assert layout.has_native_text(blank) is False


# ── Column-aware reading order ────────────────────────────────────────────


def _el(text, t, left, r):
    return {
        "type": "paragraph",
        "text": text,
        "page_no": 1,
        "bbox": {"t": t, "l": left, "r": r, "b": t - 10},
    }


def test_two_column_order_reads_left_then_right():
    # left column x≈80, right column x≈360; interleaved input order.
    # Column ordering for spreads is opt-in via aggressive_columns.
    els = [
        _el("R-top", 560, 340, 400),
        _el("L-top", 560, 70, 200),
        _el("L-bot", 120, 70, 200),
        _el("R-bot", 120, 340, 400),
    ]
    out = [e["text"] for e in pipeline._fix_reading_order(els, aggressive_columns=True)]
    assert out.index("L-top") < out.index("L-bot") < out.index("R-top")
    assert out.index("R-top") < out.index("R-bot")


def test_single_column_untouched_when_ordered():
    els = [_el(f"p{i}", 600 - i * 50, 72, 500) for i in range(5)]
    out = [e["text"] for e in pipeline._fix_reading_order(els)]
    assert out == ["p0", "p1", "p2", "p3", "p4"]


def test_margin_repeats_stripped():
    els = []
    for pg in range(1, 8):
        els.append(
            {"type": "heading", "text": "RUNNING HEAD", "page_no": pg,
             "bbox": {"t": 600, "l": 70, "r": 200, "b": 590}}
        )
        els.append(
            {"type": "paragraph", "text": f"Body A of page {pg} " * 5, "page_no": pg,
             "bbox": {"t": 400, "l": 70, "r": 400, "b": 390}}
        )
        els.append(
            {"type": "paragraph", "text": f"Body B of page {pg} " * 5, "page_no": pg,
             "bbox": {"t": 250, "l": 70, "r": 400, "b": 240}}
        )
    kept = pipeline._strip_margin_repeats(els)
    assert not any(e["text"] == "RUNNING HEAD" for e in kept)
    assert any("Body A of page" in e["text"] for e in kept)


# ── parse_source_path indirection ─────────────────────────────────────────


class _Doc:
    def __init__(self, id, kind, storage_path):
        self.id = id
        self.kind = kind
        self.storage_path = storage_path


def test_parse_source_path_prefers_normalized(tmp_path, monkeypatch):
    from manabi_core.models import DocumentKind

    monkeypatch.setattr(files, "storage_root", lambda: tmp_path)
    doc = _Doc(42, DocumentKind.pdf, "originals/x.pdf")
    # no normalized file → original
    assert pipeline.parse_source_path(doc) == files.resolve("originals/x.pdf")
    # create normalized (keyed by document id) → it wins
    norm = files.resolve(files.normalized_path(doc.id))
    norm.parent.mkdir(parents=True, exist_ok=True)
    norm.write_bytes(b"%PDF-1.4")
    assert pipeline.parse_source_path(doc) == norm


# ── Cancel plumbing + grounding prompt (worker package on sys.path) ───────

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "ai-worker" / "src"))


def test_grounding_prompt_selection():
    from manabi_ai import prompts

    assert prompts.chat_prompt_for(False, True) == prompts.CHAT_PROMPT
    assert prompts.chat_prompt_for(True, True) == prompts.TEACHER_CHAT_PROMPT
    assert prompts.chat_prompt_for(False, False) == prompts.REASONING_CHAT_PROMPT
    assert prompts.chat_prompt_for(True, False) == prompts.TEACHER_REASONING_PROMPT


@pytest.mark.asyncio
async def test_abort_raises_jobaborted_and_marks_cancelled():
    from manabi_ai.tasks_gen import _abort_if_requested
    from procrastinate.exceptions import JobAborted

    class _Ctx:
        def should_abort(self):
            return True

    class _Job:
        status = None
        progress_note = None
        preview = "x"
        finished_at = None

    class _Db:
        async def commit(self):
            return None

    job = _Job()
    with pytest.raises(JobAborted):
        await _abort_if_requested(_Db(), job, _Ctx())
    assert str(job.status) == "JobStatus.cancelled" or job.status.value == "cancelled"


@pytest.mark.asyncio
async def test_abort_noop_when_not_requested():
    from manabi_ai.tasks_gen import _abort_if_requested

    class _Ctx:
        def should_abort(self):
            return False

    class _Db:
        async def commit(self):
            raise AssertionError("should not commit when not aborting")

    await _abort_if_requested(_Db(), object(), _Ctx())  # no raise, no commit
