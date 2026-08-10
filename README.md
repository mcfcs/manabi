# Manabi 学び

Personal AI study workspace, self-hosted and single-user. Courses → modules →
materials, with a privately hosted LLM doing the heavy lifting — everything
**source-grounded with page citations**, nothing invented.

## What it does

- **Materials** — PDF/PPTX upload or Canvas import; Docling parse → page
  renders → structure-aware chunks → pgvector embeddings. Viewer with text
  layer, tables, highlights, annotations, native "Original" PDF mode
  (browser Ctrl+F). Per-document AI include/exclude; render-only mode for
  files that shouldn't feed the AI.
- **AI artifacts** — summaries (coverage-tracked key terms/acronyms),
  flashcards (Anki .apkg export), quizzes with attempt history, all with
  page-cited claims, staleness detection, and version history.
- **Teacher mode** — Steven A. Starphase teaches each module: scripted
  lectures (standard/cram/deep-dive) with self-graded checkpoints and weak-spot
  remediation, spoken in a fine-tuned GPT-SoVITS voice (LecturePlayer with
  lockscreen controls). Quiz debriefs and "Ask Steven" from any selected
  passage.
- **Chat** — per-module threads grounded in the materials (says so honestly
  when they don't cover it). Per-thread **source scoping** (pick specific
  files/note sections), Steven persona toggle, spoken replies, voice input.
- **Notes** — multiple sections per module (Google-Docs-style sidebar),
  Tiptap editor with tables/checklists/math/**images**, autosave + snapshots,
  .docx export. Notes feed chat context ("According to your notes…").
- **Life admin** — class schedule (groups, sync/async marks, meet links),
  calendar (month/week/day, Google Calendar ICS feeds in + .ics export out,
  tasks overlaid), tasks with Canvas assignment auto-sync (last-synced shown),
  Canvas announcements, spaced repetition (/review, SM-2), global search
  (Ctrl+K), study stats, web-push notifications (due digests, class
  reminders, announcements).

## Architecture

```
apps/web        Vite + React + TS SPA (PWA, injectManifest SW)
apps/server     FastAPI (port 56690) + CPU-queue Procrastinate worker
                (parse/render/chunk/embed pipeline, embeddings on CPU)
apps/ai-worker  GPU-queue Procrastinate worker: generation via Ollama,
                TTS via GPT-SoVITS (api_v2 on 127.0.0.1:9880)
packages/core-py  shared SQLAlchemy models + retrieval (THE scoped chunk access)
infra/          compose (Postgres 16 + pgvector on host port 56661),
                phillmyeol runbook
```

**Pull topology**: the GPU worker only talks to Postgres — it pulls `gpu`-queue
jobs and writes results (including audio) back as rows. No inbound ports on
the AI node; AI-online status = heartbeat freshness. The worker currently runs
on the main PC (4070); `infra/phillmyeol/` documents moving it to the 5090
laptop over Tailscale (the TTS install moves with it — `docs/teacher-voice.md`).

## Running

Single user, no login — access control is the Tailscale boundary.

```bat
start-manabi.bat            :: Docker + Postgres, migrations, web build if
                            ::   missing, then windows: API, AI worker,
                            ::   CPU worker, TTS (Steven)
start-manabi.bat --rebuild  :: same, but force a fresh web build
backup-manabi.bat           :: pg_dump + file-storage copy, keeps 7
```

First-time setup: install uv + pnpm, `uv sync`, `pnpm install`, copy `.env`
keys (see below).

### Addresses — and why HTTPS matters

- `http://localhost:56690` — this machine.
- `https://peakfiction.tail580e35.ts.net` — any tailnet device, via
  `tailscale serve --bg 56690`. **Use this one on phones**: browsers only
  allow service-worker push notifications and PWA install on secure (HTTPS)
  origins. The scheme is what matters, not the port — `http://…:56690` can
  never do push, while any `https://…` URL can.

### Running more HTTPS sites on this machine

`tailscale serve` can front any number of local apps, each on its own TLS
port, all with valid certs (so notifications etc. work on every one):

```bat
tailscale serve --bg 56690                      :: :443  -> Manabi
tailscale serve --bg --https=8443 56791         :: :8443 -> another app
tailscale serve --bg --https=8444 <local-port>  :: :8444 -> the next one…
tailscale serve status                          :: see the current map
```

Then open `https://peakfiction.tail580e35.ts.net:<tls-port>`. Only :443 gets
the bare URL; everything else carries its port — which is fine, because it's
still HTTPS.

## Configuration (`.env`, gitignored — secrets never reach the client)

| Key | Purpose |
| --- | --- |
| `DATABASE_URL` / `DATABASE_URL_SYNC` | Postgres on host port 56661 |
| `FILE_STORAGE_ROOT` | originals/renders/thumbs/note images on disk |
| `OLLAMA_URL`, `GENERATION_MODEL`, `CHAT_MODEL` | qwen3.5:27b generation, gpt-oss:20b chat |
| `EMBEDDING_MODEL`, `EMBEDDING_DIM` | qwen3-embedding:0.6b on the app-server CPU |
| `CANVAS_BASE_URL`, `CANVAS_ACCESS_TOKEN` | Canvas file import, assignments, announcements |
| `GCAL_ICS_URLS` | comma-separated `Name\|secret-ics-url` Google feeds |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` | web push (py_vapid) |
| `TTS_URL`, `TTS_REF_AUDIO`, `TTS_REF_TEXT`, `TTS_TUNED_GPT`, `TTS_TUNED_SOVITS` | Steven's voice (GPT-SoVITS); TTS disabled if unset |

Workers cache settings — restart them after `.env` edits.

## Development

```bash
uv run --package manabi-server uvicorn manabi_server.main:app --reload --port 56690
pnpm --filter web dev        # Vite on :5173, proxies /api to :56690

uv run pytest apps/server/tests -q      # server + shared-core tests
pnpm --filter web test                  # vitest
pnpm --filter web typecheck && pnpm --filter web build
uv run ruff check apps packages
```

Migrations: `uv run alembic -c apps/server/alembic.ini upgrade head`
(new revision files live in `apps/server/alembic/versions/`).

More docs: `docs/runbooks.md` (ops/recovery), `docs/teacher-voice.md`
(voice setup + fine-tuning), `infra/phillmyeol/` (moving the GPU worker).
