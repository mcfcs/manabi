"""Practice problems: validation of what the model wrote, and judging what
the student submits. The model never decides an expected output — see
processing.judge (code) and processing.formal (grammar / regex / DFA)."""

from __future__ import annotations

from dataclasses import dataclass

from manabi_server.processing import formal, judge

MAX_ATTEMPTS = 3
SAMPLE_STRINGS = 3  # accepted + rejected examples shown for a theory task


@dataclass
class Validation:
    ok: bool
    problem: str = ""
    samples: list | None = None
    tests: list | None = None


def validate(
    kind: str, language: str | None, reference: str, spec: dict, limit_ms: int
) -> Validation:
    """Build a problem's visible samples and hidden tests from its reference,
    or say why the problem can't be offered."""
    if not (reference or "").strip():
        return Validation(False, "no reference answer was written")
    if kind == "code":
        samples_in = list(spec.get("sample_inputs") or [])
        tests_in = list(spec.get("test_inputs") or [])
        inputs = [i if i.endswith("\n") else i + "\n" for i in samples_in + tests_in]
        exp = judge.expected_outputs(language or "c", reference, inputs, limit_ms)
        if not exp.ok:
            return Validation(False, exp.problem)
        n = len(samples_in)
        # Hidden tests include the samples, as on HackerRank.
        return Validation(True, samples=exp.tests[:n], tests=exp.tests)
    ref_kind = spec.get("reference_kind") or ("grammar" if kind == "grammar" else "regex")
    tests, problem = formal.build_tests(ref_kind, reference, list(spec.get("alphabet") or []))
    if problem:
        return Validation(False, problem)
    accepted = [t for t in tests if t["accept"]][:SAMPLE_STRINGS]
    rejected = [t for t in tests if not t["accept"]][:SAMPLE_STRINGS]
    return Validation(True, samples=accepted + rejected, tests=tests)


def run(kind: str, language: str, answer: str, cases: list, limit_ms: int) -> dict:
    """Judge an answer on the given cases; a JSON-ready verdict."""
    if kind == "code":
        return judge.judge(language, answer, cases, limit_ms).as_dict()
    v = formal.check(kind, answer, cases)
    return {
        "verdict": v.verdict,
        "passed": v.checked - len(v.mismatches) if v.verdict != "format_error" else 0,
        "total": v.checked,
        "compile_error": v.error,
        "max_len": v.max_len,
        "mismatches": v.mismatches,
        "results": [],
    }
