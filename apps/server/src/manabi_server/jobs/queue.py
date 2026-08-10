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

# Task names are the contract between deferrer and worker.
ECHO_TASK = "manabi_ai.tasks.echo"  # gpu queue (phillmyeol)
GENERATE_SUMMARY_TASK = "manabi_ai.tasks.generate_summary"  # gpu
GENERATE_FLASHCARDS_TASK = "manabi_ai.tasks.generate_flashcards"  # gpu
GENERATE_QUIZ_TASK = "manabi_ai.tasks.generate_quiz"  # gpu
DEFINE_TERM_TASK = "manabi_ai.tasks.define_term"  # gpu
CHAT_ANSWER_TASK = "manabi_ai.tasks.chat_answer"  # gpu
TEACH_MODULE_TASK = "manabi_ai.tasks.teach_module"  # gpu
SYNTHESIZE_LECTURE_TASK = "manabi_ai.tasks.synthesize_lecture"  # gpu
SPEAK_TEXT_TASK = "manabi_ai.tasks.speak_text"  # gpu
PROCESS_DOCUMENT_TASK = "manabi_server.tasks.process_document"  # cpu queue (app server)
SCORE_SUPPORT_TASK = "manabi_server.tasks.score_support"  # cpu (needs local embed model)
EXTRACT_TEXT_HTML_TASK = "manabi_server.tasks.extract_text_html"  # cpu (backfill)

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
