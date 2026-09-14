"""Re-verify every stored `output` question by running its code.

The 20 output questions on record were generated before any verification
existed, and at least one was wrong in a way that mattered: asked what
`sentence + 5` prints for "the quick brown fox", the model named index 5 ('u')
correctly in its own explanation and then answered "quick brown fox" — the
substring from index 4.

Run from the repo root:
    uv run --package manabi-server python scripts/verify_quiz_outputs.py          # report only
    uv run --package manabi-server python scripts/verify_quiz_outputs.py --apply  # correct them

Reporting is the default on purpose: this rewrites stored answers.
"""

import sys

from manabi_core.models import AIFeedback, AIFeedbackKind, Artifact, QuizQuestion
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from manabi_server.config import get_settings
from manabi_server.processing.code_exec import (
    c_compiler,
    execute,
    extract_snippet,
    normalize_output,
    outputs_match,
    printed_anything,
)


def main(apply: bool) -> int:
    if c_compiler() is None:
        print("warning: no C compiler found — C questions will be skipped")

    engine = create_engine(get_settings().database_url_sync)
    checked = agreed = corrected = unverifiable = 0

    with Session(engine) as db:
        rows = db.execute(
            select(QuizQuestion, Artifact)
            .join(Artifact, Artifact.id == QuizQuestion.artifact_id)
            .where(QuizQuestion.qtype == "output")
            .order_by(QuizQuestion.id)
        ).all()

        for q, artifact in rows:
            checked += 1
            answer = dict(q.answer or {})
            snippet = extract_snippet(q.prompt or "")
            if snippet is None:
                unverifiable += 1
                print(f"  q{q.id:<4} — no runnable code block")
                if apply:
                    q.answer = {**answer, "verified": "unverifiable:no runnable code block"}
                continue
            result = execute(snippet)
            if not result.ok:
                unverifiable += 1
                print(f"  q{q.id:<4} - could not run ({result.error})")
                if apply:
                    q.answer = {**answer, "verified": f"unverifiable:{result.error}"}
                continue
            if not printed_anything(result):
                # Ran clean but printed nothing: the question is about something
                # other than stdout, so "" is not the answer.
                unverifiable += 1
                print(f"  q{q.id:<4} - prints nothing; leaving the model's answer")
                if apply:
                    q.answer = {**answer, "verified": "unverifiable:program prints nothing"}
                continue

            claimed = answer.get("text", "")
            real = normalize_output(result.stdout)
            if outputs_match(claimed, result.stdout):
                agreed += 1
                print(f"  q{q.id:<4} ok   {real!r}")
                if apply:
                    # Stamp it: without the flag the client self-grades, which
                    # is the safe default but loses exact grading on answers we
                    # have actually proven.
                    q.answer = {**answer, "verified": "executed"}
                continue

            corrected += 1
            print(f"  q{q.id:<4} WRONG")
            print(f"        model: {claimed!r}")
            print(f"        real:  {real!r}")
            if apply:
                db.add(
                    AIFeedback(
                        kind=AIFeedbackKind.answer_disputed,
                        artifact_id=artifact.id,
                        question_id=q.id,
                        rejected={"answer": q.answer, "explanation": q.explanation},
                        preferred={
                            "answer": {"kind": "output", "text": real},
                            "verified_by": f"executed ({snippet.lang})",
                        },
                        model_name=artifact.model_name,
                        prompt_version=artifact.prompt_version,
                    )
                )
                q.answer = {"kind": "output", "text": real, "verified": "executed"}
                q.explanation = (
                    f"{(q.explanation or '').rstrip()}\n\nVerified by running the code."
                ).strip()

        if apply:
            db.commit()

    print(
        f"\n{checked} output question(s): {agreed} already correct, "
        f"{corrected} wrong, {unverifiable} not verifiable."
    )
    if corrected and not apply:
        print("Re-run with --apply to correct them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--apply" in sys.argv))
