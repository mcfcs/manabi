from functools import lru_cache

from manabi_core.settings import CoreSettings


class Settings(CoreSettings):
    secret_key: str = "dev-only-change-me"
    file_storage_root: str = "./storage"
    web_dist: str = "./apps/web/dist"  # built SPA served by FastAPI
    soffice_path: str = r"C:\Program Files\LibreOffice\program\soffice.exe"
    app_origin: str = "http://localhost:5173"
    # Extra origins accepted by the CSRF Origin check (dev servers etc.)
    extra_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    cookie_secure: bool = False  # set true in production (HTTPS via Caddy)
    session_ttl_days: int = 30
    # Heartbeat older than this ⇒ AI node considered offline
    ai_heartbeat_stale_seconds: int = 45


@lru_cache
def get_settings() -> Settings:
    return Settings()
