from pydantic_settings import BaseSettings, SettingsConfigDict


class CoreSettings(BaseSettings):
    """Settings shared by the app server and the GPU worker.

    Each machine provides its own .env; the AI node's DATABASE_URL points at
    the app server's Postgres over Tailscale (MagicDNS name, never a raw IP).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://manabi:manabi@localhost:56661/manabi"
    database_url_sync: str = "postgresql+psycopg://manabi:manabi@localhost:56661/manabi"
