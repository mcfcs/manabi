"""Dump the RAW questions the model returns for one module, before any filter.

Generation reports how many questions survived, never why the rest died, so a
quiz that comes back empty is opaque. This runs one real generation call and
prints each question with the verdict `_question_answer` would give it.

    uv run --package manabi-ai python apps/ai-worker/scripts/debug_quiz_raw.py 21 output
"""

import asyncio
import sys

from manabi_core.retrieval import load_context_chunks
from manabi_ai import prompts
from manabi_ai.config import get_settings
from manabi_ai.context import build_context, batch_chunks
from manabi_ai.ollama_client import generate_structured
from manabi_ai.tasks_gen import _GEN_RESPONSE_HEADROOM, _question_answer
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def main(module_id: int, qtype: str, count: int) -> None:
    engine = create_async_engine(get_settings().database_url)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as db:
        chunks = await load_context_chunks(db, [module_id])
    if not chunks:
        print("no chunks in scope")
        return
    batch = next(iter(batch_chunks(chunks)))
    ctx = build_context(batch, None)
    print(f"module {module_id}: {len(chunks)} chunks, first batch {len(batch)}\n")

    result = await generate_structured(
        prompts.QUIZ_PROMPT.replace("{count}", str(count)).replace("{types}", qtype),
        ctx.source_text,
        prompts.quiz_schema_for([qtype]),
        response_headroom=_GEN_RESPONSE_HEADROOM,
    )
    questions = result.get("questions", [])
    print(f"model returned {len(questions)} question(s)\n" + "=" * 70)
    from manabi_ai.tasks_gen import fold_code_into_prompt

    for i, q in enumerate(questions, 1):
        fold_code_into_prompt(q)
        verdict = _question_answer(q)
        has_fence = "```" in (q.get("prompt") or "")
        print(f"\n--- {i} qtype={q.get('qtype')} fence={has_fence} "
              f"accepted={verdict is not None} ---")
        print("PROMPT:")
        print(q.get("prompt"))
        print(f"correct_text: {q.get('correct_text')!r}")
        if verdict is None:
            print(">>> REJECTED by _question_answer")


if __name__ == "__main__":
    mid = int(sys.argv[1]) if len(sys.argv) > 1 else 21
    qt = sys.argv[2] if len(sys.argv) > 2 else "output"
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    asyncio.run(main(mid, qt, n))
