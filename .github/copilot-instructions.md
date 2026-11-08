# Copilot instructions

This repository's agent guide is [AGENTS.md](../AGENTS.md) and its binding rules are
[RULES.md](../RULES.md) — follow both. Key points:

- Single-user FastAPI + Postgres/pgvector + Procrastinate backend (`apps/server`),
  GPU/LLM worker (`apps/ai-worker`), Vite/React/TS SPA (`apps/web`), shared models in
  `packages/core-py`. Timezone Asia/Manila via `manabi_server/timeutil.py`.
- Match surrounding style; comments explain *why*. Prefer deterministic validators
  with tests over prompt tweaks.
- Tests: `uv run --package manabi-server pytest apps/server/tests -q`,
  `uv run --package manabi-ai-worker pytest apps/ai-worker/tests -q`,
  `pnpm exec tsc -b --noEmit` and `pnpm exec vitest run` in `apps/web`.
- Canvas is read-only; course data never leaves the machine.
