# AGENTS.md — working on Manabi

Guide for AI coding agents (Claude Code, Codex, Cursor, Copilot, Gemini, …).
**Read [RULES.md](RULES.md) before changing anything** — it holds the non-negotiable
rules (commits, deploys, testing, privacy). Then read `handoff.md` (local, gitignored)
for the current state: what shipped last, what is open, what the user decided.

## What Manabi is

A single-user, self-hosted study platform for one university student (Gio), reached
over Tailscale. Course materials (PDF/PPTX/TXT, Canvas imports) are parsed, chunked
and embedded; local LLMs generate cited summaries, flashcards, quizzes, study plans and
lectures; "Steven" (a TTS teacher persona) narrates readings and answers chat. Also:
schedule, calendar (Google ICS), tasks (Canvas), grades, web push, PWA.

No auth (single user; the tailnet is the boundary). Timezone is Asia/Manila — all
"now/today" comes from `manabi_server/timeutil.py`.

## Repository map

```
apps/server/        FastAPI API + CPU worker (Procrastinate "cpu" queue) + scheduler
  src/manabi_server/
    api/            HTTP routes (artifacts.py = summaries/cards/quizzes/lectures,
                    chat.py, assistant.py, documents.py, narration.py, calendar…)
    processing/     extraction: pipeline.py (Docling parse → elements → chunks),
                    layout.py (spreads, text-layer readability), text_health.py
                    (OCR clean-up), text_html.py (viewer text), narration_script.py
    services/       scheduler.py (5-min ticks: push, gcal, canvas, letter),
                    narration.py, push.py, context.py …
    jobs/queue.py   task names + defer helpers
  alembic/versions/ migrations (0001 … 0048)
  tests/            pytest (also tests ai-worker modules via sys.path)
apps/ai-worker/     GPU worker (Procrastinate "gpu" queue) — LLM + TTS tasks
  src/manabi_ai/
    tasks_gen.py    generate_summary / flashcards / quiz / teach_module / briefing
    prompts.py      every prompt + JSON schema; PROMPT_VERSION
    quizplan.py     quiz planning, type mix, selection, audit helpers
    validators.py   citation resolution, dedup, deterministic quality guards
    tts_client.py   GPT-SoVITS client
  tests/            pytest
apps/web/           Vite + React + TS SPA (TanStack Router/Query), served by FastAPI
  src/features/<area>/   one folder per feature (ai, calendar, courses, …)
  scripts/mobile-audit.mjs  Playwright layout audit at phone/tablet widths
packages/core-py/   shared SQLAlchemy models (models.py) + retrieval.py (THE scoped
                    chunk access: hybrid pgvector + FTS, module scope required)
infra/compose.yaml  Postgres 16 + pgvector (container manabi-postgres, host port 56661)
docs/               runbooks, testing, generation checks, voice, grades, responsive
start-manabi.bat    the ONLY way to (re)start services — see RULES.md
```

## Runtime topology

| Piece | Where | Notes |
|---|---|---|
| Postgres 16 + pgvector | Docker `manabi-postgres`, port **56661** | `docker exec -i manabi-postgres psql -U manabi -d manabi` |
| API (uvicorn) | this PC, port **56690** | serves the built SPA; `tailscale serve` gives HTTPS |
| CPU worker | this PC | extraction, chunking, embedding, scoring |
| GPU worker | this PC | LLM calls go to Ollama on **phillmyeol** (generation model in `.env`); TTS on this PC (GPT-SoVITS, port 9880) |
| Scheduler | inside the API process | `services/scheduler.py`, 5-minute ticks |

Jobs: a `jobs` row (UI-facing status/progress) + a Procrastinate job. The GPU queue
runs ONE job at a time — long narrations delay generation. Active jobs:
`GET /api/jobs/active` (raw body `[]` = idle).

## Commands

Python (uv workspace) — run from the repo root:

```powershell
uv run --package manabi-server pytest apps/server/tests -q
uv run --package manabi-ai-worker pytest apps/ai-worker/tests -q
uv run ruff check <changed files>          # lint only what you touched (see baseline)
uv run --package manabi-server alembic -c apps/server/alembic.ini upgrade head  # the bat does this
```

Web (from `apps/web`):

```powershell
pnpm exec tsc -b --noEmit     # typecheck
pnpm exec vitest run          # unit tests
pnpm build                    # tsc + vite build (the bat rebuilds on deploy)
npx playwright cli open http://127.0.0.1:56690/    # drive the real app (see docs/testing.md)
```

Deploy (after `GET /api/jobs/active` returns `[]`):

```powershell
cmd /c "c:\Users\Gio\Documents\GitHub\manabi\start-manabi.bat --quiet"
```

## Conventions

- **Match the surrounding code**: comment density, naming, idioms. Comments explain
  *why* (often citing the real case that motivated them), not what.
- **Deterministic guards over more prompting.** When generated output is wrong, first
  look for a code-checkable cause (extraction, selection, dedup, validation) and add a
  guard + test in `validators.py` / `quizplan.py`; prompts change only with evidence.
  Bump `prompts.PROMPT_VERSION` (and its test) when a prompt changes.
- **Pure functions for logic, thin handlers** — scheduler predicates, selection,
  validators are pure and unit-tested; I/O stays at the edges.
- **Migrations**: new numbered Alembic file in `apps/server/alembic/versions/`;
  models in `packages/core-py/src/manabi_core/models.py`. Workers must restart after
  model changes (the bat does it).
- **Re-extracting a document re-creates its chunks** and orphans artifact citations
  (summaries/quizzes/decks cite chunk ids). Fix extraction BEFORE generating; after
  generation, prefer in-place fixes.
- **Frontend**: one feature folder per area; React Query caches with
  `staleTime: Infinity` must be updated on mutation (`setQueryData`). PWA: the UI may
  run a cached bundle — a user "not seeing" a fix may just need the update applied.
- **Copy and UI text**: plain, specific, Gio's voice; no marketing tone.

## Gotchas that have bitten before

- Windows: psycopg async needs `WindowsSelectorEventLoopPolicy`; `TORCHDYNAMO_DISABLE=1`
  for Docling; colons are illegal in filenames (parse-cache keys use `-`).
- PowerShell 5.1: piping UTF-8 into native commands mangles non-ASCII — `docker cp` a
  SQL file and run `psql -f`, or write files with the Write tool. `H` is an alias
  (`Get-History`); `Invoke-RestMethod` mis-decodes UTF-8 for display only.
- Bash heredocs collapse backslashes; psql `E'\s'` blanks every `s`.
- RAM on this PC is tight (other bots run here): watch free RAM in long job loops; a
  dead CPU worker leaves uploads stuck at pending/processing (see `docs/runbooks.md`).
- Large text-layer PDFs can carry unreadable glyph-id text (`layout.text_layer_readable`
  now routes those to OCR). Old-style numerals OCR as letters (`text_health`).
- Element type for lists is `"list"` (not `list_item`).
- `tests/test_code_exec.py::test_a_program_that_frees_memory_twice_has_no_defined_output`
  is flaky (undefined behaviour by design) — re-run it alone before blaming a change.
- Ruff baseline: a few pre-existing findings exist (e.g. SIM103 in
  `ai-worker/validators.py`, E501/SIM102/I001 in some tests). Don't add new ones;
  compare against `git stash` when unsure.

## Where to look first

| Task | Start in |
|---|---|
| Bad quiz/summary/cards | `docs/generation-checks.md`, then `tasks_gen.py`, `validators.py`, `quizplan.py`, `prompts.py` |
| Extraction / OCR / viewer text | `processing/pipeline.py`, `layout.py`, `text_health.py`, `text_html.py` |
| Narration (Steven reads) | `services/narration.py`, `processing/narration_script.py`, `ai-worker/tts_client.py` |
| Push, reminders, daily letter | `services/scheduler.py`, `api/assistant.py` |
| Calendar semantics (sync/async marks) | `web/src/features/calendar/CalendarPage.tsx` (`meetingMode`), `scheduler.class_mode` |
| Retrieval / RAG | `packages/core-py/src/manabi_core/retrieval.py`, `api/chat.py` |
