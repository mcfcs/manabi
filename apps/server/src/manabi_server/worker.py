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


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    async with app.open_async():
        await app.run_worker_async(queues=["cpu"], concurrency=1)


if __name__ == "__main__":
    if sys.platform == "win32":
        # psycopg async cannot run on the default ProactorEventLoop
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
