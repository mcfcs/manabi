---
name: manabi-deploy
description: Redeploy Manabi (API, CPU worker, GPU worker, web build, migrations) through start-manabi.bat and prove the new code is running. Use after ANY committed change to apps/server, apps/ai-worker, packages/core-py or apps/web, whenever asked to restart/redeploy/"apply" Manabi, and before testing a change in the real app.
---

# Deploy Manabi

RULES.md §3 is the authority; this is its executable form. Services start ONLY
through `start-manabi.bat` — never uvicorn, workers, vite dev or the TTS server by
hand. Committed code that isn't running doesn't count as shipped.

## 1. Gate: nothing running

```powershell
(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:56690/api/jobs/active).Content
```

Compare the RAW body to `[]` (PowerShell 5.1's parsed `.Count` is unreliable). If a
job is running, wait — never kill a generation or narration. A stale job you
started yourself: `POST /api/jobs/{id}/cancel` (header `X-Requested-With: fetch`),
not a redeploy over it.

## 2. Launch hidden, fresh log

The bat runs 2–5 min (migrations, web build, restarts). Run in the foreground it
outlives the tool timeout and its children hold the handle, so launch it detached
with a log path never used before (a reused path fails before cmd starts):

```powershell
$start = Get-Date
$log = "<scratchpad>\deploy-$(Get-Date -Format yyyyMMddHHmmss).log"
Start-Process -WindowStyle Hidden cmd -ArgumentList '/c', "c:\Users\Gio\Documents\GitHub\manabi\start-manabi.bat --quiet > `"$log`" 2>&1"
```

Never pipe the bat's output through `Select-Object` (it hangs).

## 3. Prove it is running (all three)

Poll in one command (5 s steps, ≤ ~8 min) until the web build is newer than
`$start`, the API is a fresh process, and health is 200:

```powershell
for ($i=0; $i -lt 100; $i++) { Start-Sleep -Seconds 5
  $dist = (Get-Item c:\Users\Gio\Documents\GitHub\manabi\apps\web\dist\index.html -ErrorAction SilentlyContinue).LastWriteTime
  $ok = $false; try { $ok = (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:56690/api/health -TimeoutSec 5).StatusCode -eq 200 } catch {}
  $api = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'uvicorn' } | Sort-Object CreationDate -Descending | Select-Object -First 1
  if ($dist -gt $start -and $ok -and $api.CreationDate -gt $start) { "deployed: dist $dist, api $($api.CreationDate)"; break } }
```

Then confirm the workers restarted too — `manabi_server.worker` (CPU) and
`manabi_ai.worker` (GPU) python processes with a CreationDate after `$start`:

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'manabi_server.worker|manabi_ai.worker|uvicorn' } | Select-Object ProcessId, CreationDate
```

After a model or migration change, check the revision:
`docker exec manabi-postgres psql -U manabi -d manabi -tc "select version_num from alembic_version;"`

## 4. Report

State what was verified (health, fresh start times, migration head), or exactly
which check failed. If the deploy didn't come up, read the log tail and say so —
don't relaunch blindly. Never kill Gio's other python processes (stockx/lazada/
facebook monitors, naa, monitors.py).
