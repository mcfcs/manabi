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
    # Voice-lab A/B: weight sets for "base" (pretrained zero-shot) and
    # "tuned" (fine-tuned). Paths are relative to the TTS server's cwd.
    tts_base_gpt: str = (
        "GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/"
        "s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt"
    )
    tts_base_sovits: str = (
        "GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s2G2333k.pth"
    )
    tts_tuned_gpt: str = ""  # e.g. GPT_weights_v2/steven-e15.ckpt
    tts_tuned_sovits: str = ""  # e.g. SoVITS_weights_v2/steven_e8_s264.pth

    @property
    def effective_chat_model(self) -> str:
        return self.chat_model or self.generation_model

    @property
    def tts_enabled(self) -> bool:
        return bool(self.tts_url and self.tts_ref_audio)


@lru_cache
def get_settings() -> WorkerSettings:
    return WorkerSettings()
