"""Procrastinate app for the server side.

The server DEFERS gpu-queue tasks by name; their implementations live in
apps/ai-worker (manabi_ai.tasks) and run on phillmyeol. CPU-queue task
implementations will live here from Phase 2 on.

Uses the SYNC connector: deferring is a quick INSERT, and psycopg's async
pool cannot run on Windows' ProactorEventLoop (uvicorn's default there).
Call defer_task() from async code — it hops to a thread.
"""

import asyncio
import threading

import procrastinate

from manabi_server.config import get_settings

# Task names are the contract between server (defer) and ai-worker (execute).
ECHO_TASK = "manabi_ai.tasks.echo"

_app: procrastinate.App | None = None
_lock = threading.Lock()


def _get_open_app() -> procrastinate.App:
    global _app
    with _lock:
        if _app is None:
            conninfo = get_settings().database_url_sync.replace(
                "postgresql+psycopg", "postgresql"
            )
            app = procrastinate.App(
                connector=procrastinate.SyncPsycopgConnector(conninfo=conninfo)
            )
            app.open()
            _app = app
    return _app


async def defer_task(task_name: str, queue: str, **task_kwargs) -> int:
    """Defer a Procrastinate job; returns the procrastinate job id."""

    def _defer() -> int:
        app = _get_open_app()
        return app.configure_task(task_name, queue=queue).defer(**task_kwargs)

    return await asyncio.to_thread(_defer)
