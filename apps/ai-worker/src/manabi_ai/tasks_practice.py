"""Practice problems: the model writes a problem, a reference solution and
test INPUTS; the app server then runs the reference to get the expected
outputs (manabi_server.tasks.validate_problem) and refuses any problem whose
reference doesn't hold up. A refused problem comes back here with the reason,
at most twice more.

Theory tasks (grammar / regex / DFA) work the same way: the model writes the
exercise and a reference answer; the server computes which strings belong to
the language, so the student's answer is judged by the language it
describes, not by resembling the key.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from manabi_core.models import Job, JobStatus, PracticeProblem
from manabi_core.retrieval import load_chunks_by_ids, load_context_chunks
from sqlalchemy import select

from manabi_ai.app import app
from manabi_ai.config import get_settings
from manabi_ai.context import batch_chunks, build_context
from manabi_ai.db import session_factory
from manabi_ai.ollama_client import GenerationError, generate_structured

log = logging.getLogger("manabi_ai.practice")

VALIDATE_PROBLEM_TASK = "manabi_server.tasks.validate_problem"  # cpu queue contract
LANGUAGE_NAME = {"c": "C", "cpp": "C++", "python": "Python 3"}
NO_SOURCES = "(No course material: write an original problem on the topic.)"

CODE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "topic": {"type": "string"},
        "statement": {"type": "string"},
        "input_format": {"type": "string"},
        "output_format": {"type": "string"},
        "constraints": {"type": "string"},
        "reference_solution": {"type": "string"},
        "starter_code": {"type": "string"},
        "sample_inputs": {"type": "array", "items": {"type": "string"}, "minItems": 2},
        "test_inputs": {"type": "array", "items": {"type": "string"}, "minItems": 6},
    },
    "required": [
        "title",
        "topic",
        "statement",
        "input_format",
        "output_format",
        "constraints",
        "reference_solution",
        "starter_code",
        "sample_inputs",
        "test_inputs",
    ],
}

THEORY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "topic": {"type": "string"},
        "statement": {"type": "string"},
        "alphabet": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "reference": {"type": "string"},
        "hint": {"type": "string"},
    },
    "required": ["title", "topic", "statement", "alphabet", "reference", "hint"],
}

CODE_PROMPT = """You write ONE programming problem in the style of HackerRank for a
university course, with its official solution. Language: {language}.
Difficulty: {difficulty}. Topic: {topic}.

Rules — the problem is judged automatically, so follow them exactly:
- The program reads ALL input from standard input and writes ONLY the answer
  to standard output, in exactly the format stated. Never print prompts such
  as "Enter n:" and never print extra labels.
- Deterministic: no randomness, time, memory addresses or undefined behaviour.
- Keep inputs small (at most a few hundred values); any sensible solution
  must finish well within one second.
- "statement": the task in Markdown — the story and what to compute. Do NOT
  repeat the input/output formats here.
- "input_format", "output_format", "constraints": precise and complete.
- "reference_solution": a COMPLETE, correct {language} program that solves
  every valid input. It is the answer key; it must be right.
- "starter_code": a {language} skeleton (includes, main, the function or
  struct to fill in) WITHOUT the solution logic.
- "sample_inputs": 2 small inputs shown to the student.
- "test_inputs": 8 different hidden inputs covering normal cases and edge
  cases (smallest input, empty structure, duplicates, largest allowed). Each
  must follow the input format and constraints exactly.
- When the course material below contains a homework, lab or demo program on
  this topic (for example a stack), base the problem on it.
{style}{feedback}
COURSE MATERIAL:
"""

THEORY_RULES = {
    "grammar": (
        "write a CONTEXT-FREE GRAMMAR for a language",
        "a correct grammar in this exact format: one nonterminal per line, "
        "alternatives separated by |, symbols separated by spaces, ε for the "
        "empty string, uppercase letters for nonterminals, the first line's "
        "nonterminal is the start symbol. Example: `S -> a S b | ε`",
    ),
    "regex": (
        "write a REGULAR EXPRESSION for a language",
        "a correct regular expression using only the alphabet's characters and "
        "| (union), * + ? (repetition), parentheses and ε. Example: `(a|b)*abb`",
    ),
    "dfa": (
        "design a DFA (deterministic finite automaton) for a language",
        "a correct REGULAR EXPRESSION for the same language (the student "
        "writes the DFA; your regex is the key), using | * + ? ( ) and ε",
    ),
}

THEORY_PROMPT = """You write ONE formal-languages exercise for a university course
in which the student must {task}. Difficulty: {difficulty}. Topic: {topic}.

Rules — the answer is judged automatically by testing strings:
- The language is over a small alphabet of 2 or 3 single characters
  (for example a and b). "alphabet" lists them.
- "statement": in Markdown, state the language precisely in words (and set
  notation if useful), e.g. "all strings over {a, b} with an even number of
  a's". It must not contain the answer.
- "reference": {reference}.
- "hint": one short hint that does not give the answer away.
- Prefer languages like those in the course material below (its examples,
  quizzes and exercises).
{feedback}
COURSE MATERIAL:
"""


@app.task(name="manabi_ai.tasks.generate_problem", queue="gpu", retry=0)
async def generate_problem(
    job_id: int,
    problem_id: int,
    chunk_ids: list[int] | None = None,
    feedback: str | None = None,
) -> None:
    from manabi_ai.tasks_gen import _course_code_style

    settings = get_settings()
    async with session_factory()() as db:
        job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()
        problem = await db.get(PracticeProblem, problem_id)
        job.status = JobStatus.running
        job.started_at = job.started_at or datetime.now(UTC)
        job.progress_pct = 10
        job.progress_note = "Writing the problem" if not feedback else "Rewriting the problem"
        await db.commit()
        try:
            if problem is None:
                raise RuntimeError("problem row is gone")
            source = NO_SOURCES
            chunks = []
            if problem.source == "materials":
                if chunk_ids:
                    chunks = await load_chunks_by_ids(db, [int(c) for c in chunk_ids])
                elif problem.module_id:
                    chunks = await load_context_chunks(db, [problem.module_id])
            if chunks:
                ctx = build_context(batch_chunks(chunks)[0], None)
                source = ctx.source_text
                problem.source_chunk_ids = [c.id for c in batch_chunks(chunks)[0]]
            fb = (
                f"\nYOUR PREVIOUS VERSION WAS REJECTED: {feedback}\nWrite a new, fixed version.\n"
                if feedback
                else ""
            )
            topic = problem.topic or "a core idea of the course material"
            if problem.kind == "code":
                style = ""
                if problem.language in ("c", "cpp") and problem.module_id:
                    style = await _course_code_style(db, problem.module_id)
                    if style:
                        style = (
                            "\nWrite the reference solution and starter code in this style." + style
                        )
                prompt = (
                    CODE_PROMPT.replace("{language}", LANGUAGE_NAME.get(problem.language, "C"))
                    .replace("{difficulty}", problem.difficulty)
                    .replace("{topic}", topic)
                    .replace("{style}", style)
                    .replace("{feedback}", fb)
                )
                out = await generate_structured(
                    prompt, source, CODE_SCHEMA, None, response_headroom=6144
                )
                problem.title = (out.get("title") or "Practice problem")[:255]
                problem.topic = (out.get("topic") or topic)[:500]
                problem.statement = out.get("statement") or ""
                problem.spec = {
                    "input_format": out.get("input_format") or "",
                    "output_format": out.get("output_format") or "",
                    "constraints": out.get("constraints") or "",
                    "starter_code": out.get("starter_code") or "",
                    "sample_inputs": [s for s in out.get("sample_inputs") or [] if s.strip()][:3],
                    "test_inputs": [s for s in out.get("test_inputs") or [] if s.strip()][:12],
                }
                problem.reference = out.get("reference_solution") or ""
            else:
                task, reference = THEORY_RULES[problem.kind]
                prompt = (
                    THEORY_PROMPT.replace("{task}", task)
                    .replace("{difficulty}", problem.difficulty)
                    .replace("{topic}", topic)
                    .replace("{reference}", reference)
                    .replace("{feedback}", fb)
                )
                out = await generate_structured(
                    prompt, source, THEORY_SCHEMA, None, response_headroom=3072
                )
                problem.title = (out.get("title") or "Formal languages exercise")[:255]
                problem.topic = (out.get("topic") or topic)[:500]
                problem.statement = out.get("statement") or ""
                problem.spec = {
                    "alphabet": [a.strip() for a in out.get("alphabet") or [] if a.strip()],
                    "hint": out.get("hint") or "",
                    "reference_kind": "grammar" if problem.kind == "grammar" else "regex",
                }
                problem.reference = out.get("reference") or ""
            problem.model_name = settings.generation_model
            problem.status = "validating"
            problem.attempts = (problem.attempts or 0) + 1
            job.progress_pct = 70
            job.progress_note = "Checking the reference solution"
            await db.commit()
            await app.configure_task(VALIDATE_PROBLEM_TASK, queue="cpu").defer_async(
                problem_id=problem.id, job_id=job.id
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("problem generation failed")
            await db.rollback()
            if problem is not None:
                problem.status = "failed"
                problem.error = f"{type(exc).__name__}: {str(exc)[:300]}"
            job.status = JobStatus.failed
            job.error = f"{type(exc).__name__}: {str(exc)[:400]}"
            job.finished_at = datetime.now(UTC)
            await db.commit()
            if not isinstance(exc, GenerationError):
                raise
