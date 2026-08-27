"""Ollama access for the GPU worker — streamed structured output with
re-asks, keep_alive so the model stays resident between queued jobs."""

import contextlib
import json
import logging
import time
from collections.abc import Awaitable, Callable

import httpx

from manabi_ai.config import get_settings

log = logging.getLogger("manabi_ai")

GENERATION_TIMEOUT = 1800  # generous: cold model load + long context
KEEP_ALIVE = "30m"  # survive the summary→cards→quiz job sequence
PREVIEW_INTERVAL = 0.7  # seconds between preview flushes (drives the live type-out)

# Ollama defaults num_ctx to 4096 regardless of the model's trained window, so a
# large prompt (e.g. "Ask about pages 1-10" = ~12k tokens) is silently truncated
# and the model never sees the question/material. Size the context to the prompt.
_CTX_TIERS = (4096, 8192, 16384, 24576)
_RESPONSE_HEADROOM = 1024  # tokens reserved for the model's own answer
_CHARS_PER_TOKEN = 3.5  # English/JSON runs ~3.3–3.8; 4 undersized → silent truncation


def _num_ctx(
    system: str, user: str, cap: int, headroom: int = _RESPONSE_HEADROOM
) -> int:
    """Smallest context tier that holds prompt + a response, clamped to `cap`.
    Keeps ordinary chats at 4096 (fast) and only grows for big page-range /
    whole-doc asks. The chars/token estimate is deliberately conservative (3.5,
    not 4): overestimating costs a little VRAM; underestimating silently drops
    the tail of the prompt (the question or the last material).

    `headroom` = tokens reserved for the model's own answer. The 1024 default
    fits chat-length replies; multi-item generation (a quiz's worth of
    step-by-step explanations easily runs 3-6k tokens) must pass more, or the
    window fills mid-answer and the JSON stream is cut off mid-string."""
    need = int((len(system) + len(user)) / _CHARS_PER_TOKEN) + headroom
    for tier in _CTX_TIERS:
        if tier >= need:
            return min(tier, cap)
    return min(_CTX_TIERS[-1], cap)

# Connection-level failures that mean the primary node is DOWN/unreachable — the
# signal to fail over to the local backup. Deliberately excludes ReadTimeout:
# a slow (but reachable) generation should wait, not trigger failover.
_NODE_DOWN = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadError,
    httpx.RemoteProtocolError,
    httpx.PoolTimeout,
)

PreviewWriter = Callable[[str], Awaitable[None]]


class GenerationError(Exception):
    pass


# Model families whose chain-of-thought CANNOT be turned off — sending
# think=false makes them return EMPTY content instead of erroring.
_REASONING_LOCKED_PREFIXES = ("gpt-oss",)


def _initial_think(model: str) -> bool | None:
    """think=False for structured generation: thinking models (qwen3.5) under
    a format grammar otherwise spend the whole budget in message.thinking and
    emit zero content. None (= omit the field) for reasoning-locked families."""
    name = model.rsplit("/", 1)[-1]
    return None if name.startswith(_REASONING_LOCKED_PREFIXES) else False


async def generate_structured(
    system: str,
    user: str,
    schema: dict,
    on_preview: PreviewWriter | None = None,
    model: str | None = None,
    response_headroom: int = _RESPONSE_HEADROOM,
) -> dict:
    """JSON-schema-constrained generation, streamed. `on_preview` receives the
    accumulated output text (throttled) so users can watch generation live.
    2 re-asks on invalid output. `model` overrides the default (e.g. the
    faster chat model for interactive tasks)."""
    settings = get_settings()
    think = _initial_think(model or settings.generation_model)
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            content = await _stream_chat(
                settings,
                system,
                user,
                schema,
                on_preview,
                model,
                think=think,
                headroom=response_headroom,
            )
            if not content.strip():
                # Thinking-mode mismatch: a reasoning-locked model sent
                # think=false returns nothing, and a thinking model without it
                # can burn the whole budget reasoning. Flip and re-ask.
                last_error = ValueError("empty response")
                log.warning(
                    "empty structured output (attempt %d, think=%s) — flipping "
                    "think mode",
                    attempt + 1,
                    think,
                )
                think = None if think is False else False
                continue
            return json.loads(content)
        except (json.JSONDecodeError, KeyError) as exc:
            last_error = exc
            log.warning("invalid structured output (attempt %d): %s", attempt + 1, exc)
        except httpx.HTTPStatusError as exc:
            if think is not None and exc.response.status_code == 400:
                # Most likely the think field rejected (a plain instruct
                # model) — drop it and re-ask.
                last_error = exc
                think = None
                continue
            body = ""
            with contextlib.suppress(Exception):
                body = exc.response.text[:200]
            raise GenerationError(
                f"Ollama error {exc.response.status_code}: {body}"
            ) from exc
        except _NODE_DOWN as exc:
            # Primary down AND no (working) backup — nothing left to try.
            raise GenerationError(
                f"AI node unreachable: {exc.__class__.__name__}. "
                "Primary Ollama is offline and no local backup is configured "
                "(set OLLAMA_BACKUP_URL + OLLAMA_BACKUP_MODEL)."
            ) from exc
    raise GenerationError(f"Model produced invalid JSON after 3 attempts: {last_error}")


async def _stream_chat(
    settings,
    system: str,
    user: str,
    schema: dict,
    on_preview: PreviewWriter | None,
    model: str | None = None,
    think: bool | None = None,
    headroom: int = _RESPONSE_HEADROOM,
) -> str:
    """Try the primary node; on a connection-level failure fall back to the
    local backup Ollama (small model that fits this laptop's 8 GB GPU)."""
    try:
        return await _stream_once(
            settings.ollama_url,
            model or settings.generation_model,
            system,
            user,
            schema,
            on_preview,
            think=think,
            headroom=headroom,
        )
    except _NODE_DOWN as exc:
        if not settings.backup_enabled:
            raise
        log.warning(
            "primary Ollama (%s) unreachable (%s) — failing over to local backup "
            "%s / %s",
            settings.ollama_url,
            exc.__class__.__name__,
            settings.ollama_backup_url,
            settings.ollama_backup_model,
        )
        # The backup only has ollama_backup_model pulled, so ignore the
        # requested (phillmyeol-only) model name. The backup is a plain
        # instruct model — never send a think field to it.
        return await _stream_once(
            settings.ollama_backup_url,
            settings.ollama_backup_model,
            system,
            user,
            schema,
            on_preview,
            headroom=headroom,
        )


async def _stream_once(
    url: str,
    model: str,
    system: str,
    user: str,
    schema: dict,
    on_preview: PreviewWriter | None,
    think: bool | None = None,
    headroom: int = _RESPONSE_HEADROOM,
) -> str:
    accumulated: list[str] = []
    last_flush = 0.0
    num_ctx = _num_ctx(system, user, get_settings().max_num_ctx, headroom=headroom)
    payload: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": True,
        "format": schema,
        "keep_alive": KEEP_ALIVE,
        "options": {"temperature": 0.3, "num_ctx": num_ctx},
    }
    if think is not None:
        payload["think"] = think
    async with (
        httpx.AsyncClient(timeout=GENERATION_TIMEOUT) as client,
        client.stream(
            "POST",
            f"{url}/api/chat",
            json=payload,
        ) as response,
    ):
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.strip():
                continue
            piece = json.loads(line)
            accumulated.append(piece.get("message", {}).get("content", ""))
            now = time.monotonic()
            if on_preview and now - last_flush > PREVIEW_INTERVAL:
                last_flush = now
                # preview is best-effort — never let it break generation
                with contextlib.suppress(Exception):
                    await on_preview("".join(accumulated))
            if piece.get("done"):
                break
    return "".join(accumulated)
