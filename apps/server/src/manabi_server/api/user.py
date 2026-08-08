from fastapi import APIRouter, Depends
from manabi_core.models import User
from pydantic import BaseModel

from manabi_server.security import get_default_user

router = APIRouter(prefix="/api", tags=["user"])


class UserOut(BaseModel):
    id: int
    email: str


@router.get("/me")
async def me(user: User = Depends(get_default_user)) -> UserOut:
    return UserOut(id=user.id, email=user.email)
