"""Practice: judged coding problems (stdin → stdout, C / C++ / Python) and
formal-language tasks (grammar, regex, DFA). Generation runs on the GPU
worker; expectations come from running the reference (services.practice).
Hidden tests and the reference answer never leave the server until the
problem is solved or the student asks to see the solution."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from manabi_core.models import (
    Course,
    Job,
    JobQueue,
    Module,
    PracticeProblem,
    PracticeSubmission,
    StudyPlan,
    User,
)
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.db import get_db
from manabi_server.jobs.queue import GENERATE_PROBLEM_TASK, defer_task
from manabi_server.security import get_default_user, require_csrf
from manabi_server.services import practice

router = APIRouter(prefix="/api/practice", tags=["practice"])

Kind = Literal["code", "grammar", "regex", "dfa"]
Language = Literal["c", "cpp", "python"]


class ProblemIn(BaseModel):
    kind: Kind = "code"
    language: Language | None = None
    course_id: int | None = None
    module_id: int | None = None
    plan_id: int | None = None
    topic: str | None = Field(default=None, max_length=1000)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    source: Literal["materials", "original"] = "materials"


class AnswerIn(BaseModel):
    answer: str = Field(max_length=100_000)
    language: Language | None = None


class ProblemSummary(BaseModel):
    id: int
    kind: str
    language: str | None
    title: str
    topic: str | None
    difficulty: str
    status: str
    error: str | None
    solved: bool
    best_passed: int | None
    best_total: int | None
    course_id: int | None
    module_id: int | None
    plan_id: int | None
    job_id: int | None
    created_at: datetime


class ProblemOut(ProblemSummary):
    source: str
    statement: str
    spec: dict
    samples: list
    time_limit_ms: int
    test_count: int
    reference: str | None  # only once solved or revealed


def _public_spec(p: PracticeProblem) -> dict:
    spec = dict(p.spec or {})
    for hidden in ("test_inputs", "sample_inputs", "reference_kind", "revealed"):
        spec.pop(hidden, None)
    return spec


async def _best(db: AsyncSession, problem_ids: list[int]) -> dict[int, tuple[int, int]]:
    if not problem_ids:
        return {}
    rows = (
        await db.execute(
            select(
                PracticeSubmission.problem_id,
                func.max(PracticeSubmission.passed),
                func.max(PracticeSubmission.total),
            )
            .where(
                PracticeSubmission.problem_id.in_(problem_ids),
                PracticeSubmission.mode == "submit",
            )
            .group_by(PracticeSubmission.problem_id)
        )
    ).all()
    return {pid: (passed, total) for pid, passed, total in rows}


def _summary(p: PracticeProblem, best: tuple[int, int] | None) -> dict:
    return {
        "id": p.id,
        "kind": p.kind,
        "language": p.language,
        "title": p.title,
        "topic": p.topic,
        "difficulty": p.difficulty,
        "status": p.status,
        "error": p.error if p.status == "failed" else None,
        "solved": p.solved_at is not None,
        "best_passed": best[0] if best else None,
        "best_total": best[1] if best else None,
        "course_id": p.course_id,
        "module_id": p.module_id,
        "plan_id": p.plan_id,
        "job_id": p.job_id,
        "created_at": p.created_at,
    }


def _out(p: PracticeProblem, best: tuple[int, int] | None) -> ProblemOut:
    show_ref = p.solved_at is not None or bool((p.spec or {}).get("revealed"))
    return ProblemOut(
        **_summary(p, best),
        source=p.source,
        statement=p.statement,
        spec=_public_spec(p),
        samples=p.samples or [],
        time_limit_ms=p.time_limit_ms,
        test_count=len(p.tests or []),
        reference=p.reference if show_ref else None,
    )


async def _owned_problem(problem_id: int, user: User, db: AsyncSession) -> PracticeProblem:
    p = await db.get(PracticeProblem, problem_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(status_code=404, detail="Problem not found")
    return p


@router.post("/problems", dependencies=[Depends(require_csrf)])
async def create_problem(
    data: ProblemIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> ProblemSummary:
    """Queue the generation of one problem. Kind `code` needs a language;
    `source=materials` with a module writes from that module's material (a
    topic narrows it to the matching passages)."""
    if data.kind == "code" and data.language is None:
        raise HTTPException(status_code=422, detail="Pick a language for a coding problem")
    course_id = data.course_id
    if data.plan_id is not None:
        plan = await db.get(StudyPlan, data.plan_id)
        course = await db.get(Course, plan.course_id) if plan else None
        if plan is None or course is None or course.user_id != user.id:
            raise HTTPException(status_code=404, detail="Study plan not found")
        course_id = plan.course_id
    if data.module_id is not None:
        module = await db.get(Module, data.module_id)
        course = await db.get(Course, module.course_id) if module else None
        if module is None or course is None or course.user_id != user.id:
            raise HTTPException(status_code=404, detail="Module not found")
        course_id = module.course_id
    elif course_id is not None:
        course = await db.get(Course, course_id)
        if course is None or course.user_id != user.id:
            raise HTTPException(status_code=404, detail="Course not found")
    chunk_ids = None
    topic = (data.topic or "").strip() or None
    if data.source == "materials" and data.module_id and topic:
        from manabi_server.api.artifacts import _focus_chunk_ids

        chunk_ids = await _focus_chunk_ids(db, [data.module_id], topic, None)
    problem = PracticeProblem(
        user_id=user.id,
        course_id=course_id,
        module_id=data.module_id,
        plan_id=data.plan_id,
        kind=data.kind,
        language=data.language if data.kind == "code" else None,
        topic=topic,
        difficulty=data.difficulty,
        source=data.source if data.module_id else "original",
        status="generating",
    )
    db.add(problem)
    await db.flush()
    job = Job(
        user_id=user.id,
        job_type="generate_problem",
        queue=JobQueue.gpu,
        payload={"problem_id": problem.id},
        module_id=data.module_id,
    )
    db.add(job)
    await db.flush()
    problem.job_id = job.id
    await db.commit()  # before deferring: the worker must find both rows
    job.procrastinate_job_id = await defer_task(
        GENERATE_PROBLEM_TASK, "gpu", job_id=job.id, problem_id=problem.id, chunk_ids=chunk_ids
    )
    await db.commit()
    return ProblemSummary(**_summary(problem, None))


@router.get("/problems")
async def list_problems(
    course_id: int | None = None,
    plan_id: int | None = None,
    module_id: int | None = None,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> list[ProblemSummary]:
    q = select(PracticeProblem).where(PracticeProblem.user_id == user.id)
    if course_id is not None:
        q = q.where(PracticeProblem.course_id == course_id)
    if plan_id is not None:
        q = q.where(PracticeProblem.plan_id == plan_id)
    if module_id is not None:
        q = q.where(PracticeProblem.module_id == module_id)
    problems = (await db.execute(q.order_by(PracticeProblem.id.desc()))).scalars().all()
    best = await _best(db, [p.id for p in problems])
    return [ProblemSummary(**_summary(p, best.get(p.id))) for p in problems]


@router.get("/problems/{problem_id}")
async def get_problem(
    problem_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> ProblemOut:
    p = await _owned_problem(problem_id, user, db)
    return _out(p, (await _best(db, [p.id])).get(p.id))


async def _judge(p: PracticeProblem, data: AnswerIn, mode: str, db: AsyncSession) -> dict:
    if p.status != "ready":
        raise HTTPException(status_code=409, detail="This problem is not ready yet")
    language = data.language or p.language or "c"
    cases = p.samples if mode == "run" else p.tests
    if p.kind == "code" and mode == "run" and not cases:
        cases = p.tests[:2]
    verdict = await asyncio.to_thread(
        practice.run, p.kind, language, data.answer, cases or [], p.time_limit_ms
    )
    db.add(
        PracticeSubmission(
            problem_id=p.id,
            mode=mode,
            language=language if p.kind == "code" else None,
            code=data.answer,
            verdict=verdict["verdict"],
            passed=verdict.get("passed") or 0,
            total=verdict.get("total") or 0,
            results=verdict.get("results") or verdict.get("mismatches") or [],
        )
    )
    if mode == "submit" and verdict["verdict"] == "accepted" and p.solved_at is None:
        p.solved_at = datetime.now(UTC)
    if mode == "submit" and p.kind == "code":
        # Hidden tests: show which failed and the first one in full, not all.
        shown = next((r for r in verdict["results"] if r["verdict"] != "passed"), None)
        verdict["results"] = [
            {"index": r["index"], "verdict": r["verdict"], "ms": r["ms"]}
            for r in verdict["results"]
        ]
        verdict["first_failure"] = shown
    await db.commit()
    verdict["solved"] = p.solved_at is not None
    return verdict


@router.post("/problems/{problem_id}/run", dependencies=[Depends(require_csrf)])
async def run_answer(
    problem_id: int,
    data: AnswerIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Judge on the visible samples only."""
    return await _judge(await _owned_problem(problem_id, user, db), data, "run", db)


@router.post("/problems/{problem_id}/submit", dependencies=[Depends(require_csrf)])
async def submit_answer(
    problem_id: int,
    data: AnswerIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Judge on every hidden test; accepted marks the problem solved."""
    return await _judge(await _owned_problem(problem_id, user, db), data, "submit", db)


@router.post("/problems/{problem_id}/reveal", dependencies=[Depends(require_csrf)])
async def reveal_solution(
    problem_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> ProblemOut:
    p = await _owned_problem(problem_id, user, db)
    p.spec = {**(p.spec or {}), "revealed": True}
    await db.commit()
    return _out(p, (await _best(db, [p.id])).get(p.id))


@router.get("/problems/{problem_id}/submissions")
async def list_submissions(
    problem_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    p = await _owned_problem(problem_id, user, db)
    rows = (
        (
            await db.execute(
                select(PracticeSubmission)
                .where(PracticeSubmission.problem_id == p.id)
                .order_by(PracticeSubmission.id.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": s.id,
            "mode": s.mode,
            "language": s.language,
            "verdict": s.verdict,
            "passed": s.passed,
            "total": s.total,
            "code": s.code,
            "created_at": s.created_at,
        }
        for s in rows
    ]


@router.delete("/problems/{problem_id}", dependencies=[Depends(require_csrf)])
async def delete_problem(
    problem_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    p = await _owned_problem(problem_id, user, db)
    await db.delete(p)
    await db.commit()
    return {"ok": True}
