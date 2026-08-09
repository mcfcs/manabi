"""Web Push sender. pywebpush is sync (requests) → run in a thread."""

import asyncio
import json
import logging

from manabi_core.models import PushSubscription
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.config import get_settings
from manabi_server.timeutil import now_manila

log = logging.getLogger("manabi.push")


def _send_one(sub: PushSubscription, payload: str) -> str | None:
    """Returns None on success, 'gone' when the subscription is dead,
    or an error string."""
    from pywebpush import WebPushException, webpush

    settings = get_settings()
    try:
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=payload,
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_sub},
        )
        return None
    except WebPushException as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status in (404, 410):
            return "gone"
        return f"{status}: {exc}"


async def send_to_all(db: AsyncSession, payload: dict) -> int:
    """Send to every subscription; prune dead ones. Returns delivered count."""
    settings = get_settings()
    if not (settings.vapid_public_key and settings.vapid_private_key):
        return 0
    subs = (await db.execute(select(PushSubscription))).scalars().all()
    body = json.dumps(payload)
    delivered = 0
    for sub in subs:
        result = await asyncio.to_thread(_send_one, sub, body)
        if result is None:
            sub.last_success_at = now_manila()
            delivered += 1
        elif result == "gone":
            log.info("pruning dead push subscription %s", sub.id)
            await db.delete(sub)
        else:
            log.warning("push to %s failed: %s", sub.id, result)
    await db.commit()
    return delivered
