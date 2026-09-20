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
    # Failover: when the primary Ollama node (phillmyeol) is unreachable, retry
    # against a local Ollama that fits this laptop's RTX 4070 (8 GB). One small
    # model serves every job here (generation + chat), so the requested model
    # name is ignored on the backup path. Both must be set to arm failover.
    ollama_backup_url: str = ""  # e.g. http://127.0.0.1:11434
    ollama_backup_model: str = ""  # e.g. qwen2.5:7b-instruct (~4.7 GB Q4_K_M)
    # Upper bound on the per-request Ollama context window. Grown from 4096 only
    # as a prompt needs it. 24576 holds whole-doc / big page-range asks without
    # truncation; it stays VRAM-safe on phillmyeol ONLY with KV-cache
    # quantization enabled (OLLAMA_FLASH_ATTENTION=1 + OLLAMA_KV_CACHE_TYPE=q8_0),
    # which ~halves the cache. The 8 GB backup falls back to the low tiers via
    # its own smaller model, so this cap is effectively the phillmyeol ceiling.
    max_num_ctx: int = 24576
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
    #
    # These MUST match the engine version the server is actually running
    # (`custom.version` in GPT_SoVITS/configs/tts_infer.yaml) — currently
    # v2ProPlus. `synthesize_variant("base")` swaps the weights on the shared
    # api_v2 process and restores `tts_tuned_*` afterwards, so a base pair from
    # a different version silently moves the whole server onto that version,
    # and the A/B then compares two engines rather than two training sets.
    # Rolling back to v2 means changing all four of these together.
    tts_base_gpt: str = "GPT_SoVITS/pretrained_models/s1v3.ckpt"
    tts_base_sovits: str = "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth"
    tts_tuned_gpt: str = ""  # e.g. GPT_weights_v2ProPlus/steven4-e4.ckpt
    tts_tuned_sovits: str = ""  # e.g. SoVITS_weights_v2ProPlus/steven4_e8_s8.pth

    @property
    def effective_chat_model(self) -> str:
        return self.chat_model or self.generation_model

    @property
    def backup_enabled(self) -> bool:
        return bool(self.ollama_backup_url and self.ollama_backup_model)

    @property
    def tts_enabled(self) -> bool:
        return bool(self.tts_url and self.tts_ref_audio)


@lru_cache
def get_settings() -> WorkerSettings:
    return WorkerSettings()
