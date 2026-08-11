"""CPU worker entry point: `python -m manabi_server.worker`.

Consumes the `cpu` queue (document processing, later: embeddings, exports).
Runs on the app server; the `gpu` queue worker lives in apps/ai-worker.
"""

import asyncio
import logging
import os
import sys

# Docling's layout models attempt torch.compile, which needs MSVC on Windows.
# Eager mode produces identical results without a C++ toolchain.
os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")

from manabi_server.jobs.tasks import app  # noqa: E402


def _startup_embedding_sweep() -> None:
    """Backfill embeddings for any chunks created before this feature."""
    from manabi_server.jobs.tasks import db_session
    from manabi_server.processing.embedding import embed_missing_chunks_sync

    try:
        with db_session() as db:
            n = embed_missing_chunks_sync(db)
            if n:
                logging.getLogger("manabi").info("backfilled %d chunk embeddings", n)
    except Exception:  # noqa: BLE001 — sweep is best-effort; pipeline retries cover it
        logging.getLogger("manabi").exception("embedding sweep failed")


def _reap_orphans() -> None:
    """Any cpu procrastinate job left 'doing' at startup is orphaned (its worker
    died mid-extraction). Requeue it — document processing resumes from its
    stage checkpoint, so this is cheap and safe."""
    from sqlalchemy import text

    from manabi_server.jobs.tasks import db_session

    try:
        with db_session() as db:
            res = db.execute(
                text(
                    "UPDATE procrastinate_jobs SET status='todo' "
                    "WHERE status='doing' AND queue_name='cpu'"
                )
            )
            if res.rowcount:
                logging.getLogger("manabi").info(
                    "requeued %d orphaned cpu job(s)", res.rowcount
                )
            db.commit()
    except Exception:  # noqa: BLE001 — best-effort, never block startup
        logging.getLogger("manabi").warning("cpu orphan reap failed")


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await asyncio.to_thread(_startup_embedding_sweep)
    await asyncio.to_thread(_reap_orphans)
    async with app.open_async():
        # 2 = two documents can parse in parallel (sync tasks run in threads)
        await app.run_worker_async(queues=["cpu"], concurrency=2)


if __name__ == "__main__":
    if sys.platform == "win32":
        # psycopg async cannot run on the default ProactorEventLoop
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
