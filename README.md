# Manabi 学び

Personal AI-assisted study workspace: organize university courses into modules,
upload lecture materials (PDF/PPTX), and generate **source-grounded** summaries,
flashcards, and quizzes with a privately hosted LLM.

## Architecture

- `apps/web` — Vite + React + TypeScript SPA (PWA)
- `apps/server` — FastAPI backend + CPU-queue Procrastinate worker (app server)
- `apps/ai-worker` — GPU-queue Procrastinate worker (runs on **phillmyeol**, pulls
  jobs from Postgres over Tailscale; Ollama stays on localhost)
- `packages/core-py` — shared SQLAlchemy models, schemas, validators
- `infra/` — docker compose (Postgres + pgvector), Caddy, phillmyeol setup

See `docs/` for the full architecture plan, ADRs, and runbooks.

## Running

Single-user, no login — access control is the Tailscale boundary.

```bat
start-manabi.bat            :: starts everything (Docker, DB, migrations,
                            ::   web build if needed, API + AI worker)
start-manabi.bat --rebuild  :: same, but force a fresh web build
```

Then open `http://localhost:56690` on this machine, or
`http://<machine-name>:56690` from any device on the tailnet.

First-time setup: install uv + pnpm, then `uv sync` and `pnpm install`.

## Development (hot reload)

```bash
uv run --package manabi-server uvicorn manabi_server.main:app --reload --port 56690
pnpm --filter web dev   # Vite on :5173, proxies /api to :56690
```

The AI node (phillmyeol) gets its own `.env` — see `infra/phillmyeol/`.
