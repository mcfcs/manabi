from manabi_server.processing.pipeline import _fix_reading_order
from manabi_server.processing.textmerge import merge_fragments


def _el(page: int, top: float, text: str = "x") -> dict:
    return {"page_no": page, "bbox": {"t": top, "l": 10, "r": 100, "b": top - 10}, "text": text}


def test_scrambled_page_is_resorted_by_position():
    # >20% inversions → re-sort top-to-bottom (bottom-left origin: high t first)
    elements = [
        _el(1, 535, "a"), _el(1, 488, "c"), _el(1, 523, "b"),
        _el(1, 297, "f"), _el(1, 345, "e"), _el(1, 440, "d"),
    ]
    fixed = _fix_reading_order(elements)
    assert [e["text"] for e in fixed] == ["a", "b", "c", "d", "e", "f"]


def test_ordered_page_is_untouched():
    # correctly ordered (monotonic descending tops) — no re-sort even though
    # a position sort would give the same result; key is minimal inversions
    elements = [
        _el(1, 500, "a"), _el(1, 450, "b"), _el(1, 400, "c"),
        _el(1, 350, "d"), _el(1, 300, "e"),
    ]
    assert [e["text"] for e in _fix_reading_order(elements)] == ["a", "b", "c", "d", "e"]


def test_multicolumn_like_page_with_few_inversions_untouched():
    # realistic two-column page: one upward jump at the column break out of
    # many pairs → far below threshold → column order preserved
    col1 = [_el(1, 500 - i * 30, f"a{i}") for i in range(8)]
    col2 = [_el(1, 500 - i * 30, f"b{i}") for i in range(8)]
    elements = col1 + col2  # 1 inversion / 15 pairs ≈ 6.7%
    assert [e["text"] for e in _fix_reading_order(elements)] == [
        e["text"] for e in col1 + col2
    ]


def test_merge_fragments_rejoins_sentences_and_dehyphenates():
    fragments = [
        "The discussion of data abstraction and object-",
        "oriented programming equates support with the ability.",
        "This is a new sentence starting fresh.",
    ]
    merged = merge_fragments(fragments)
    assert merged[0] == (
        "The discussion of data abstraction and object"
        "oriented programming equates support with the ability."
    )
    assert merged[1] == "This is a new sentence starting fresh."


def test_merge_fragments_joins_lowercase_continuation():
    merged = merge_fragments(["§1.3 presents the basic facilities pro", "vided by C++."])
    # no hyphen → space join (lowercase continuation)
    assert merged == ["§1.3 presents the basic facilities pro vided by C++."]


def test_merge_fragments_respects_terminal_punctuation():
    merged = merge_fragments(["First sentence.", "second thing continues?"])
    # previous ended with '.' → no join even though next starts lowercase
    assert len(merged) == 2
