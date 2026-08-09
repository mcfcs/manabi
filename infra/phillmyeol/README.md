# phillmyeol — GPU worker runbook

Moves the GPU worker (summaries, cards, quizzes, chat) from the app-server
PC onto phillmyeol, next to Ollama. The worker **pulls** `gpu`-queue jobs
from the app server's Postgres over Tailscale; phillmyeol accepts no
inbound connections and Ollama stays on 127.0.0.1.

Everything below is run **on phillmyeol** unless marked *(app server)*.

## 1. Ollama + models

Ollama is already installed and serving on phillmyeol. Make sure the three
models are present:

```powershell
ollama pull qwen3.5:27b
ollama pull gpt-oss:20b
ollama pull qwen2.5vl:7b
```

(qwen3-embedding stays on the app server — embeddings are computed there so
search keeps working while this laptop sleeps.)

## 2. Repo + Python env

```powershell
winget install astral-sh.uv
git clone <repo-url> C:\manabi
cd C:\manabi
uv sync
```

## 3. Expose Postgres to the tailnet *(app server)*

The compose file maps Postgres to host port **56661**. Two things must
allow phillmyeol to reach it:

1. Windows Defender Firewall → inbound rule allowing TCP 56661
   (scope it to the Tailscale interface / 100.64.0.0/10 if you want).
2. Nothing else — Docker already binds the port on all interfaces.

Then create the worker role in psql
(`docker exec -it manabi-postgres psql -U manabi -d manabi`):

```sql
CREATE ROLE manabi_gpu LOGIN PASSWORD '<pick-a-password>';
GRANT USAGE ON SCHEMA public, procrastinate TO manabi_gpu;
-- Single-user setup: the worker reads sources and writes artifacts, cards,
-- quizzes, citations, chat messages, job previews and heartbeats.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO manabi_gpu;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO manabi_gpu;
GRANT ALL ON ALL TABLES IN SCHEMA procrastinate TO manabi_gpu;
GRANT ALL ON ALL SEQUENCES IN SCHEMA procrastinate TO manabi_gpu;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA procrastinate TO manabi_gpu;
```

## 4. `.env` on phillmyeol

Create `C:\manabi\.env` (use the app-server's MagicDNS name, never an IP —
find it with `tailscale status`):

```ini
DATABASE_URL=postgresql+asyncpg://manabi_gpu:<password>@<app-server-name>:56661/manabi
DATABASE_URL_SYNC=postgresql+psycopg://manabi_gpu:<password>@<app-server-name>:56661/manabi
OLLAMA_URL=http://127.0.0.1:11434
GENERATION_MODEL=qwen3.5:27b
CHAT_MODEL=gpt-oss:20b
```

Smoke test: `uv run python -m manabi_ai.worker` — the app-server UI header
should show the AI node as online within ~15 s, and a "Generate summary"
click should stream.

## 5. Run as a Windows service (NSSM)

```powershell
winget install nssm
nssm install ManabiGpuWorker "$((Get-Command uv).Source)" "run python -m manabi_ai.worker"
nssm set ManabiGpuWorker AppDirectory "C:\manabi"
nssm set ManabiGpuWorker AppExit Default Restart
nssm start ManabiGpuWorker
```

## 6. Flip the app server *(app server)*

1. `setx SKIP_GPU_WORKER 1` — `start-manabi.bat` stops opening the local
   GPU-worker window (close the currently open one).
2. `.env` keeps `OLLAMA_URL=http://phillmyeol:11434` — the app server still
   uses it for the VLM OCR fallback during document processing. The
   embedding URL (`EMBEDDING_OLLAMA_URL`, default 127.0.0.1) is separate
   and unchanged.

## Behaviour when the laptop sleeps

Jobs wait in the Postgres queue, the UI header shows the AI node offline
(heartbeat stale after 45 s), and everything resumes on wake — nothing to
restart. Uploads, search, notes, and reading keep working the whole time
because extraction + embeddings run on the app server.
