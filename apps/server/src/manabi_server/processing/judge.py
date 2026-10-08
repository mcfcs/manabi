"""Judge a program against stdin/stdout tests (HackerRank style).

Compile once (C / C++) or run directly (Python), then feed each test's input
on stdin under a time limit and compare stdout with the expected output after
the same normalisation the output questions use (line-end whitespace and the
final newline don't count; everything else does). Also used to *build* a
problem's expectations: the reference solution is run on every test input and
must be deterministic, quick, and crash-free there before the problem is
offered. Code is the student's own or a local model's, run in a throwaway
temp dir with no network stake and a hard timeout — see code_exec.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from manabi_server.processing.code_exec import (
    COMPILE_TIMEOUT,
    c_compiler,
    cpp_compiler,
    crash_reason,
    normalize_output,
)

MAX_TESTS = 30
MAX_OUTPUT = 20_000
LANGUAGES = ("c", "cpp", "python")


@dataclass
class TestResult:
    index: int
    verdict: str  # passed|wrong|runtime_error|time_limit
    input: str = ""
    expected: str = ""
    got: str = ""
    error: str = ""
    ms: int = 0


@dataclass
class Judgement:
    verdict: str  # accepted|wrong|compile_error|runtime_error|time_limit|no_tests
    passed: int = 0
    total: int = 0
    compile_error: str = ""
    results: list[TestResult] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {**asdict(self), "results": [asdict(r) for r in self.results]}


def _compile(language: str, code: str, cwd: Path) -> tuple[list[str] | None, str]:
    """argv to run the program, or (None, compiler error)."""
    if language == "python":
        src = cwd / "main.py"
        src.write_text(code, encoding="utf-8")
        return [sys.executable, "-I", str(src)], ""
    cc = cpp_compiler() if language == "cpp" else c_compiler()
    if cc is None:
        return None, f"no {'C++' if language == 'cpp' else 'C'} compiler on this machine"
    src = cwd / ("main.cpp" if language == "cpp" else "main.c")
    src.write_text(code, encoding="utf-8")
    exe = cwd / ("main.exe" if sys.platform == "win32" else "main")
    std = "-std=c++17" if language == "cpp" else "-std=gnu11"
    proc = subprocess.run(  # noqa: S603 — argv list
        [cc, str(src), "-o", str(exe), "-O2", std, "-w"],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=COMPILE_TIMEOUT,
    )
    if proc.returncode != 0:
        msg = proc.stderr.replace(str(src), src.name).replace(str(cwd), ".")
        return None, msg.strip()[:4000]
    return [str(exe)], ""


def _run_one(argv: list[str], stdin: str, cwd: Path, limit_ms: int) -> tuple[str, str, str, int]:
    """(verdict-ish, stdout, error, ms) — verdict is ok|runtime_error|time_limit."""
    import time

    start = time.perf_counter()
    try:
        proc = subprocess.run(  # noqa: S603 — argv list
            argv,
            cwd=cwd,
            input=stdin,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=max(0.5, limit_ms / 1000),
        )
    except subprocess.TimeoutExpired:
        return "time_limit", "", f"exceeded {limit_ms} ms", limit_ms
    ms = int((time.perf_counter() - start) * 1000)
    out = proc.stdout[:MAX_OUTPUT]
    crash = crash_reason(proc.returncode)
    if crash:
        return "runtime_error", out, f"crashed: {crash}", ms
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()
        tail = err[-1][:300] if err else ""
        return (
            "runtime_error",
            out,
            f"exit code {proc.returncode}" + (f": {tail}" if tail else ""),
            ms,
        )
    return "ok", out, "", ms


def judge(language: str, code: str, tests: list[dict], limit_ms: int = 2000) -> Judgement:
    """Run `code` on every {input, output} test."""
    if language not in LANGUAGES:
        return Judgement("compile_error", compile_error=f"unsupported language {language!r}")
    tests = tests[:MAX_TESTS]
    if not tests:
        return Judgement("no_tests")
    with tempfile.TemporaryDirectory(prefix="manabi-judge-") as tmp:
        cwd = Path(tmp)
        try:
            argv, err = _compile(language, code, cwd)
        except subprocess.TimeoutExpired:
            return Judgement("compile_error", total=len(tests), compile_error="compiler timed out")
        if argv is None:
            return Judgement("compile_error", total=len(tests), compile_error=err)
        results: list[TestResult] = []
        for i, t in enumerate(tests):
            status, out, error, ms = _run_one(argv, t.get("input") or "", cwd, limit_ms)
            expected = t.get("output") or ""
            if status == "ok":
                status = (
                    "passed" if normalize_output(out) == normalize_output(expected) else "wrong"
                )
            results.append(TestResult(i, status, t.get("input") or "", expected, out, error, ms))
    passed = sum(1 for r in results if r.verdict == "passed")
    if passed == len(results):
        verdict = "accepted"
    else:
        first = next(r for r in results if r.verdict != "passed")
        verdict = first.verdict
    return Judgement(verdict, passed, len(results), results=results)


@dataclass
class Expected:
    ok: bool
    tests: list[dict] = field(default_factory=list)
    problem: str = ""


def expected_outputs(
    language: str, reference: str, inputs: list[str], limit_ms: int = 2000
) -> Expected:
    """Build {input, output} tests by running the reference — twice, which
    must agree — on every input. Any compile error, crash, timeout, silent or
    unstable run disqualifies the problem: its tests cannot be trusted."""
    if not inputs:
        return Expected(False, problem="the generator wrote no test inputs")
    with tempfile.TemporaryDirectory(prefix="manabi-judge-") as tmp:
        cwd = Path(tmp)
        try:
            argv, err = _compile(language, reference, cwd)
        except subprocess.TimeoutExpired:
            return Expected(False, problem="the reference solution did not compile in time")
        if argv is None:
            return Expected(False, problem=f"the reference solution does not compile: {err[:400]}")
        tests = []
        for i, given in enumerate(inputs[:MAX_TESTS]):
            first = _run_one(argv, given, cwd, limit_ms)
            if first[0] != "ok":
                return Expected(False, problem=f"reference fails test {i + 1}: {first[2]}")
            second = _run_one(argv, given, cwd, limit_ms)
            if normalize_output(first[1]) != normalize_output(second[1]):
                return Expected(False, problem=f"reference output on test {i + 1} is not stable")
            out = normalize_output(first[1])
            tests.append({"input": given, "output": out + "\n" if out else ""})
    # An empty answer is legitimate for some inputs (a stack fed only pushes
    # prints nothing — a real, good problem was thrown out three times for
    # it); a reference that prints nothing for EVERY input is not.
    if all(not t["output"].strip() for t in tests):
        return Expected(False, problem="the reference prints nothing on any test")
    outs = {t["output"] for t in tests}
    if len(tests) >= 4 and len(outs) == 1:
        # Every input giving the same answer means the tests can't tell a
        # right solution from one that prints a constant.
        return Expected(False, problem="every test has the same expected output")
    return Expected(True, tests=tests)
