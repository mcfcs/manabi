from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from manabi_ai.config import get_settings

_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def session_factory() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        engine = create_async_engine(get_settings().database_url, pool_size=2)
        _sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    return _sessionmaker
