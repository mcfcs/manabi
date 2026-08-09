@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Manabi launcher

echo.
echo   Manabi - start everything
echo   (pass --rebuild to force a fresh web build)
echo.

REM ── 0. .env ────────────────────────────────────────────────────────────
if not exist .env (
    copy .env.example .env >nul
    echo [env]      created .env from .env.example
)

REM ── 1. Docker Desktop ─────────────────────────────────────────────────
docker info >nul 2>&1
if errorlevel 1 (
    echo [docker]   starting Docker Desktop...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    :wait_docker
    timeout /t 3 /nobreak >nul
    docker info >nul 2>&1
    if errorlevel 1 goto wait_docker
)
echo [docker]   ready

REM ── 2. Database ───────────────────────────────────────────────────────
docker compose -f infra\compose.yaml up -d >nul 2>&1
:wait_pg
docker exec manabi-postgres pg_isready -U manabi -d manabi >nul 2>&1
if errorlevel 1 (
    timeout /t 2 /nobreak >nul
    goto wait_pg
)
echo [postgres] ready on port 56661

REM ── 3. Migrations (idempotent) ────────────────────────────────────────
uv run --package manabi-server alembic -c apps\server\alembic.ini upgrade head >nul 2>&1
if errorlevel 1 (
    echo [ERROR]    database migration failed - run it manually to see why:
    echo            uv run --package manabi-server alembic -c apps\server\alembic.ini upgrade head
    pause
    exit /b 1
)
uv run procrastinate --app=manabi_ai.app.app schema --apply >nul 2>&1
echo [migrate]  schema up to date

REM ── 4. Web build (only if missing, or --rebuild) ──────────────────────
set NEED_BUILD=0
if not exist apps\web\dist\index.html set NEED_BUILD=1
if "%~1"=="--rebuild" set NEED_BUILD=1
if "!NEED_BUILD!"=="1" (
    echo [web]      building...
    call pnpm --filter web run build >nul 2>&1
    if errorlevel 1 (
        echo [ERROR]    web build failed - run manually: pnpm --filter web run build
        pause
        exit /b 1
    )
)
echo [web]      built

REM ── 5. Services (each in its own window, skipped if already running) ──
REM Health-check the port: healthy API → skip; zombie holder → kill, then start.
powershell -NoProfile -Command ^
  "$c = Get-NetTCPConnection -LocalPort 56690 -State Listen -ErrorAction SilentlyContinue; if (-not $c) { exit 1 }; try { $r = Invoke-WebRequest -Uri 'http://localhost:56690/api/health' -UseBasicParsing -TimeoutSec 3; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; $c | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }; Start-Sleep -Seconds 1; exit 1"
if errorlevel 1 (
    start "Manabi API" cmd /k uv run --package manabi-server uvicorn manabi_server.main:app --host 0.0.0.0 --port 56690
) else (
    echo [api]      already running and healthy on port 56690 - not starting another
)

powershell -NoProfile -Command "exit ((Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'manabi_ai\.worker' }).Count)" >nul 2>&1
if not errorlevel 1 (
    start "Manabi AI worker" cmd /k uv run python -m manabi_ai.worker
) else (
    echo [worker]   AI worker already running - not starting another
)

powershell -NoProfile -Command "exit ((Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'manabi_server\.worker' }).Count)" >nul 2>&1
if not errorlevel 1 (
    start "Manabi CPU worker" cmd /k uv run python -m manabi_server.worker
) else (
    echo [worker]   CPU worker already running - not starting another
)

REM ── 6. URLs ───────────────────────────────────────────────────────────
set TSIP=
for /f "delims=" %%i in ('tailscale ip -4 2^>nul') do if not defined TSIP set TSIP=%%i
echo.
echo   Manabi is starting in three windows (API + AI worker + CPU worker).
echo.
echo   This computer:   http://localhost:56690
if defined TSIP (
    echo   Tailscale:       http://%TSIP%:56690
    echo                    ^(or http://%COMPUTERNAME%:56690 with MagicDNS^)
) else (
    echo   Tailscale:       http://^<this-machine's-tailscale-name^>:56690
)
echo.
echo   First run: if Windows Firewall asks, click "Allow" so tailnet
echo   devices can reach the server.
echo.
pause
