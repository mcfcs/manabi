from functools import lru_cache

from manabi_core.settings import CoreSettings


class WorkerSettings(CoreSettings):
    """On phillmyeol, DATABASE_URL points at the app server over Tailscale
    (MagicDNS name), using the minimal-grant manabi_gpu role."""

    ollama_url: str = "http://127.0.0.1:11434"
    generation_model: str = "qwen3.5:27b"
    worker_name: str = "phillmyeol"
    heartbeat_interval_seconds: int = 15


@lru_cache
def get_settings() -> WorkerSettings:
    return WorkerSettings()
