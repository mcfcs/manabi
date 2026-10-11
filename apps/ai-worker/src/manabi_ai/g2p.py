"""What the voice will actually say: runs g2p_probe.py under GPT-SoVITS's
own python (its text front end can't be imported into the worker's env)."""

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path

from manabi_ai.config import get_settings

log = logging.getLogger("manabi_ai.g2p")

PROBE = Path(__file__).with_name("g2p_probe.py")
TIMEOUT_S = 120


def _available(python: str, root: str) -> bool:
    return os.path.exists(python) and os.path.isdir(root)


def _run(python: str, root: str, texts: list[str]) -> dict[str, dict] | None:
    out = subprocess.run(
        [python, str(PROBE)],
        cwd=root,
        input=json.dumps(texts).encode(),
        capture_output=True,
        timeout=TIMEOUT_S,
        env={**os.environ, "PYTHONUTF8": "1"},
        check=False,
    )
    lines = [ln for ln in out.stdout.decode("utf-8", "replace").splitlines() if ln.startswith("{")]
    return json.loads(lines[-1]) if lines else None


async def probe(texts: list[str]) -> dict[str, dict] | None:
    """{text: {"phones": [...], "known": bool}}, or None when the voice's
    environment is not on this machine (callers then skip verification).

    A plain subprocess in a thread, not asyncio's: the worker runs a selector
    event loop on Windows (psycopg needs it), which has no subprocess support —
    create_subprocess_exec raised NotImplementedError and failed a recording."""
    settings = get_settings()
    texts = list(dict.fromkeys(t for t in texts if t))
    if not texts:
        return {}
    if not _available(settings.tts_g2p_python, settings.tts_g2p_root):
        return None
    try:
        return await asyncio.to_thread(_run, settings.tts_g2p_python, settings.tts_g2p_root, texts)
    except Exception as exc:  # noqa: BLE001 — verification is optional, never fatal
        log.warning("g2p probe unavailable: %s", exc)
        return None
