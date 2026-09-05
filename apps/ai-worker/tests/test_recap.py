"""Rolling-recap decisions for long chat threads."""

from manabi_ai.recap import (
    KEEP_RECENT,
    RECAP_EVERY,
    RECAP_THRESHOLD,
    recap_block,
    should_refresh,
    turns_to_fold,
)


def test_short_threads_never_recap():
    ids = list(range(1, RECAP_THRESHOLD))  # one short of the threshold
    assert not should_refresh(ids, None)
    assert turns_to_fold(ids, None) == (ids[:-KEEP_RECENT], ids[-KEEP_RECENT - 1])


def test_first_recap_at_threshold_covers_everything_but_the_window():
    ids = list(range(1, RECAP_THRESHOLD + 1))  # 1..10
    assert should_refresh(ids, None)
    fold, cutoff = turns_to_fold(ids, None)
    assert fold == [1, 2, 3, 4]
    assert cutoff == 4


def test_refresh_only_after_enough_new_turns_beyond_the_window():
    ids = list(range(1, 11))
    upto = 4
    # 5 more messages: 11..15 -> beyond-window new turns = 5..9 -> 5 < 6
    assert not should_refresh(ids + list(range(11, 16)), upto)
    # 6 more: 11..16 -> beyond-window new turns = 5..10 -> refresh
    longer = ids + list(range(11, 17))
    assert should_refresh(longer, upto)
    fold, cutoff = turns_to_fold(longer, upto)
    assert fold == [5, 6, 7, 8, 9, 10]
    assert cutoff == 10
    assert len(fold) == RECAP_EVERY


def test_recap_block_is_empty_without_a_summary():
    assert recap_block(None) == ""
    assert recap_block("   ") == ""
    block = recap_block("The student is comparing paradigms.")
    assert block.startswith("\n\nEARLIER IN THIS CONVERSATION")
    assert block.endswith("The student is comparing paradigms.")


def test_recap_schema_requires_only_summary():
    from manabi_ai import prompts

    assert prompts.THREAD_RECAP_SCHEMA["required"] == ["summary"]
    assert set(prompts.THREAD_RECAP_SCHEMA["properties"]) == {"summary"}
    assert "PREVIOUS RECAP" in prompts.THREAD_RECAP_PROMPT
