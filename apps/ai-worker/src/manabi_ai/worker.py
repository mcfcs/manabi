"""GPU worker entry point: `python -m manabi_ai.worker`.

Runs the Procrastinate worker (gpu queue, concurrency=1 — that IS the GPU
semaphore) alongside a heartbeat loop whose row freshness powers the
"AI ● online" indicator in the UI.
"""

import asyncio
import logging
import sys

from sqlalchemy import text

from manabi_ai.app import app
from manabi_ai.config import get_settings
from manabi_ai.db import session_factory

log = logging.getLogger("manabi_ai")


async def _heartbeat_loop() -> None:
    settings = get_settings()
    while True:
        try:
            async with session_factory()() as db:
                await db.execute(
                    text(
                        """
                        INSERT INTO ai_node_heartbeats (worker_name, last_seen_at)
                        VALUES (:name, now())
                        ON CONFLICT (worker_name)
                        DO UPDATE SET last_seen_at = now()
                        """
                    ),
                    {"name": settings.worker_name},
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001 — keep beating through transient DB drops
            log.warning("heartbeat failed: %s", exc)
        await asyncio.sleep(settings.heartbeat_interval_seconds)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    heartbeat = asyncio.create_task(_heartbeat_loop())
    try:
        async with app.open_async():
            await app.run_worker_async(queues=["gpu"], concurrency=1)
    finally:
        heartbeat.cancel()


if __name__ == "__main__":
    if sys.platform == "win32":
        # psycopg async cannot run on the default ProactorEventLoop
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
