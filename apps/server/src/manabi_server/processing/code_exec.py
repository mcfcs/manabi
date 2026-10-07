"""Run the code in a quiz question and see what it actually prints.

An `output` question asks what a program produces. There is no reason to ask a
model that when the program can simply be run — and models are specifically bad
at it. A real case: given `char *sentence = "the quick brown fox"` and
`ptrs[0] = sentence + 5`, qwen3.5:27b wrote "pointing to index 5 ('u')" and then
answered "quick brown fox", which is the substring from index 4. It did not
miscount; it snapped to a whole word because that looks like a nicer answer.
Compiling the same code answers "uick brown fox" every time.

C, C++ and Python run. C/C++ are compiled twice — at -O0 and -O2 — and both
binaries must print the same thing, and the compiler's undefined-behaviour
warnings are read: `y = --x + (x--)` "verifies" against whatever one build
happens to print, which is exactly how a question with no right answer got a
definite key. Undefined behaviour is reported as such, never as ground truth.

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
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("manabi.code_exec")

COMPILE_TIMEOUT = 30  # seconds
RUN_TIMEOUT = 5
MAX_OUTPUT = 8000  # characters kept from stdout

_FENCE = re.compile(r"```([A-Za-z0-9_+#-]*)[ \t]*\n(.*?)```", re.DOTALL)

# Language tags we can actually execute. Anything else is left to the model.
_C = {"c", "h"}
_CPP = {"cpp", "c++", "cc", "cxx", "hpp"}
_PY = {"py", "python", "python3"}

# Models label C++ as ```c often enough that the tag cannot be trusted: a
# `cout` in a "c" block would simply fail to compile and go unverified.
_CPP_MARKERS = re.compile(
    r"#include\s*<(?:iostream|string|vector|map|set|memory|iomanip|sstream|"
    r"algorithm|list|queue|stack|utility|fstream)>"
    r"|\bstd::|\bcout\b|\bcin\b|\bendl\b|\bclass\s+\w+|\bnamespace\b"
    r"|\btemplate\s*<|\bvirtual\b|\bpublic\s*:|\bprivate\s*:|\bprotected\s*:"
    r"|\bnullptr\b|::"
)
_C_MARKERS = re.compile(r"#include\s*<|\bprintf\s*\(|\bint\s+main\s*\(|\bputs\s*\(|\bputchar\s*\(")

# Compiler diagnostics that mean the program's output is not defined by the
# language, so whatever it prints is not an answer key.
_UB_WARNINGS = re.compile(
    r"may be undefined"  # -Wsequence-point: i = i++ + ++i
    r"|unsequenced modification"
    r"|is used uninitialized|may be used uninitialized"
    r"|array subscript .{0,60}(?:outside|above|below) array bounds"
    r"|invokes undefined behavior"
    r"|returns? (?:the )?address of (?:a )?local"
    r"|reference to local variable .{0,40} returned"
    r"|division by zero"
    r"|too few arguments for format"
    r"|-Wsequence-point|-Wuninitialized|-Warray-bounds|-Waggressive-loop-optimizations",
    re.I,
)

# Results that depend on the platform's data model. The machine running the
# checks is Windows (LLP64: long is 4 bytes) while course material assumes the
# usual Linux LP64 (long is 8) — such a run would "correct" a right answer.
_PLATFORM_DEPENDENT = re.compile(
    r"sizeof\s*\(\s*(?:unsigned\s+)?long\s*\)|sizeof\s*\(\s*long\s+double"
)


@dataclass(frozen=True)
class Snippet:
    lang: str  # normalized: "c" | "cpp" | "python"
    source: str


@dataclass(frozen=True)
class ExecResult:
    ok: bool
    stdout: str
    error: str | None = None
    # Set when the program has no defined output: a compiler UB warning, or
    # the -O0 and -O2 builds disagreeing. `ok` is False whenever this is set.
    undefined: str | None = None


def guess_lang(source: str) -> str | None:
    """C, C++ or nothing, from the code itself."""
    if _CPP_MARKERS.search(source):
        return "cpp"
    if _C_MARKERS.search(source):
        return "c"
    return None


def extract_snippet(prompt: str) -> Snippet | None:
    """The first fenced block we know how to run. Questions carry exactly one."""
    for m in _FENCE.finditer(prompt or ""):
        tag = (m.group(1) or "").strip().lower()
        source = m.group(2)
        if not source.strip():
            continue
        if tag in _PY:
            return Snippet("python", source)
        if tag in _C or tag in _CPP:
            # Trust the code over the tag: C++ is routinely fenced as ```c.
            lang = "cpp" if (tag in _CPP or _CPP_MARKERS.search(source)) else "c"
            return Snippet(lang, source)
        if tag == "":
            guessed = guess_lang(source)
            if guessed:
                return Snippet(guessed, source)
    return None


def _wrap(lang: str, source: str) -> str:
    """Questions sometimes quote a fragment, not a program — no includes, no
    main. Wrap it so it compiles, unless it already brings its own main."""
    if re.search(r"\bmain\s*\(", source):
        if lang == "c" and not re.search(r"#include\s*<stdio\.h>", source):
            # A complete program that forgot its include is still a program.
            return "#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n" + source
        return source
    body = source.strip()
    if not body.endswith(";") and not body.endswith("}"):
        body += ";"
    if lang == "cpp":
        return (
            "#include <iostream>\n#include <string>\n#include <cstring>\n"
            "#include <cstdio>\nusing namespace std;\n"
            "int main() {\n" + body + "\nreturn 0;\n}\n"
        )
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


def cpp_compiler() -> str | None:
    for name in ("g++", "clang++", "c++"):
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


def _compile_and_run_native(snippet: Snippet, cwd: Path) -> ExecResult:
    is_cpp = snippet.lang == "cpp"
    cc = cpp_compiler() if is_cpp else c_compiler()
    if cc is None:
        return ExecResult(False, "", f"no {'C++' if is_cpp else 'C'} compiler on this machine")
    src = cwd / ("main.cpp" if is_cpp else "main.c")
    src.write_text(_wrap(snippet.lang, snippet.source), encoding="utf-8")
    std = ["-std=c++17"] if is_cpp else ["-std=gnu11"]
    outputs: list[str] = []
    for opt in ("-O0", "-O2"):
        exe = cwd / (f"main{opt}.exe" if sys.platform == "win32" else f"main{opt}")
        code, _, err = _run(
            [cc, str(src), "-o", str(exe), opt, *std, "-Wall", "-Wextra", "-Wno-unused"],
            cwd,
            COMPILE_TIMEOUT,
        )
        if code != 0:
            return ExecResult(False, "", f"compile failed: {err.strip()[:300]}")
        ub = _UB_WARNINGS.search(err or "")
        if ub:
            line = next(
                (ln for ln in err.splitlines() if _UB_WARNINGS.search(ln)), ub.group(0)
            )
            reason = f"undefined behaviour: {line.strip()[:200]}"
            return ExecResult(False, "", reason, undefined=reason)
        run_code, out, run_err = _run([str(exe)], cwd, RUN_TIMEOUT)
        if run_code != 0:
            return ExecResult(
                False, out[:MAX_OUTPUT], f"exit {run_code}: {run_err.strip()[:300]}"
            )
        outputs.append(out)
    if normalize_output(outputs[0]) != normalize_output(outputs[1]):
        reason = "undefined behaviour: the -O0 and -O2 builds print different things"
        return ExecResult(False, outputs[0][:MAX_OUTPUT], reason, undefined=reason)
    if is_cpp and re.search(r"\w+\s*\(\s*const\s+\w+\s*&", snippet.source):
        # A class with a copy constructor: whether it runs on `return local;`
        # is the compiler's choice (NRVO), so "Init Copy End" and "Init End"
        # are both right. A real generated key assumed the copy; g++ elides it.
        exe = cwd / ("main-noelide.exe" if sys.platform == "win32" else "main-noelide")
        code, _, err = _run(
            [cc, str(src), "-o", str(exe), "-O0", *std, "-fno-elide-constructors", "-w"],
            cwd,
            COMPILE_TIMEOUT,
        )
        if code == 0:
            run_code, out, _ = _run([str(exe)], cwd, RUN_TIMEOUT)
            if run_code == 0 and normalize_output(out) != normalize_output(outputs[0]):
                reason = (
                    "no single correct output: it depends on copy elision "
                    "(whether the copy constructor runs is the compiler's choice)"
                )
                return ExecResult(False, outputs[0][:MAX_OUTPUT], reason, undefined=reason)
    return ExecResult(True, outputs[0][:MAX_OUTPUT])


def execute(snippet: Snippet) -> ExecResult:
    """Compile (if needed) and run, returning what it printed to stdout."""
    if snippet.lang in ("c", "cpp") and _PLATFORM_DEPENDENT.search(snippet.source):
        return ExecResult(False, "", "platform-dependent (sizeof long differs on this machine)")
    try:
        with tempfile.TemporaryDirectory(prefix="manabi-exec-") as tmp:
            cwd = Path(tmp)
            if snippet.lang in ("c", "cpp"):
                return _compile_and_run_native(snippet, cwd)
            src = cwd / "main.py"
            src.write_text(snippet.source, encoding="utf-8")
            # -I: isolated — ignore env vars and the user's site-packages.
            cmd = [sys.executable, "-I", str(src)]
            # Run twice and require agreement. Code that prints an address, a
            # random number or the time would otherwise "verify" against
            # whatever it happened to print first.
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

    Whitespace counts: a program printing a single space printed something (a
    real question's correct answer was " "), only bare newlines do not.
    """
    if not result.ok:
        return False
    return (result.stdout or "").replace("\r", "").replace("\n", "") != ""


# ── Checking a whole question ────────────────────────────────────────────

# A stem asking about printed output, as opposed to "what is stored in x".
_ASKS_OUTPUT = re.compile(
    r"\b(?:outputs?|print(?:s|ed)?|display(?:s|ed)?|cout|printf|console|screen|shown)\b",
    re.I,
)
_WHICH_OF = re.compile(
    r"\bwhich of the following (?:is|would be|will be|best describes|correctly shows)"
    r"(?: the)?(?: exact| correct)?\s+",
    re.I,
)


@dataclass
class CodeCheck:
    """What running a question's code says about its answer key.

    status:
      skip         nothing to check (no code, or not an output question)
      agree        the key matches what the program prints
      corrected    the key was wrong and `answer` is the corrected one
      converted    an mcq whose options never match the real output — it is
                   now an `output` question (`qtype`, `answer`, options None)
      rejected     the program has no defined output; the question must go
      unverifiable the code exists but could not be run (`reason` says why)
    """

    status: str
    reason: str = ""
    real: str | None = None
    qtype: str | None = None
    answer: dict | None = None
    options: list | None = field(default=None)


def _clean_option(text: str) -> str:
    t = (text or "").strip()
    # Options are often quoted or code-formatted: `10 20`, "Hello", 'A'.
    for _ in range(2):
        if len(t) >= 2 and t[0] == t[-1] and t[0] in "`\"'":
            t = t[1:-1]
    t = re.sub(r"^```[A-Za-z]*\n?|```$", "", t).strip("\n")
    # A literal "\n" written into an option means a line break.
    return t.replace("\\n", "\n").replace("\\t", "\t")


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_output(text)).strip()


def match_options(options: list, stdout: str) -> list[int]:
    """Indexes of the options that equal what the program printed — exact
    (normalized) matches first; whitespace-insensitive ones only if no option
    matches exactly, since "1 2 3" and "1\\n2\\n3" are the same to a reader."""
    exact = [
        i for i, o in enumerate(options) if outputs_match(_clean_option(str(o)), stdout)
    ]
    if exact:
        return exact
    real = _collapse(stdout)
    return [i for i, o in enumerate(options) if _collapse(_clean_option(str(o))) == real]


def check_code_question(
    qtype: str, prompt: str, options: list | None, answer: dict | None
) -> CodeCheck:
    """Run a question's code and reconcile its answer key with the result.

    Pure apart from `execute`. Only a successful, defined run overrules the
    model; code that will not compile is left as written.
    """
    answer = dict(answer or {})
    if qtype not in ("output", "mcq", "short"):
        return CodeCheck("skip")
    snippet = extract_snippet(prompt or "")
    if snippet is None:
        if qtype == "output":
            return CodeCheck("unverifiable", "no runnable code block")
        return CodeCheck("skip")
    if qtype != "output" and not _ASKS_OUTPUT.search(_FENCE.sub(" ", prompt or "")):
        return CodeCheck("skip")  # e.g. "what value does x hold" — not stdout

    result = execute(snippet)
    if result.undefined:
        return CodeCheck("rejected", result.undefined)
    if not result.ok:
        return CodeCheck("unverifiable", result.error or "could not run")
    if not printed_anything(result):
        return CodeCheck("unverifiable" if qtype == "output" else "skip", "program prints nothing")

    real = normalize_output(result.stdout)
    if qtype in ("output", "short"):
        if outputs_match(answer.get("text", ""), result.stdout):
            return CodeCheck("agree", real=real, answer={**answer, "verified": "executed"})
        return CodeCheck(
            "corrected",
            "the program prints something else",
            real=real,
            answer={"kind": qtype, "text": real, "verified": "executed"},
        )

    # mcq: the key must point at the option the program actually prints.
    opts = list(options or [])
    hits = match_options(opts, result.stdout)
    if len(hits) == 1:
        if answer.get("correct_option") == hits[0]:
            return CodeCheck("agree", real=real, answer={**answer, "verified": "executed"})
        return CodeCheck(
            "corrected",
            f"option {hits[0]} is what the program prints",
            real=real,
            answer={"kind": "mcq", "correct_option": hits[0], "verified": "executed"},
        )
    # No option (or several identical ones) shows the real output: the choices
    # are broken, but the code and the stem are fine — ask for the output.
    return CodeCheck(
        "converted",
        "no single option matches the real output",
        real=real,
        qtype="output",
        answer={"kind": "output", "text": real, "verified": "executed"},
        options=None,
    )


def converted_prompt(prompt: str) -> str:
    """Re-word an mcq stem whose options were dropped ("Which of the following
    is the output…" → "What is the exact output…")."""
    return _WHICH_OF.sub("What is the exact ", prompt or "", count=1)
