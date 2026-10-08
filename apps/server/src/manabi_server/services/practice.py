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
    # The key must describe the statement's language. A generated "equal
    # numbers of a's and b's" grammar missed 90 balanced strings (aabbba…),
    # so a student's correct grammar would have been marked wrong. The model
    # also writes the language as a plain membership test, straight from the
    # statement; key and test must agree on every string checked.
    test_code = (spec.get("membership_test") or "").strip()
    if not test_code:
        return Validation(False, "no membership test was written")
    words = ["" if t["s"] == "ε" else t["s"] for t in tests]
    answers = judge.predicate_answers(test_code, words)
    if isinstance(answers, str):
        return Validation(False, answers)
    for t, says in zip(tests, answers, strict=True):
        if says != t["accept"]:
            key_says = "accepts" if t["accept"] else "rejects"
            test_says = "accepts" if says else "rejects"
            return Validation(
                False,
                f"your reference {key_says} `{t['s']}` but your membership test {test_says} it "
                "— one of them does not match the statement",
            )
    # With the key and the membership test agreeing on every string, a listed
    # example that disagrees is the model miscounting an example ("ababab is
    # rejected" for equal a's and b's), not evidence against the key — drop
    # it rather than throw away a verified problem (one was, three times).
    accepts = formal.recognizer(ref_kind, reference)

    def norm(s: str) -> str:
        s = s.strip()
        return "ε" if s in formal.EPSILON or s == "" else s

    def holds(s: str, expected: bool) -> bool:
        word = () if norm(s) == "ε" else tuple(norm(s))
        return accepts(word) == expected

    samples: list[dict] = []
    for listed, expected in (
        (spec.get("examples_accepted") or [], True),
        (spec.get("examples_rejected") or [], False),
    ):
        # The model's examples that hold first, then the shortest strings.
        picks = [norm(s) for s in listed if holds(s, expected)]
        picks += [t["s"] for t in tests if t["accept"] == expected]
        for s in list(dict.fromkeys(picks))[: SAMPLE_STRINGS + 1]:
            samples.append({"s": s, "accept": expected})
    return Validation(True, samples=samples, tests=tests)


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
