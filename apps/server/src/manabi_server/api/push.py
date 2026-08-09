"""Web Push subscription management + test send."""

from fastapi import APIRouter, Depends, Header, HTTPException
from manabi_core.models import PushSubscription, User
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.config import get_settings
from manabi_server.db import get_db
from manabi_server.security import get_default_user, require_csrf
from manabi_server.services.push import send_to_all

router = APIRouter(prefix="/api/push", tags=["push"])


class SubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class SubscriptionIn(BaseModel):
    endpoint: str
    keys: SubscriptionKeys


class UnsubscribeIn(BaseModel):
    endpoint: str


@router.get("/vapid-public-key")
async def vapid_public_key() -> dict:
    key = get_settings().vapid_public_key
    if not key:
        raise HTTPException(
            status_code=409,
            detail="Push is not configured — set VAPID_PUBLIC_KEY and "
            "VAPID_PRIVATE_KEY in .env (generate with: uv run vapid --gen)",
        )
    return {"key": key}


@router.post("/subscribe", dependencies=[Depends(require_csrf)])
async def subscribe(
    data: SubscriptionIn,
    user_agent: str | None = Header(default=None),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    existing = (
        await db.execute(
            select(PushSubscription).where(PushSubscription.endpoint == data.endpoint)
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.p256dh = data.keys.p256dh
        existing.auth = data.keys.auth
    else:
        db.add(
            PushSubscription(
                user_id=user.id,
                endpoint=data.endpoint,
                p256dh=data.keys.p256dh,
                auth=data.keys.auth,
                user_agent=(user_agent or "")[:255] or None,
            )
        )
    await db.commit()
    return {"ok": True}


@router.delete("/subscribe", dependencies=[Depends(require_csrf)])
async def unsubscribe(data: UnsubscribeIn, db: AsyncSession = Depends(get_db)) -> dict:
    existing = (
        await db.execute(
            select(PushSubscription).where(PushSubscription.endpoint == data.endpoint)
        )
    ).scalar_one_or_none()
    if existing is not None:
        await db.delete(existing)
        await db.commit()
    return {"ok": True}


@router.post("/test", dependencies=[Depends(require_csrf)])
async def test_push(db: AsyncSession = Depends(get_db)) -> dict:
    delivered = await send_to_all(
        db,
        {
            "title": "Manabi",
            "body": "Notifications are working.",
            "tag": "manabi-test",
            "url": "/tasks",
        },
    )
    return {"delivered": delivered}
