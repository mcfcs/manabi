"""Run with GPT-SoVITS's OWN python, from its repo root, not the worker's:

    C:/GPT-SoVITS/.venv/Scripts/python.exe g2p_probe.py < words.json

stdin: a JSON list of strings. stdout (last line): a JSON object
{text: {"phones": [...], "known": bool}} — the phonemes the voice will
actually speak for that text, and whether every word of it is in the voice's
dictionary (CMUdict, its hot list, or its name list for a Title-case word).

It imports nothing from manabi, so it works in that environment as is.
"""

import json
import os
import re
import sys


def main() -> None:
    root = os.getcwd()
    sys.path.insert(0, root)
    sys.path.insert(0, os.path.join(root, "GPT_SoVITS"))
    os.chdir(os.path.join(root, "GPT_SoVITS"))
    from text.english import _g2p, g2p, text_normalize  # noqa: PLC0415

    items = json.loads(sys.stdin.read() or "[]")
    out = {}
    for text in items:
        tokens = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)*", text)
        known = all(
            (len(t) > 1 and t.lower() in _g2p.cmu) or (t.istitle() and t.lower() in _g2p.namedict)
            for t in tokens
        )
        out[text] = {"phones": list(g2p(text_normalize(text))), "known": known}
    print(json.dumps(out))


if __name__ == "__main__":
    main()
