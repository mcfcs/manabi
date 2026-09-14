"""Run the code in a quiz question and see what it actually prints.

An `output` question asks what a program produces. There is no reason to ask a
model that when the program can simply be run — and models are specifically bad
at it. A real case: given `char *sentence = "the quick brown fox"` and
`ptrs[0] = sentence + 5`, qwen3.5:27b wrote "pointing to index 5 ('u')" and then
answered "quick brown fox", which is the substring from index 4. It did not
miscount; it snapped to a whole word because that looks like a nicer answer.
Compiling the same code answers "uick brown fox" every time.

Safety: this executes code a local model wrote from the owner's own course
materials, so it is not attacker-controlled, but it is unreviewed. Everything
runs in a throwaway temp directory, with no stdin, under a hard timeout, and
the process is killed on expiry.
"""

import logging
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("manabi.code_exec")

COMPILE_TIMEOUT = 20  # seconds
RUN_TIMEOUT = 5
MAX_OUTPUT = 8000  # characters kept from stdout

_FENCE = re.compile(r"```([A-Za-z0-9_+#-]*)\n(.*?)```", re.DOTALL)

# Language tags we can actually execute. Anything else is left to the model.
_C = {"c"}
_PY = {"py", "python", "python3"}


@dataclass(frozen=True)
class Snippet:
    lang: str  # normalized: "c" | "python"
    source: str


@dataclass(frozen=True)
class ExecResult:
    ok: bool
    stdout: str
    error: str | None = None


def extract_snippet(prompt: str) -> Snippet | None:
    """The first fenced block we know how to run. Questions carry exactly one."""
    for m in _FENCE.finditer(prompt or ""):
        tag = (m.group(1) or "").strip().lower()
        source = m.group(2)
        if tag in _C:
            return Snippet("c", source)
        if tag in _PY:
            return Snippet("python", source)
    return None


def _wrap_c(source: str) -> str:
    """Questions quote a fragment, not a program — no includes, no main. Wrap
    it so it compiles, unless it already brings its own main."""
    if re.search(r"\bmain\s*\(", source):
        return source
    body = source.strip()
    if not body.endswith(";") and not body.endswith("}"):
        body += ";"
    return (
        "#include <stdio.h>\n"
        "#include <stdlib.h>\n"
        "#include <string.h>\n"
        "int main(void) {\n" + body + "\nreturn 0;\n}\n"
    )


def c_compiler() -> str | None:
    for name in ("gcc", "clang", "cc"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _run(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str, str]:
    proc = subprocess.run(  # noqa: S603 — argv list, never a shell string
        cmd,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def execute(snippet: Snippet) -> ExecResult:
    """Compile (if needed) and run, returning what it printed to stdout."""
    try:
        with tempfile.TemporaryDirectory(prefix="manabi-exec-") as tmp:
            cwd = Path(tmp)
            if snippet.lang == "c":
                cc = c_compiler()
                if cc is None:
                    return ExecResult(False, "", "no C compiler on this machine")
                src = cwd / "main.c"
                src.write_text(_wrap_c(snippet.source), encoding="utf-8")
                exe = cwd / ("main.exe" if sys.platform == "win32" else "main")
                code, _, err = _run(
                    [cc, str(src), "-o", str(exe), "-w"], cwd, COMPILE_TIMEOUT
                )
                if code != 0:
                    return ExecResult(False, "", f"compile failed: {err.strip()[:300]}")
                cmd = [str(exe)]
            else:
                src = cwd / "main.py"
                src.write_text(snippet.source, encoding="utf-8")
                # -I: isolated — ignore env vars and the user's site-packages.
                cmd = [sys.executable, "-I", str(src)]

            # Run twice and require agreement. Code that prints an address, an
            # uninitialised value, a random number or the time would otherwise
            # "verify" against whatever it happened to print first, and then
            # mark the student wrong on every later attempt.
            code, out, err = _run(cmd, cwd, RUN_TIMEOUT)
            if code != 0:
                return ExecResult(False, out[:MAX_OUTPUT], f"exit {code}: {err.strip()[:300]}")
            code2, out2, _ = _run(cmd, cwd, RUN_TIMEOUT)
            if code2 != 0 or normalize_output(out) != normalize_output(out2):
                return ExecResult(False, out[:MAX_OUTPUT], "output is not deterministic")
            return ExecResult(True, out[:MAX_OUTPUT])
    except subprocess.TimeoutExpired:
        return ExecResult(False, "", "timed out")
    except OSError as exc:  # noqa: BLE001 — a broken toolchain must not fail the job
        return ExecResult(False, "", f"could not run: {exc}")


def normalize_output(text: str) -> str:
    """Compare what a program printed against what a model claimed it prints.

    Trailing newlines and line-end whitespace are noise here — a question's
    stored answer rarely reproduces the final "\n" from printf — but interior
    spacing is meaningful and is left alone.
    """
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip("\n")


def outputs_match(expected: str, actual: str) -> bool:
    return normalize_output(expected) == normalize_output(actual)


def printed_anything(result: "ExecResult") -> bool:
    """Did the program actually print something?

    A snippet with no printf at all runs fine and produces "". That is not
    ground truth for "what is the exact output" — it means the question is not
    about printed output. A real generation asked what a string-copy routine
    leaves in `dest`; the model answered "Hi\0", the program printed nothing,
    and treating "" as the truth replaced a sensible answer with an empty one.
    """
    return result.ok and normalize_output(result.stdout) != ""
