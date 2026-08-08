import sys
from pathlib import Path

from manabi_core.retrieval import ScopedChunk, source_fingerprint

sys.path.insert(0, str(Path(__file__).parents[2] / "ai-worker" / "src"))
from manabi_ai.validators import dedup_questions, resolve_items  # noqa: E402


def _chunk(id: int, module_id: int = 1) -> ScopedChunk:
    return ScopedChunk(
        id=id,
        module_id=module_id,
        document_id=1,
        document_title="lecture.pdf",
        page_start=1,
        page_end=2,
        heading_path="1. Intro",
        text="content",
        token_count=10,
        content_hash=f"hash{id}",
    )


def test_resolve_drops_unresolvable_ids():
    index_map = {1: _chunk(101), 2: _chunk(102)}
    items = [
        {"text": "supported", "source_ids": [1]},
        {"text": "invented citation", "source_ids": [99]},
        {"text": "empty", "source_ids": []},
    ]
    kept, dropped = resolve_items(items, index_map, {1})
    assert len(kept) == 1 and dropped == 2
    assert kept[0].chunks[0].id == 101


def test_resolve_rejects_out_of_scope_module():
    """The live isolation audit: a chunk from another module is refused even
    if it somehow appeared in the index map."""
    index_map = {1: _chunk(101, module_id=1), 2: _chunk(202, module_id=2)}
    items = [{"text": "leaky", "source_ids": [2]}]
    kept, dropped = resolve_items(items, index_map, {1})
    assert kept == [] and dropped == 1


def test_dedup_questions_drops_near_duplicates():
    index_map = {1: _chunk(101)}
    items, _ = resolve_items(
        [
            {"prompt": "What is a cache hit?", "source_ids": [1]},
            {"prompt": "What is a cache hit ?", "source_ids": [1]},
            {"prompt": "Explain set-associative mapping.", "source_ids": [1]},
        ],
        index_map,
        {1},
    )
    deduped = dedup_questions(items)
    assert len(deduped) == 2


def test_source_fingerprint_orders_and_detects_change():
    a = [_chunk(1), _chunk(2)]
    b = [_chunk(2), _chunk(1)]  # same set, different order
    assert source_fingerprint(a) == source_fingerprint(b)
    changed = [_chunk(1), _chunk(3)]
    assert source_fingerprint(a) != source_fingerprint(changed)
