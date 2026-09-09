"""Actually remove documents that were soft-deleted long enough ago.

`DELETE /api/documents/{id}` sets `deleted_at` and says the file is
"recoverable until a future purge job". That job did not exist, so every
deleted document kept its original, its rendered pages, its thumbnails and its
normalized PDF forever — and renders are by far the largest thing on disk.
Nothing ever shrank.

Retention is deliberately long: the point of the soft delete is that a
mis-click is undoable for a while.
"""

import logging
from datetime import UTC, datetime, timedelta

from manabi_core.models import Document
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.storage import files

log = logging.getLogger("manabi.purge")

RETENTION = timedelta(days=30)


async def purge_deleted_documents(db: AsyncSession, *, retention: timedelta = RETENTION) -> int:
    """Drop rows soft-deleted before the cutoff, and the files they own.
    Returns how many were purged."""
    cutoff = datetime.now(UTC) - retention
    doomed = (
        await db.execute(
            select(Document.id, Document.storage_path).where(
                Document.deleted_at.is_not(None), Document.deleted_at < cutoff
            )
        )
    ).all()
    if not doomed:
        return 0
    await db.execute(delete(Document).where(Document.id.in_([d[0] for d in doomed])))
    await db.commit()
    files.delete_files_for_documents(doomed)
    log.info("purged %d soft-deleted document(s)", len(doomed))
    return len(doomed)
