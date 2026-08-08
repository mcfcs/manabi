"""Ollama access for the GPU worker — structured output with re-asks."""

import json
import logging

import httpx

from manabi_ai.config import get_settings

log = logging.getLogger("manabi_ai")

GENERATION_TIMEOUT = 1800  # generous: cold model load + long context


class GenerationError(Exception):
    pass


async def generate_structured(system: str, user: str, schema: dict) -> dict:
    """JSON-schema-constrained generation with 2 re-asks on invalid output."""
    settings = get_settings()
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=GENERATION_TIMEOUT) as client:
                r = await client.post(
                    f"{settings.ollama_url}/api/chat",
                    json={
                        "model": settings.generation_model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "stream": False,
                        "format": schema,
                        "options": {"temperature": 0.3},
                    },
                )
                r.raise_for_status()
                content = r.json()["message"]["content"]
                return json.loads(content)
        except (json.JSONDecodeError, KeyError) as exc:
            last_error = exc
            log.warning("invalid structured output (attempt %d): %s", attempt + 1, exc)
        except httpx.HTTPStatusError as exc:
            raise GenerationError(
                f"Ollama error {exc.response.status_code}: {exc.response.text[:200]}"
            ) from exc
    raise GenerationError(f"Model produced invalid JSON after 3 attempts: {last_error}")
