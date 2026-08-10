from functools import lru_cache

from manabi_core.settings import CoreSettings


class WorkerSettings(CoreSettings):
    """On phillmyeol, DATABASE_URL points at the app server over Tailscale
    (MagicDNS name), using the minimal-grant manabi_gpu role."""

    ollama_url: str = "http://127.0.0.1:11434"
    generation_model: str = "qwen3.5:27b"
    # Interactive tasks (chat, term lookups) use a smaller, faster model that
    # co-resides with the big one in VRAM. Empty → fall back to generation_model.
    chat_model: str = ""
    worker_name: str = "phillmyeol"
    heartbeat_interval_seconds: int = 15
    # Teacher voice (GPT-SoVITS api_v2 or compatible). Empty tts_url = voice
    # disabled; lectures fall back to reading mode.
    tts_url: str = ""
    tts_voice: str = "steven"
    tts_ref_audio: str = ""  # path (on this machine) to a 3-10s reference wav
    tts_ref_text: str = ""  # exact transcript of the reference clip
    tts_speed: float = 1.0

    @property
    def effective_chat_model(self) -> str:
        return self.chat_model or self.generation_model

    @property
    def tts_enabled(self) -> bool:
        return bool(self.tts_url and self.tts_ref_audio)


@lru_cache
def get_settings() -> WorkerSettings:
    return WorkerSettings()
