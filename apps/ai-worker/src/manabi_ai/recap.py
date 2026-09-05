"""When and what to fold into a thread's rolling recap (pure decisions).

The chat prompt shows only the last WINDOW messages verbatim. Once a thread
outgrows that, everything older is condensed into ``chat_threads.summary`` by
the chat model, refreshed every RECAP_EVERY new messages, and prepended to the
prompt as "EARLIER IN THIS CONVERSATION". The model call itself lives in
tasks_gen.chat_answer; this module only decides.
"""

from __future__ import annotations

from collections.abc import Sequence

RECAP_THRESHOLD = 10  # a thread this long gets its first recap
RECAP_EVERY = 6  # ...and a refresh every this many messages after that
KEEP_RECENT = 6  # turns that stay verbatim (never summarized)
WINDOW = 7  # turns the prompt shows verbatim (one overlaps the recap)


def should_refresh(message_ids: Sequence[int], upto_id: int | None) -> bool:
    """True when the recap is missing for a long thread, or stale by
    RECAP_EVERY or more messages beyond the verbatim window."""
    total = len(message_ids)
    if total < RECAP_THRESHOLD:
        return False
    if upto_id is None:
        return True
    beyond_window = [i for i in message_ids[:-KEEP_RECENT] if i > upto_id]
    return len(beyond_window) >= RECAP_EVERY


def turns_to_fold(message_ids: Sequence[int], upto_id: int | None) -> tuple[list[int], int | None]:
    """Message ids not yet covered by the recap and outside the verbatim
    window, plus the new cutoff id (None when there is nothing to fold)."""
    ids = list(message_ids)
    older = ids[:-KEEP_RECENT] if len(ids) > KEEP_RECENT else []
    fresh = [i for i in older if upto_id is None or i > upto_id]
    return fresh, (fresh[-1] if fresh else None)


def recap_block(summary: str | None) -> str:
    """The prompt fragment inserted before CONVERSATION when a recap exists."""
    text = (summary or "").strip()
    if not text:
        return ""
    return "\n\nEARLIER IN THIS CONVERSATION (recap of turns not shown below):\n" + text
