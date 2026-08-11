"""AI-node introspection: the Ollama models installed on the GPU worker, so the
Settings UI can offer a model dropdown for the general assistant. The worker
advertises them in its heartbeat's gpu_info.models."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from manabi_core.models import AINodeHeartbeat
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.config import get_settings
from manabi_server.db import get_db

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/models")
async def list_models(db: AsyncSession = Depends(get_db)) -> dict:
    hb = (
        await db.execute(
            select(AINodeHeartbeat)
            .order_by(AINodeHeartbeat.last_seen_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if hb is None:
        return {"models": [], "online": False, "worker": None}
    threshold = datetime.now(UTC) - timedelta(
        seconds=get_settings().ai_heartbeat_stale_seconds
    )
    info = hb.gpu_info or {}
    return {
        "models": info.get("models", []),
        "online": hb.last_seen_at >= threshold,
        "worker": hb.worker_name,
    }
