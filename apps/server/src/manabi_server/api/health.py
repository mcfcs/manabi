from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from manabi_core.models import AINodeHeartbeat
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.config import get_settings
from manabi_server.db import get_db

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    settings = get_settings()
    await db.execute(text("SELECT 1"))

    threshold = datetime.now(UTC) - timedelta(seconds=settings.ai_heartbeat_stale_seconds)
    heartbeats = (await db.execute(select(AINodeHeartbeat))).scalars().all()
    ai_online = any(hb.last_seen_at >= threshold for hb in heartbeats)

    return {
        "status": "ok",
        "database": "ok",
        "ai_node": {
            "online": ai_online,
            "last_seen_at": max(
                (hb.last_seen_at for hb in heartbeats), default=None
            ),
        },
    }
