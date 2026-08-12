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
PREVIEW_INTERVAL = 1.5  # seconds between preview flushes

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


async def generate_structured(
    system: str,
    user: str,
    schema: dict,
    on_preview: PreviewWriter | None = None,
    model: str | None = None,
) -> dict:
    """JSON-schema-constrained generation, streamed. `on_preview` receives the
    accumulated output text (throttled) so users can watch generation live.
    2 re-asks on invalid output. `model` overrides the default (e.g. the
    faster chat model for interactive tasks)."""
    settings = get_settings()
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            content = await _stream_chat(
                settings, system, user, schema, on_preview, model
            )
            return json.loads(content)
        except (json.JSONDecodeError, KeyError) as exc:
            last_error = exc
            log.warning("invalid structured output (attempt %d): %s", attempt + 1, exc)
        except httpx.HTTPStatusError as exc:
            raise GenerationError(
                f"Ollama error {exc.response.status_code}: {exc.response.text[:200]}"
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
        # requested (phillmyeol-only) model name.
        return await _stream_once(
            settings.ollama_backup_url,
            settings.ollama_backup_model,
            system,
            user,
            schema,
            on_preview,
        )


async def _stream_once(
    url: str,
    model: str,
    system: str,
    user: str,
    schema: dict,
    on_preview: PreviewWriter | None,
) -> str:
    accumulated: list[str] = []
    last_flush = 0.0
    async with (
        httpx.AsyncClient(timeout=GENERATION_TIMEOUT) as client,
        client.stream(
            "POST",
            f"{url}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": True,
                "format": schema,
                "keep_alive": KEEP_ALIVE,
                "options": {"temperature": 0.3},
            },
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
