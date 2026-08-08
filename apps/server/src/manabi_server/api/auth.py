from fastapi import APIRouter, Depends, HTTPException, Request, Response
from manabi_core.models import User
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.db import get_db
from manabi_server.security import (
    create_session,
    destroy_session,
    get_current_user,
    hash_password,
    require_csrf,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: str


@router.get("/setup-required")
async def setup_required(db: AsyncSession = Depends(get_db)) -> dict:
    count = (await db.execute(select(func.count(User.id)))).scalar_one()
    return {"setup_required": count == 0}


@router.post("/register", dependencies=[Depends(require_csrf)])
async def register(
    creds: Credentials, response: Response, db: AsyncSession = Depends(get_db)
) -> UserOut:
    """First-run account creation — only allowed while no user exists."""
    count = (await db.execute(select(func.count(User.id)))).scalar_one()
    if count > 0:
        raise HTTPException(status_code=403, detail="Account already exists")
    if len(creds.password) < 10:
        raise HTTPException(status_code=422, detail="Password must be at least 10 characters")
    user = User(email=creds.email, password_hash=hash_password(creds.password))
    db.add(user)
    await db.flush()
    await create_session(db, user.id, response)
    return UserOut(id=user.id, email=user.email)


@router.post("/login", dependencies=[Depends(require_csrf)])
async def login(
    creds: Credentials, response: Response, db: AsyncSession = Depends(get_db)
) -> UserOut:
    user = (
        await db.execute(select(User).where(User.email == creds.email))
    ).scalar_one_or_none()
    if user is None or not verify_password(user.password_hash, creds.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    await create_session(db, user.id, response)
    return UserOut(id=user.id, email=user.email)


@router.post("/logout", dependencies=[Depends(require_csrf)])
async def logout(
    request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> dict:
    await destroy_session(db, request, response)
    return {"ok": True}


@router.get("/me")
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(id=user.id, email=user.email)
