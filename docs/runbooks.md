# Manabi runbooks

## Backup

Run `backup-manabi.bat` from the repo root (Postgres container must be up).
It writes `backups\<yyyy-MM-dd_HHmm>\` containing:

- `manabi.dump` — full database dump (`pg_dump -Fc`, custom format)
- `storage\` — every uploaded file, page render, and export

Only the 7 newest backup folders are kept; older ones are deleted
automatically. The `backups\` folder lives next to the repo — copy it to an
external drive or cloud folder occasionally for real disaster protection.

## Restore

1. Start only the database: `docker compose -f infra\compose.yaml up -d postgres`
2. Recreate an empty database (this **destroys** the current one):
   ```powershell
   docker exec manabi-postgres psql -U manabi -d postgres -c "DROP DATABASE manabi WITH (FORCE)"
   docker exec manabi-postgres psql -U manabi -d postgres -c "CREATE DATABASE manabi OWNER manabi"
   ```
3. Load the dump:
   ```powershell
   docker cp backups\<stamp>\manabi.dump manabi-postgres:/tmp/manabi.dump
   docker exec manabi-postgres pg_restore -U manabi -d manabi /tmp/manabi.dump
   docker exec manabi-postgres rm -f /tmp/manabi.dump
   ```
4. Restore files: `robocopy backups\<stamp>\storage storage /E`
5. `start-manabi.bat` as usual.

## Moving the GPU worker to phillmyeol

Full runbook: [infra/phillmyeol/README.md](../infra/phillmyeol/README.md).
Short version — on phillmyeol: clone, `uv sync`, `.env` pointing at this
PC's Postgres over Tailscale, run/install the worker. On this PC:
`setx SKIP_GPU_WORKER 1` so `start-manabi.bat` stops opening the local
GPU-worker window.

## Zombie API process holding port 56690

`start-manabi.bat` health-checks the port and kills any process that
listens on 56690 but does not answer `/api/health`. If the API window
disappears but the port stays busy, just run the bat again.
