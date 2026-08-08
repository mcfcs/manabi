# phillmyeol — AI node setup

The GPU worker pulls `gpu`-queue jobs from the app server's Postgres over
Tailscale. **phillmyeol exposes no ports**; Ollama stays on 127.0.0.1.

## One-time setup

1. Install [Ollama](https://ollama.com) and pull models:
   ```powershell
   ollama pull qwen3.5:27b
   ```
2. Install uv, clone the repo, then from the repo root:
   ```powershell
   uv sync
   ```
3. Create `.env` in the repo root on this machine:
   ```ini
   DATABASE_URL=postgresql+asyncpg://manabi_gpu:<password>@<app-server-magicdns>:5432/manabi
   DATABASE_URL_SYNC=postgresql+psycopg://manabi_gpu:<password>@<app-server-magicdns>:5432/manabi
   OLLAMA_URL=http://127.0.0.1:11434
   GENERATION_MODEL=qwen3.5:27b
   ```
   Use the Tailscale MagicDNS name, never a raw IP.
4. On the app server, create the minimal-grant role:
   ```sql
   CREATE ROLE manabi_gpu LOGIN PASSWORD '<password>';
   GRANT SELECT, UPDATE ON jobs TO manabi_gpu;
   GRANT INSERT, UPDATE, SELECT ON ai_node_heartbeats TO manabi_gpu;
   GRANT USAGE ON SCHEMA procrastinate TO manabi_gpu;
   GRANT ALL ON ALL TABLES IN SCHEMA procrastinate TO manabi_gpu;
   GRANT ALL ON ALL SEQUENCES IN SCHEMA procrastinate TO manabi_gpu;
   ```
   (Later phases grant read on chunks/documents and insert on artifacts.)
5. Tailscale ACL: allow phillmyeol → app-server:5432 and :443 only; nothing
   may connect **to** phillmyeol.

## Run

```powershell
uv run python -m manabi_ai.worker
```

## Run as a Windows service (NSSM)

```powershell
nssm install ManabiGpuWorker "C:\path\to\uv.exe" "run python -m manabi_ai.worker"
nssm set ManabiGpuWorker AppDirectory "C:\path\to\manabi"
nssm set ManabiGpuWorker AppExit Default Restart
nssm start ManabiGpuWorker
```

Laptop asleep / Tailscale down ⇒ jobs simply wait in the queue and the UI
shows the AI node as offline. Everything resumes on wake.
