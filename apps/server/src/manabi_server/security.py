"""Single-user mode: no login. Access control is the Tailscale boundary —
only devices on the tailnet can reach the server at all.

Kept defenses: a CSRF check (custom header + same-origin) so a malicious
website open in a browser on the tailnet can't fire mutating requests, and
the default-user row so every record still carries a user_id (multi-user
later stays a schema no-op).
"""

from fastapi import Depends, HTTPException, Request
from manabi_core.models import User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.config import get_settings
from manabi_server.db import get_db

DEFAULT_USER_EMAIL = "gio@manabi.local"


async def get_default_user(db: AsyncSession = Depends(get_db)) -> User:
    """Return the single user, creating it on first request."""
    user = (
        await db.execute(select(User).order_by(User.id).limit(1))
    ).scalar_one_or_none()
    if user is None:
        user = User(email=DEFAULT_USER_EMAIL, password_hash="")
        db.add(user)
        await db.commit()
    return user


def require_csrf(request: Request) -> None:
    """CSRF defense for a fetch-based SPA: custom header + same-origin check.

    Cross-site HTML forms cannot set X-Requested-With, and cross-site fetch
    with it triggers CORS preflight (which we never allow).
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if request.headers.get("x-requested-with") != "fetch":
        raise HTTPException(status_code=403, detail="Missing CSRF header")
    origin = request.headers.get("origin")
    if origin is not None:
        # Same-origin (works for any tailnet hostname/IP) or explicit allowlist
        origin_host = origin.split("://", 1)[-1]
        request_host = request.headers.get("host", "")
        if origin_host != request_host:
            settings = get_settings()
            if origin not in {settings.app_origin, *settings.extra_origins}:
                raise HTTPException(status_code=403, detail="Bad origin")
