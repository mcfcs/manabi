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

## Development

```bash
# 1. Database
docker compose -f infra/compose.yaml up -d

# 2. Python (uv workspace)
uv sync
uv run --package manabi-server alembic -c apps/server/alembic.ini upgrade head
uv run --package manabi-server uvicorn manabi_server.main:app --reload

# 3. Web
pnpm install
pnpm --filter web dev
```

Copy `.env.example` to `.env` and adjust. The AI node gets its own `.env`
(see `infra/phillmyeol/`).
