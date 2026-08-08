import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response
from manabi_core.models import Session as DbSession
from manabi_core.models import User
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.config import get_settings
from manabi_server.db import get_db

SESSION_COOKIE = "manabi_session"

_hasher = PasswordHasher()  # argon2id defaults


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(db: AsyncSession, user_id: int, response: Response) -> None:
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    db.add(
        DbSession(
            token_hash=_token_hash(token),
            user_id=user_id,
            expires_at=datetime.now(UTC) + timedelta(days=settings.session_ttl_days),
        )
    )
    await db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


async def destroy_session(db: AsyncSession, request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await db.execute(delete(DbSession).where(DbSession.token_hash == _token_hash(token)))
        await db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    row = (
        await db.execute(
            select(DbSession, User)
            .join(User, User.id == DbSession.user_id)
            .where(DbSession.token_hash == _token_hash(token))
        )
    ).first()
    if row is None or row.Session.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=401, detail="Session expired")
    return row.User


def require_csrf(request: Request) -> None:
    """CSRF defense for a fetch-based SPA: custom header + Origin check.

    Cross-site HTML forms cannot set X-Requested-With, and cross-site fetch
    with it triggers CORS preflight (which we never allow).
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if request.headers.get("x-requested-with") != "fetch":
        raise HTTPException(status_code=403, detail="Missing CSRF header")
    origin = request.headers.get("origin")
    if origin is not None:
        settings = get_settings()
        allowed = {settings.app_origin, *settings.extra_origins}
        if origin not in allowed:
            raise HTTPException(status_code=403, detail="Bad origin")
