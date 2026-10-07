"""Study plans: CRUD and the plan-scoped study path view.

A plan's tests are quiz artifacts with `content.plan_id`; its view lists, per
chosen module, the summary sections that cite the plan's materials (each with
its own quick check), Steven's lesson, the module topic test, and then the
plan's final mock exams. Quizzes without a plan_id belong to no plan.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from manabi_core.material_profile import profile_material
from manabi_core.models import (
    Artifact,
    ArtifactType,
    Chunk,
    Course,
    Document,
    Job,
    JobStatus,
    Module,
    StudyPlan,
    User,
)
from manabi_core.retrieval import load_context_chunks
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.api.artifacts import (
    QUIZ_TYPES,
    QuizListItem,
    _latest_artifact,
    _quiz_list_items,
    _section_chunks,
    _summary_sections,
)
from manabi_server.db import get_db
from manabi_server.security import get_default_user, require_csrf
from manabi_server.services.study_plans import auto_mix, merge_mixes, plan_mix

router = APIRouter(prefix="/api", tags=["study"])


# ── Shapes ────────────────────────────────────────────────────────────────


class PlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    module_ids: list[int] = Field(min_length=1)
    document_ids: list[int] | None = None  # None = every material
    types: list[str] | None = None  # None = chosen from the material
    type_mix: dict[str, float] | None = None
    focus: str | None = None


class PlanPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    module_ids: list[int] | None = None
    document_ids: list[int] | None = None
    types: list[str] | None = None
    type_mix: dict[str, float] | None = None
    focus: str | None = None
    position: int | None = None


class PlanOut(BaseModel):
    id: int
    course_id: int
    name: str
    position: int
    module_ids: list[int]
    document_ids: list[int] | None
    types: list[str] | None
    type_mix: dict | None
    focus: str | None
    created_at: datetime
    # progress, for the plan list
    modules_total: int = 0
    modules_passed: int = 0
    final_best: float | None = None


class StudySectionOut(BaseModel):
    index: int
    title: str
    block_count: int
    has_sources: bool
    quiz_id: int | None = None
    best_score: float | None = None


class StudyModuleOut(BaseModel):
    id: int
    title: str
    has_material: bool
    chunk_count: int
    summary_id: int | None = None
    sections: list[StudySectionOut] = []
    lecture_id: int | None = None
    lecture_segments: int = 0
    checkpoint: QuizListItem | None = None
    language: str | None = None
    mix: dict[str, float] = {}  # the mix this plan's tests use for the module
    pending: dict[str, int] = {}


class StudyOut(BaseModel):
    course_id: int
    plan: PlanOut | None = None
    modules: list[StudyModuleOut]
    finals: list[QuizListItem]
    final_mix: dict[str, float] = {}
    pending_final: int | None = None


PASS_MARK = 70.0


# ── Helpers ───────────────────────────────────────────────────────────────


async def _owned_course(db: AsyncSession, course_id: int, user: User) -> Course:
    course = (
        await db.execute(select(Course).where(Course.id == course_id, Course.user_id == user.id))
    ).scalar_one_or_none()
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


async def get_owned_plan(
    plan_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> StudyPlan:
    plan = (
        await db.execute(
            select(StudyPlan)
            .join(Course, Course.id == StudyPlan.course_id)
            .where(StudyPlan.id == plan_id, Course.user_id == user.id)
        )
    ).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="Study plan not found")
    return plan


async def _validate_plan_scope(
    db: AsyncSession,
    course: Course,
    module_ids: list[int],
    document_ids: list[int] | None,
    types: list[str] | None,
) -> None:
    valid_modules = set(
        (
            await db.execute(
                select(Module.id).where(
                    Module.course_id == course.id, Module.is_general.is_(False)
                )
            )
        ).scalars()
    )
    if not set(module_ids) <= valid_modules:
        raise HTTPException(status_code=422, detail="Module not in this course")
    if document_ids is not None:
        valid_docs = set(
            (
                await db.execute(
                    select(Document.id).where(
                        Document.module_id.in_(module_ids), Document.deleted_at.is_(None)
                    )
                )
            ).scalars()
        )
        if not set(document_ids) <= valid_docs:
            raise HTTPException(status_code=422, detail="Material not in the chosen modules")
        if not document_ids:
            raise HTTPException(status_code=422, detail="Pick at least one material")
    if types is not None and not set(types) <= set(QUIZ_TYPES):
        raise HTTPException(status_code=422, detail="Unknown question type")


def _plan_out(plan: StudyPlan, **progress) -> PlanOut:
    return PlanOut(
        id=plan.id,
        course_id=plan.course_id,
        name=plan.name,
        position=plan.position,
        module_ids=[int(m) for m in plan.module_ids],
        document_ids=[int(d) for d in plan.document_ids] if plan.document_ids is not None else None,
        types=list(plan.types) if plan.types else None,
        type_mix=plan.type_mix,
        focus=plan.focus,
        created_at=plan.created_at,
        **progress,
    )


async def module_material(
    db: AsyncSession, module_id: int, document_ids: list[int] | None
) -> list:
    """The chunks a plan may use from one module (all, or its chosen materials)."""
    if document_ids is None:
        return await load_context_chunks(db, [module_id])
    return await load_context_chunks(db, [module_id], document_ids=list(document_ids))


async def resolve_mix(
    db: AsyncSession, plan: StudyPlan | None, module_ids: list[int], document_ids
) -> dict[str, float]:
    """The mix a test over these modules uses under this plan."""
    mixes = []
    for mid in module_ids:
        chunks = await module_material(db, mid, document_ids)
        if chunks:
            mixes.append(auto_mix(profile_material(c.text for c in chunks)))
    auto = merge_mixes(mixes) if len(mixes) > 1 else (mixes[0] if mixes else {"mcq": 1})
    if plan is None:
        return auto
    return plan_mix(list(plan.types) if plan.types else None, plan.type_mix, auto)


def _slot(job: Job) -> tuple[int | None, int | None, str] | None:
    """(plan_id, module_id or None for a final, slot) an in-flight job fills."""
    payload = job.payload if isinstance(job.payload, dict) else {}
    plan_id = payload.get("plan_id")
    if job.job_type == "generate_quiz":
        role = payload.get("role")
        mods = payload.get("module_ids") or []
        if role == "final" or payload.get("exam"):
            return (plan_id, None, "final")
        if role and mods:
            return (plan_id, int(mods[0]), str(role))
        return None
    if job.job_type == "generate_summary" and job.module_id:
        return (None, job.module_id, "summary")
    if job.job_type == "teach_module" and job.module_id:
        return (None, job.module_id, "lecture")
    return None


async def build_view(
    db: AsyncSession, user: User, course: Course, plan: StudyPlan | None
) -> StudyOut:
    all_modules = (
        (
            await db.execute(
                select(Module)
                .where(Module.course_id == course.id, Module.is_general.is_(False))
                .order_by(Module.position, Module.id)
            )
        )
        .scalars()
        .all()
    )
    chosen = set(int(m) for m in plan.module_ids) if plan else None
    modules = [m for m in all_modules if chosen is None or m.id in chosen]
    plan_docs = (
        [int(d) for d in plan.document_ids] if plan and plan.document_ids is not None else None
    )
    allowed_docs = set(plan_docs) if plan_docs is not None else None

    quizzes = [
        a
        for a in (
            await db.execute(
                select(Artifact)
                .join(Module, Module.id == Artifact.module_id)
                .where(Module.course_id == course.id, Artifact.artifact_type == ArtifactType.quiz)
                .order_by(Artifact.id.desc())
            )
        )
        .scalars()
        .all()
        if (a.content or {}).get("plan_id") == (plan.id if plan else None)
    ]
    items = {i.artifact_id: i for i in await _quiz_list_items(db, quizzes)}
    finals = [items[a.id] for a in quizzes if (a.content or {}).get("role") == "final"]

    inflight = (
        (
            await db.execute(
                select(Job)
                .where(
                    Job.user_id == user.id,
                    Job.status.in_([JobStatus.queued, JobStatus.running]),
                    Job.job_type.in_(["generate_quiz", "generate_summary", "teach_module"]),
                )
                .order_by(Job.id)
            )
        )
        .scalars()
        .all()
    )
    pending: dict[int | None, dict[str, int]] = {}
    pending_final = None
    module_ids = {m.id for m in modules}
    for job in inflight:
        slot = _slot(job)
        if slot is None:
            continue
        plan_id, mid, name = slot
        if name in ("summary", "lecture"):
            pending.setdefault(mid, {})[name] = job.id
        elif plan_id == (plan.id if plan else None):
            if mid is None:
                mods = {int(x) for x in (job.payload or {}).get("module_ids") or []}
                if mods & module_ids:
                    pending_final = job.id
            else:
                pending.setdefault(mid, {})[name] = job.id

    out: list[StudyModuleOut] = []
    mixes = []
    for m in modules:
        chunks = await module_material(db, m.id, plan_docs)
        profile = profile_material(c.text for c in chunks) if chunks else None
        auto = auto_mix(profile) if profile else {}
        mix = (
            plan_mix(list(plan.types) if plan and plan.types else None,
                     plan.type_mix if plan else None, auto)
            if chunks
            else {}
        )
        if chunks:
            mixes.append(auto)
        summary = await _latest_artifact(db, m.id, ArtifactType.summary)
        lecture = await _latest_artifact(db, m.id, ArtifactType.lecture)
        by_role: dict[str, Artifact] = {}
        for a in quizzes:
            if a.module_id == m.id:
                r = (a.content or {}).get("role")
                if r and r not in by_role:
                    by_role[r] = a
        sec_chunks = {
            i: _section_chunks(s) for i, s in enumerate(_summary_sections(summary))
        }
        if allowed_docs is not None and sec_chunks:
            all_ids = {c for ids in sec_chunks.values() for c in ids}
            doc_of = dict(
                (
                    await db.execute(
                        select(Chunk.id, Chunk.document_id).where(Chunk.id.in_(all_ids))
                    )
                ).all()
            ) if all_ids else {}
            sec_chunks = {
                i: [c for c in ids if doc_of.get(c) in allowed_docs]
                for i, ids in sec_chunks.items()
            }
        sections = []
        for i, sec in enumerate(_summary_sections(summary)):
            if allowed_docs is not None and not sec_chunks.get(i):
                continue  # this section teaches materials the plan left out
            q = by_role.get(f"section:{i}")
            sections.append(
                StudySectionOut(
                    index=i,
                    title=str(sec.get("title") or f"Section {i + 1}"),
                    block_count=len(sec.get("blocks", []) or []),
                    has_sources=bool(sec_chunks.get(i)),
                    quiz_id=q.id if q else None,
                    best_score=items[q.id].best_score if q else None,
                )
            )
        cp = by_role.get("checkpoint")
        segs = (lecture.content or {}).get("segments", []) if lecture else []
        out.append(
            StudyModuleOut(
                id=m.id,
                title=m.title,
                has_material=bool(chunks),
                chunk_count=len(chunks),
                summary_id=summary.id if summary else None,
                sections=sections,
                lecture_id=lecture.id if lecture else None,
                lecture_segments=len(segs) if isinstance(segs, list) else 0,
                checkpoint=items[cp.id] if cp else None,
                language=profile.language if profile else None,
                mix=mix,
                pending=pending.get(m.id, {}),
            )
        )
    auto_final = merge_mixes(mixes) if len(mixes) > 1 else (mixes[0] if mixes else {})
    final_mix = (
        plan_mix(list(plan.types) if plan and plan.types else None,
                 plan.type_mix if plan else None, auto_final)
        if auto_final
        else {}
    )
    return StudyOut(
        course_id=course.id,
        plan=_plan_out(plan, **_progress(out, finals)) if plan else None,
        modules=out,
        finals=finals,
        final_mix=final_mix,
        pending_final=pending_final,
    )


def _progress(modules: list[StudyModuleOut], finals: list[QuizListItem]) -> dict:
    with_material = [m for m in modules if m.has_material]
    passed = [
        m for m in with_material
        if m.checkpoint and m.checkpoint.best_score is not None
        and m.checkpoint.best_score >= PASS_MARK
    ]
    best = max((f.best_score for f in finals if f.best_score is not None), default=None)
    return {
        "modules_total": len(with_material),
        "modules_passed": len(passed),
        "final_best": best,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.get("/courses/{course_id}/plans")
async def list_plans(
    course_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> list[PlanOut]:
    course = await _owned_course(db, course_id, user)
    plans = (
        (
            await db.execute(
                select(StudyPlan)
                .where(StudyPlan.course_id == course.id)
                .order_by(StudyPlan.position, StudyPlan.id)
            )
        )
        .scalars()
        .all()
    )
    out = []
    for p in plans:
        view = await build_view(db, user, course, p)
        out.append(view.plan)
    return out


@router.post("/courses/{course_id}/plans", dependencies=[Depends(require_csrf)])
async def create_plan(
    course_id: int,
    data: PlanIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> PlanOut:
    course = await _owned_course(db, course_id, user)
    types = [t for t in data.types if t in QUIZ_TYPES] if data.types else None
    await _validate_plan_scope(db, course, data.module_ids, data.document_ids, types)
    position = (
        await db.execute(
            select(func.coalesce(func.max(StudyPlan.position), -1)).where(
                StudyPlan.course_id == course.id
            )
        )
    ).scalar_one() + 1
    plan = StudyPlan(
        course_id=course.id,
        name=data.name.strip(),
        position=position,
        module_ids=list(dict.fromkeys(data.module_ids)),
        document_ids=list(dict.fromkeys(data.document_ids)) if data.document_ids else None,
        types=types or None,
        type_mix={t: float(w) for t, w in (data.type_mix or {}).items() if types and t in types}
        or None,
        focus=(data.focus or "").strip()[:2000] or None,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return _plan_out(plan, modules_total=len(plan.module_ids))


@router.get("/plans/{plan_id}")
async def get_plan(
    plan: StudyPlan = Depends(get_owned_plan),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> StudyOut:
    course = await _owned_course(db, plan.course_id, user)
    return await build_view(db, user, course, plan)


@router.patch("/plans/{plan_id}", dependencies=[Depends(require_csrf)])
async def patch_plan(
    data: PlanPatch,
    plan: StudyPlan = Depends(get_owned_plan),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> PlanOut:
    course = await _owned_course(db, plan.course_id, user)
    fields = data.model_fields_set
    module_ids = data.module_ids if "module_ids" in fields and data.module_ids else plan.module_ids
    document_ids = data.document_ids if "document_ids" in fields else plan.document_ids
    types = (
        ([t for t in data.types if t in QUIZ_TYPES] or None) if "types" in fields and data.types
        else (None if "types" in fields else plan.types)
    )
    await _validate_plan_scope(db, course, list(module_ids), document_ids, types)
    if "name" in fields and data.name:
        plan.name = data.name.strip()
    plan.module_ids = list(dict.fromkeys(module_ids))
    plan.document_ids = list(dict.fromkeys(document_ids)) if document_ids else None
    plan.types = types
    if "type_mix" in fields:
        plan.type_mix = (
            {t: float(w) for t, w in (data.type_mix or {}).items() if types and t in types} or None
        )
    if "focus" in fields:
        plan.focus = (data.focus or "").strip()[:2000] or None
    if "position" in fields and data.position is not None:
        plan.position = data.position
    await db.commit()
    await db.refresh(plan)
    return _plan_out(plan, modules_total=len(plan.module_ids))


@router.delete("/plans/{plan_id}", dependencies=[Depends(require_csrf)])
async def delete_plan(
    plan: StudyPlan = Depends(get_owned_plan), db: AsyncSession = Depends(get_db)
) -> dict:
    """Removes the plan. Its tests stay (each module's Quiz tab still lists
    them) — a plan is a lens over material, not the owner of what you took."""
    await db.delete(plan)
    await db.commit()
    return {"ok": True}


@router.get("/courses/{course_id}/study")
async def course_study(
    course_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> StudyOut:
    """The course's first plan (or, with no plans, the unscoped path)."""
    course = await _owned_course(db, course_id, user)
    plan = (
        await db.execute(
            select(StudyPlan)
            .where(StudyPlan.course_id == course.id)
            .order_by(StudyPlan.position, StudyPlan.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    return await build_view(db, user, course, plan)


class DiagramIn(BaseModel):
    # The browser's Mermaid render error, when asking for a repair.
    error: str | None = Field(default=None, max_length=2000)


@router.post(
    "/artifacts/{artifact_id}/sections/{index}/diagram", dependencies=[Depends(require_csrf)]
)
async def draw_section_diagram(
    artifact_id: int,
    index: int,
    data: DiagramIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Queue one diagram for a summary section (or a repair of a diagram the
    browser could not render). The model may decline when no diagram helps."""
    from manabi_core.models import JobQueue

    from manabi_server.jobs.queue import DIAGRAM_SECTION_TASK, defer_task

    artifact = (
        await db.execute(
            select(Artifact)
            .join(Module, Module.id == Artifact.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(
                Artifact.id == artifact_id,
                Artifact.artifact_type == ArtifactType.summary,
                Course.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if artifact is None:
        raise HTTPException(status_code=404, detail="Summary not found")
    if not 0 <= index < len(_summary_sections(artifact)):
        raise HTTPException(status_code=404, detail="No such section")
    payload = {"artifact_id": artifact.id, "section_index": index}
    inflight = (
        await db.execute(
            select(Job).where(
                Job.job_type == "diagram_section",
                Job.status.in_([JobStatus.queued, JobStatus.running]),
            )
        )
    ).scalars().all()
    for j in inflight:
        if (j.payload or {}).get("artifact_id") == artifact.id and (j.payload or {}).get(
            "section_index"
        ) == index:
            return {"job_id": j.id}
    job = Job(
        user_id=user.id,
        job_type="diagram_section",
        queue=JobQueue.gpu,
        payload=payload,
        module_id=artifact.module_id,
    )
    db.add(job)
    await db.flush()
    job.procrastinate_job_id = await defer_task(
        DIAGRAM_SECTION_TASK, "gpu", job_id=job.id, error=data.error, **payload
    )
    await db.commit()
    return {"job_id": job.id}
