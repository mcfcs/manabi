"""Benchmark chat + generation on each candidate model, so you can decide whether
to consolidate to ONE model (then flip CHAT_MODEL / GENERATION_MODEL in .env).

Hits the configured Ollama (OLLAMA_URL = phillmyeol) directly, one model at a
time — it measures cold + warm latency, throughput, valid-JSON, and a grounding
sanity check for both a chat answer and a summary generation.

Run (from repo root):  uv run --package manabi-ai python apps/ai-worker/scripts/bench_models.py
Optional: pass model names as args to override the default pair.
"""

import asyncio
import sys
import time

from manabi_ai import prompts
from manabi_ai.ollama_client import generate_structured

MODELS = sys.argv[1:] or ["gpt-oss:20b", "qwen3.5:27b"]

SOURCE = """SOURCE MATERIAL (the only factual authority):

[1] (Intro to Cells, p.3) The mitochondrion is the powerhouse of the cell; it
produces ATP through oxidative phosphorylation across the inner membrane.
[2] (Intro to Cells, p.4) Chloroplasts perform photosynthesis in plant cells,
converting light energy into chemical energy stored as glucose.
[3] (Intro to Cells, p.5) The nucleus stores the cell's DNA and controls gene
expression; it is bounded by the nuclear envelope."""

CHAT_USER = (
    SOURCE
    + "\n\nCONVERSATION:\nSTUDENT: What does the mitochondrion do, and how does"
    " it relate to the chloroplast? Cite your sources."
)


async def _timed(coro):
    t = time.monotonic()
    try:
        return time.monotonic() - t, await coro, None
    except Exception as e:  # noqa: BLE001 — a bench must never crash on a bad model
        return time.monotonic() - t, None, str(e)[:120]


async def bench(model: str) -> dict:
    row: dict = {"model": model}
    # Chat — cold then warm (second call: model already resident).
    cold, out, err = await _timed(
        generate_structured(prompts.CHAT_PROMPT, CHAT_USER, prompts.CHAT_SCHEMA, model=model)
    )
    warm, out2, _ = await _timed(
        generate_structured(prompts.CHAT_PROMPT, CHAT_USER, prompts.CHAT_SCHEMA, model=model)
    )
    ans = (out2 or out or {}).get("answer", "") if not err else ""
    row["chat_cold_s"] = round(cold, 1)
    row["chat_warm_s"] = round(warm, 1)
    row["chat_grounded"] = bool((out2 or out or {}).get("source_ids")) if not err else False
    row["chat_chars_per_s"] = round(len(ans) / warm, 1) if warm and ans else 0
    row["chat_err"] = err
    # Summary generation.
    sdur, sout, serr = await _timed(
        generate_structured(prompts.SUMMARY_PROMPT, SOURCE, prompts.SUMMARY_SCHEMA, model=model)
    )
    row["summary_s"] = round(sdur, 1)
    row["summary_sections"] = len((sout or {}).get("sections", [])) if not serr else 0
    row["summary_err"] = serr
    return row


async def main() -> None:
    print(f"Benchmarking {MODELS} against the configured Ollama node…\n")
    rows = []
    for m in MODELS:
        print(f"→ {m} …", flush=True)
        rows.append(await bench(m))
    cols = [
        "model", "chat_cold_s", "chat_warm_s", "chat_chars_per_s",
        "chat_grounded", "summary_s", "summary_sections",
    ]
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    print("\n" + "  ".join(c.ljust(widths[c]) for c in cols))
    for r in rows:
        print("  ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols))
    for r in rows:
        if r.get("chat_err") or r.get("summary_err"):
            print(
                f"\n! {r['model']}: chat_err={r.get('chat_err')} "
                f"summary_err={r.get('summary_err')}"
            )


if __name__ == "__main__":
    asyncio.run(main())
