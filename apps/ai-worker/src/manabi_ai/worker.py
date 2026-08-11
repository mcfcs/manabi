"""GPU worker entry point: `python -m manabi_ai.worker`.

Runs the Procrastinate worker (gpu queue, concurrency=1 — that IS the GPU
semaphore) alongside a heartbeat loop whose row freshness powers the
"AI ● online" indicator in the UI.
"""

import asyncio
import json
import logging
import sys

import httpx
from sqlalchemy import text

import manabi_ai.tasks_gen  # noqa: F401 — registers generation tasks
import manabi_ai.tasks_tts  # noqa: F401 — registers voice tasks
from manabi_ai.app import app
from manabi_ai.config import get_settings
from manabi_ai.db import session_factory

log = logging.getLogger("manabi_ai")


async def _ollama_models(settings) -> list[str]:
    """Model tags installed on this node's Ollama — for the Settings model
    dropdown. Best-effort; empty on any error."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{settings.ollama_url}/api/tags")
            r.raise_for_status()
            return sorted(m["name"] for m in r.json().get("models", []) if m.get("name"))
    except Exception:  # noqa: BLE001 — heartbeat must never fail on this
        return []


async def _heartbeat_loop() -> None:
    settings = get_settings()
    models: list[str] = []
    beat = 0
    while True:
        try:
            # Refresh the model list occasionally (and keep retrying until we have one).
            if beat % 20 == 0 or not models:
                models = await _ollama_models(settings)
            info = json.dumps({"tts": settings.tts_enabled, "models": models})
            async with session_factory()() as db:
                await db.execute(
                    text(
                        """
                        INSERT INTO ai_node_heartbeats (worker_name, last_seen_at, gpu_info)
                        VALUES (:name, now(), cast(:info AS json))
                        ON CONFLICT (worker_name)
                        DO UPDATE SET last_seen_at = now(), gpu_info = cast(:info AS json)
                        """
                    ),
                    {"name": settings.worker_name, "info": info},
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001 — keep beating through transient DB drops
            log.warning("heartbeat failed: %s", exc)
        beat += 1
        await asyncio.sleep(settings.heartbeat_interval_seconds)


async def _reap_orphans() -> None:
    """Single-concurrency gpu worker: any procrastinate job left 'doing' at
    startup is orphaned (its worker died). Release it and fail the matching
    manabi job so the UI stops spinning. gpu work isn't auto-retried — it's
    expensive; the user re-triggers if they still want it."""
    try:
        async with session_factory()() as db:
            rows = (
                await db.execute(
                    text(
                        "SELECT id FROM procrastinate_jobs "
                        "WHERE status='doing' AND queue_name='gpu'"
                    )
                )
            ).all()
            orphan_ids = [r[0] for r in rows]
            if not orphan_ids:
                return
            await db.execute(
                text(
                    "UPDATE jobs SET status='failed', "
                    "error='interrupted — worker restarted', finished_at=now() "
                    "WHERE procrastinate_job_id = ANY(:ids) AND status='running'"
                ),
                {"ids": orphan_ids},
            )
            await db.execute(
                text(
                    "UPDATE procrastinate_jobs SET status='aborted' "
                    "WHERE id = ANY(:ids) AND status='doing'"
                ),
                {"ids": orphan_ids},
            )
            await db.commit()
            log.info("reaped %d orphaned gpu job(s)", len(orphan_ids))
    except Exception as exc:  # noqa: BLE001 — best-effort, never block startup
        log.warning("orphan reap failed: %s", exc)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    heartbeat = asyncio.create_task(_heartbeat_loop())
    try:
        async with app.open_async():
            await _reap_orphans()
            await app.run_worker_async(queues=["gpu"], concurrency=1)
    finally:
        heartbeat.cancel()


if __name__ == "__main__":
    if sys.platform == "win32":
        # psycopg async cannot run on the default ProactorEventLoop
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
