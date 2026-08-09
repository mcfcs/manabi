@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Manabi backup

echo.
echo   Manabi - backup database + files
echo.

REM ── 0. Postgres must be up ────────────────────────────────────────────
docker exec manabi-postgres pg_isready -U manabi -d manabi >nul 2>&1
if errorlevel 1 (
    echo [ERROR]    manabi-postgres is not running. Start Manabi first.
    pause
    exit /b 1
)

REM ── 1. Dated target folder ────────────────────────────────────────────
set STAMP=
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmm"') do set STAMP=%%i
set DEST=backups\!STAMP!
mkdir "!DEST!" >nul 2>&1

REM ── 2. Database dump (custom format, inside the container, then copy) ─
echo [db]       dumping...
docker exec manabi-postgres pg_dump -U manabi -d manabi -Fc -f /tmp/manabi.dump
if errorlevel 1 (
    echo [ERROR]    pg_dump failed
    pause
    exit /b 1
)
docker cp manabi-postgres:/tmp/manabi.dump "!DEST!\manabi.dump" >nul
docker exec manabi-postgres rm -f /tmp/manabi.dump
echo [db]       !DEST!\manabi.dump

REM ── 3. Uploaded files + renders ───────────────────────────────────────
echo [storage]  copying...
robocopy storage "!DEST!\storage" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
    echo [ERROR]    robocopy failed copying storage\
    pause
    exit /b 1
)
echo [storage]  !DEST!\storage

REM ── 4. Keep only the 7 newest backups ─────────────────────────────────
powershell -NoProfile -Command ^
  "Get-ChildItem backups -Directory | Sort-Object Name -Descending | Select-Object -Skip 7 | Remove-Item -Recurse -Force"

echo.
echo   Done. Restore steps: docs\runbooks.md
echo.
pause
