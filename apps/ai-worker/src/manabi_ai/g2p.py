"""What the voice will actually say: runs g2p_probe.py under GPT-SoVITS's
own python (its text front end can't be imported into the worker's env)."""

import asyncio
import json
import logging
import os
from pathlib import Path

from manabi_ai.config import get_settings

log = logging.getLogger("manabi_ai.g2p")

PROBE = Path(__file__).with_name("g2p_probe.py")
TIMEOUT_S = 120


def _available(python: str, root: str) -> bool:
    return os.path.exists(python) and os.path.isdir(root)


async def probe(texts: list[str]) -> dict[str, dict] | None:
    """{text: {"phones": [...], "known": bool}}, or None when the voice's
    environment is not on this machine (callers then skip verification)."""
    settings = get_settings()
    texts = list(dict.fromkeys(t for t in texts if t))
    if not texts:
        return {}
    if not _available(settings.tts_g2p_python, settings.tts_g2p_root):
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            settings.tts_g2p_python,
            str(PROBE),
            cwd=settings.tts_g2p_root,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        out, _ = await asyncio.wait_for(
            proc.communicate(json.dumps(texts).encode()), timeout=TIMEOUT_S
        )
        lines = [ln for ln in out.decode("utf-8", "replace").splitlines() if ln.startswith("{")]
        return json.loads(lines[-1]) if lines else None
    except (OSError, TimeoutError, ValueError) as exc:
        log.warning("g2p probe unavailable: %s", exc)
        return None
