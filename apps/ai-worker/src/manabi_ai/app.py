"""Procrastinate app + gpu-queue task definitions.

Task NAMES are the contract with the app server (which defers by name);
keep them stable.
"""

from datetime import UTC, datetime

import httpx
import procrastinate
from manabi_core.models import Job, JobStatus
from sqlalchemy import select

from manabi_ai.config import get_settings
from manabi_ai.db import session_factory


def _conninfo() -> str:
    return get_settings().database_url_sync.replace("postgresql+psycopg", "postgresql")


app = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=_conninfo()))


async def _ollama_one_token() -> dict:
    """Minimal generation proving the Ollama path; never raises."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{settings.ollama_url}/api/generate",
                json={
                    "model": settings.generation_model,
                    "prompt": "Reply with the single word: pong",
                    "stream": False,
                    "options": {"num_predict": 5},
                },
            )
            r.raise_for_status()
            return {"ollama": "ok", "response": r.json().get("response", "").strip()}
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:200]
        return {"ollama": f"error {exc.response.status_code} from {settings.ollama_url}: {detail}"}
    except Exception as exc:  # noqa: BLE001 — degrade, don't fail the spine test
        return {"ollama": f"unreachable ({settings.ollama_url}): {type(exc).__name__}: {exc}"}


@app.task(name="manabi_ai.tasks.echo", queue="gpu")
async def echo(job_id: int) -> None:
    """Phase-0 spine test: mark the app-level Job running, ping Ollama, finish."""
    async with session_factory()() as db:
        job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()
        job.status = JobStatus.running
        job.started_at = datetime.now(UTC)
        job.progress_note = "running on " + get_settings().worker_name
        await db.commit()

        result = {"echo": "pong", **await _ollama_one_token()}

        job.status = JobStatus.succeeded
        job.result = result
        job.progress_pct = 100
        job.finished_at = datetime.now(UTC)
        await db.commit()
