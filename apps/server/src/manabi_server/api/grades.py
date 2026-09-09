"""Syllabus-weighted grades: components, scores, letter cutoffs and term QPI.

The breakdown belongs to the syllabus, not to Canvas — Canvas leaves group
weights at 0 on most courses and hides the computed grade — so Manabi stores
the weights and does the arithmetic itself (manabi_server.grades). Canvas is
used only as a source of individual assignment scores, pulled on demand.
"""

from fastapi import APIRouter, Depends, HTTPException
from manabi_core.models import Course, GradeComponent, GradeItem, User
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server import grades as g
from manabi_server.db import get_db
from manabi_server.security import get_default_user, require_csrf

router = APIRouter(prefix="/api", tags=["grades"])

MAX_COMPONENTS = 30
MAX_ITEMS_PER_COMPONENT = 300


# ── Wire models ─────────────────────────────────────────────────────────────


class ItemOut(BaseModel):
    id: int
    title: str
    earned: float | None
    possible: float | None
    percent: float | None  # a straight-percentage row (no points)
    canvas_assignment_id: int | None
    graded: bool  # False = shown but excluded from the average
    value_percent: float | None  # this row as a percent, when graded


class ComponentOut(BaseModel):
    id: int
    name: str
    weight: float
    position: int
    percent: float | None  # total points across the graded items
    graded_count: int
    item_count: int
    items: list[ItemOut]


class TargetOut(BaseModel):
    letter: str
    cutoff: float
    needed: float  # average needed across the ungraded weight
    reachable: bool  # False when it would take more than 100%


class CourseGradesOut(BaseModel):
    course_id: int
    code: str
    name: str
    accent_color: str | None
    units: float
    canvas_course_id: int | None
    cutoffs: dict[str, float] | None  # None until set from the syllabus
    default_cutoffs: dict[str, float]  # the template to start from
    percent: float | None  # current standing, renormalised
    letter: str | None
    counted_weight: float
    total_weight: float
    components: list[ComponentOut]
    targets: list[TargetOut]  # only letters above the current standing


class CourseSummaryOut(BaseModel):
    course_id: int
    code: str
    name: str
    accent_color: str | None
    units: float
    percent: float | None
    letter: str | None
    quality_points: float | None
    counted_weight: float
    total_weight: float
    component_count: int
    has_cutoffs: bool


class GradesOverviewOut(BaseModel):
    qpi: float | None  # term QPI over the courses that have a letter
    graded_units: float  # units behind that QPI
    total_units: float
    courses: list[CourseSummaryOut]


class CutoffsIn(BaseModel):
    cutoffs: dict[str, float]


class ComponentIn(BaseModel):
    name: str
    weight: float


class ComponentPatch(BaseModel):
    name: str | None = None
    weight: float | None = None
    position: int | None = None


class ItemIn(BaseModel):
    title: str
    earned: float | None = None
    possible: float | None = None
    percent: float | None = None


class ItemPatch(BaseModel):
    title: str | None = None
    earned: float | None = None
    possible: float | None = None
    percent: float | None = None


class CanvasAssignmentOut(BaseModel):
    canvas_assignment_id: int
    name: str
    points_possible: float | None
    score: float | None
    graded: bool
    already_linked: bool
    linked_component: str | None


class LinkIn(BaseModel):
    canvas_assignment_ids: list[int]


class SyncOut(BaseModel):
    updated: int
    still_ungraded: int


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _owned_course(db: AsyncSession, user: User, course_id: int) -> Course:
    course = await db.get(Course, course_id)
    if course is None or course.user_id != user.id:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


async def _owned_component(db: AsyncSession, user: User, component_id: int) -> GradeComponent:
    row = (
        await db.execute(
            select(GradeComponent)
            .join(Course, Course.id == GradeComponent.course_id)
            .where(GradeComponent.id == component_id, Course.user_id == user.id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Component not found")
    return row


async def _owned_item(db: AsyncSession, user: User, item_id: int) -> GradeItem:
    row = (
        await db.execute(
            select(GradeItem)
            .join(GradeComponent, GradeComponent.id == GradeItem.component_id)
            .join(Course, Course.id == GradeComponent.course_id)
            .where(GradeItem.id == item_id, Course.user_id == user.id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Score not found")
    return row


async def _components_with_items(
    db: AsyncSession, course_ids: list[int]
) -> dict[int, list[tuple[GradeComponent, list[GradeItem]]]]:
    """Components (ordered) with their items, grouped by course id."""
    if not course_ids:
        return {}
    components = (
        (
            await db.execute(
                select(GradeComponent)
                .where(GradeComponent.course_id.in_(course_ids))
                .order_by(GradeComponent.position, GradeComponent.id)
            )
        )
        .scalars()
        .all()
    )
    items = (
        (
            await db.execute(
                select(GradeItem)
                .where(GradeItem.component_id.in_([c.id for c in components] or [0]))
                .order_by(GradeItem.position, GradeItem.id)
            )
        )
        .scalars()
        .all()
    )
    by_component: dict[int, list[GradeItem]] = {}
    for item in items:
        by_component.setdefault(item.component_id, []).append(item)
    out: dict[int, list[tuple[GradeComponent, list[GradeItem]]]] = {}
    for comp in components:
        out.setdefault(comp.course_id, []).append((comp, by_component.get(comp.id, [])))
    return out


def _as_math(item: GradeItem) -> g.Item:
    return g.Item(earned=item.earned, possible=item.possible, percent=item.percent)


def _math_components(pairs) -> list[g.Component]:
    return [
        g.Component(name=c.name, weight=c.weight, items=tuple(_as_math(i) for i in items))
        for c, items in pairs
    ]


def _validated_score(
    earned: float | None, possible: float | None, percent: float | None
) -> tuple[float | None, float | None, float | None]:
    """A row is either points or a percentage, never both."""
    if percent is not None and (earned is not None or possible is not None):
        raise HTTPException(
            status_code=422, detail="A score is either points or a percentage, not both"
        )
    if percent is None and possible is not None and possible <= 0:
        raise HTTPException(status_code=422, detail="Points possible must be greater than 0")
    if percent is None and earned is not None and possible is None:
        raise HTTPException(status_code=422, detail="Points earned needs a points-possible value")
    return earned, possible, percent


def _item_out(item: GradeItem) -> ItemOut:
    value = g.item_percent(_as_math(item))
    return ItemOut(
        id=item.id,
        title=item.title,
        earned=item.earned,
        possible=item.possible,
        percent=item.percent,
        canvas_assignment_id=item.canvas_assignment_id,
        graded=value is not None,
        value_percent=round(value, 2) if value is not None else None,
    )


def _component_out(comp: GradeComponent, items: list[GradeItem]) -> ComponentOut:
    pct = g.component_percent([_as_math(i) for i in items])
    outs = [_item_out(i) for i in items]
    return ComponentOut(
        id=comp.id,
        name=comp.name,
        weight=comp.weight,
        position=comp.position,
        percent=round(pct, 2) if pct is not None else None,
        graded_count=sum(1 for o in outs if o.graded),
        item_count=len(outs),
        items=outs,
    )


def _targets(standing: g.Standing, cutoffs: dict[str, float] | None) -> list[TargetOut]:
    """What the remaining weight must average for each letter still in reach."""
    if not cutoffs:
        return []
    current = standing.percent
    out: list[TargetOut] = []
    for letter in g.GRADED_LETTERS:
        cutoff = g.cutoff_for(letter, cutoffs)
        if cutoff is None:
            continue
        if current is not None and current >= cutoff:
            break  # already at or above this letter — nothing to chase
        needed = g.needed_on_remaining(
            cutoff, current, standing.counted_weight, standing.total_weight
        )
        if needed is None:
            continue
        out.append(
            TargetOut(
                letter=letter,
                cutoff=cutoff,
                needed=round(needed, 2),
                reachable=needed <= 100.0,
            )
        )
    return out


def _course_grades_out(course: Course, pairs) -> CourseGradesOut:
    standing = g.standing(_math_components(pairs))
    cutoffs = course.grade_cutoffs or None
    letter = g.letter_for(standing.percent, cutoffs)
    return CourseGradesOut(
        course_id=course.id,
        code=course.code,
        name=course.name,
        accent_color=course.accent_color,
        units=course.units,
        canvas_course_id=course.canvas_course_id,
        cutoffs=cutoffs,
        default_cutoffs=dict(g.DEFAULT_CUTOFFS),
        percent=round(standing.percent, 2) if standing.percent is not None else None,
        letter=letter,
        counted_weight=standing.counted_weight,
        total_weight=standing.total_weight,
        components=[_component_out(c, items) for c, items in pairs],
        targets=_targets(standing, cutoffs),
    )


# ── Reading ─────────────────────────────────────────────────────────────────


@router.get("/grades")
async def grades_overview(
    user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> GradesOverviewOut:
    """Every active course's standing plus the term QPI."""
    courses = (
        (
            await db.execute(
                select(Course)
                .where(Course.user_id == user.id, Course.archived_at.is_(None))
                .order_by(Course.position, Course.id)
            )
        )
        .scalars()
        .all()
    )
    by_course = await _components_with_items(db, [c.id for c in courses])
    summaries: list[CourseSummaryOut] = []
    qpi_entries: list[tuple[str | None, float]] = []
    graded_units = 0.0
    for course in courses:
        pairs = by_course.get(course.id, [])
        standing = g.standing(_math_components(pairs))
        letter = g.letter_for(standing.percent, course.grade_cutoffs or None)
        points = g.quality_points(letter)
        if letter is not None and course.units > 0:
            graded_units += course.units
        qpi_entries.append((letter, course.units))
        summaries.append(
            CourseSummaryOut(
                course_id=course.id,
                code=course.code,
                name=course.name,
                accent_color=course.accent_color,
                units=course.units,
                percent=round(standing.percent, 2) if standing.percent is not None else None,
                letter=letter,
                quality_points=points,
                counted_weight=standing.counted_weight,
                total_weight=standing.total_weight,
                component_count=len(pairs),
                has_cutoffs=bool(course.grade_cutoffs),
            )
        )
    qpi = g.term_qpi(qpi_entries)
    return GradesOverviewOut(
        qpi=round(qpi, 3) if qpi is not None else None,
        graded_units=graded_units,
        total_units=sum(c.units for c in courses),
        courses=summaries,
    )


@router.get("/courses/{course_id}/grades")
async def course_grades(
    course_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> CourseGradesOut:
    course = await _owned_course(db, user, course_id)
    pairs = (await _components_with_items(db, [course.id])).get(course.id, [])
    return _course_grades_out(course, pairs)


# ── Scheme ──────────────────────────────────────────────────────────────────


@router.put("/courses/{course_id}/grades/cutoffs", dependencies=[Depends(require_csrf)])
async def set_cutoffs(
    course_id: int,
    data: CutoffsIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> CourseGradesOut:
    course = await _owned_course(db, user, course_id)
    try:
        course.grade_cutoffs = g.validate_cutoffs(data.cutoffs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await db.commit()
    pairs = (await _components_with_items(db, [course.id])).get(course.id, [])
    return _course_grades_out(course, pairs)


# ── Components ──────────────────────────────────────────────────────────────


@router.post("/courses/{course_id}/grades/components", dependencies=[Depends(require_csrf)])
async def add_component(
    course_id: int,
    data: ComponentIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> ComponentOut:
    course = await _owned_course(db, user, course_id)
    name = data.name.strip()[:64]
    if not name:
        raise HTTPException(status_code=422, detail="Give the section a name")
    if data.weight <= 0:
        raise HTTPException(status_code=422, detail="Weight must be greater than 0")
    count = (
        await db.execute(
            select(func.count())
            .select_from(GradeComponent)
            .where(GradeComponent.course_id == course.id)
        )
    ).scalar_one()
    if count >= MAX_COMPONENTS:
        raise HTTPException(status_code=422, detail="That's enough sections for one course")
    comp = GradeComponent(
        course_id=course.id, name=name, weight=float(data.weight), position=int(count)
    )
    db.add(comp)
    await db.commit()
    return _component_out(comp, [])


@router.patch("/grades/components/{component_id}", dependencies=[Depends(require_csrf)])
async def update_component(
    component_id: int,
    data: ComponentPatch,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> ComponentOut:
    comp = await _owned_component(db, user, component_id)
    if data.name is not None:
        name = data.name.strip()[:64]
        if not name:
            raise HTTPException(status_code=422, detail="Give the section a name")
        comp.name = name
    if data.weight is not None:
        if data.weight <= 0:
            raise HTTPException(status_code=422, detail="Weight must be greater than 0")
        comp.weight = float(data.weight)
    if data.position is not None:
        comp.position = int(data.position)
    await db.commit()
    items = (
        (
            await db.execute(
                select(GradeItem)
                .where(GradeItem.component_id == comp.id)
                .order_by(GradeItem.position, GradeItem.id)
            )
        )
        .scalars()
        .all()
    )
    return _component_out(comp, list(items))


@router.delete("/grades/components/{component_id}", dependencies=[Depends(require_csrf)])
async def delete_component(
    component_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    comp = await _owned_component(db, user, component_id)
    await db.delete(comp)
    await db.commit()
    return {"ok": True}


# ── Score rows ──────────────────────────────────────────────────────────────


@router.post("/grades/components/{component_id}/items", dependencies=[Depends(require_csrf)])
async def add_item(
    component_id: int,
    data: ItemIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> ItemOut:
    comp = await _owned_component(db, user, component_id)
    title = data.title.strip()[:255]
    if not title:
        raise HTTPException(status_code=422, detail="Give the score a name")
    earned, possible, percent = _validated_score(data.earned, data.possible, data.percent)
    count = (
        await db.execute(
            select(func.count()).select_from(GradeItem).where(GradeItem.component_id == comp.id)
        )
    ).scalar_one()
    if count >= MAX_ITEMS_PER_COMPONENT:
        raise HTTPException(status_code=422, detail="That's enough scores for one section")
    item = GradeItem(
        component_id=comp.id,
        title=title,
        earned=earned,
        possible=possible,
        percent=percent,
        position=int(count),
    )
    db.add(item)
    await db.commit()
    return _item_out(item)


@router.patch("/grades/items/{item_id}", dependencies=[Depends(require_csrf)])
async def update_item(
    item_id: int,
    data: ItemPatch,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> ItemOut:
    item = await _owned_item(db, user, item_id)
    fields = data.model_dump(exclude_unset=True)
    if "title" in fields:
        title = (data.title or "").strip()[:255]
        if not title:
            raise HTTPException(status_code=422, detail="Give the score a name")
        item.title = title
    earned = fields.get("earned", item.earned)
    possible = fields.get("possible", item.possible)
    percent = fields.get("percent", item.percent)
    # switching a row between points and percent clears the other side
    if "percent" in fields and data.percent is not None:
        earned = possible = None
    if ("earned" in fields or "possible" in fields) and (
        data.earned is not None or data.possible is not None
    ):
        percent = None
    item.earned, item.possible, item.percent = _validated_score(earned, possible, percent)
    await db.commit()
    return _item_out(item)


@router.delete("/grades/items/{item_id}", dependencies=[Depends(require_csrf)])
async def delete_item(
    item_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    item = await _owned_item(db, user, item_id)
    await db.delete(item)
    await db.commit()
    return {"ok": True}


# ── Canvas ──────────────────────────────────────────────────────────────────


async def _canvas_assignments(canvas_course_id: int) -> list[dict]:
    """Canvas assignments with the student's own submission attached.

    `include[]=submission` is what carries score/points_possible; paginated so
    courses with more than 100 assignments are not silently truncated."""
    from manabi_server.api.canvas import _canvas_get_all

    rows = await _canvas_get_all(
        f"/courses/{canvas_course_id}/assignments",
        {"include[]": "submission", "per_page": 100},
    )
    return [r for r in rows if isinstance(r, dict) and "id" in r]


def _canvas_score(assignment: dict) -> tuple[float | None, float | None]:
    """(earned, possible) for one Canvas assignment. An excused or ungraded
    submission comes back as earned=None so it is shown but not counted."""
    submission = assignment.get("submission") or {}
    possible = assignment.get("points_possible")
    possible = float(possible) if isinstance(possible, (int, float)) else None
    if submission.get("excused"):
        return None, possible
    score = submission.get("score")
    earned = float(score) if isinstance(score, (int, float)) else None
    return earned, possible


@router.get("/courses/{course_id}/grades/canvas-assignments")
async def list_canvas_assignments(
    course_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> list[CanvasAssignmentOut]:
    """The picker's feed: what Canvas has, and where it is already linked."""
    course = await _owned_course(db, user, course_id)
    if not course.canvas_course_id:
        raise HTTPException(status_code=409, detail="This course is not linked to Canvas")
    rows = (
        await db.execute(
            select(GradeItem.canvas_assignment_id, GradeComponent.name)
            .join(GradeComponent, GradeComponent.id == GradeItem.component_id)
            .where(
                GradeComponent.course_id == course.id,
                GradeItem.canvas_assignment_id.is_not(None),
            )
        )
    ).all()
    linked = {int(aid): name for aid, name in rows}
    out: list[CanvasAssignmentOut] = []
    for a in await _canvas_assignments(course.canvas_course_id):
        aid = int(a["id"])
        earned, possible = _canvas_score(a)
        out.append(
            CanvasAssignmentOut(
                canvas_assignment_id=aid,
                name=str(a.get("name") or f"Assignment {aid}")[:255],
                points_possible=possible,
                score=earned,
                graded=earned is not None,
                already_linked=aid in linked,
                linked_component=linked.get(aid),
            )
        )
    return out


@router.post("/grades/components/{component_id}/link", dependencies=[Depends(require_csrf)])
async def link_canvas_assignments(
    component_id: int,
    data: LinkIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> ComponentOut:
    """Attach Canvas assignments to this component, pulling their scores now."""
    comp = await _owned_component(db, user, component_id)
    course = await _owned_course(db, user, comp.course_id)
    if not course.canvas_course_id:
        raise HTTPException(status_code=409, detail="This course is not linked to Canvas")
    wanted = {int(i) for i in data.canvas_assignment_ids}
    if not wanted:
        raise HTTPException(status_code=422, detail="Pick at least one assignment")
    # course-wide guard: the same assignment must never count twice
    existing = set(
        (
            await db.execute(
                select(GradeItem.canvas_assignment_id)
                .join(GradeComponent, GradeComponent.id == GradeItem.component_id)
                .where(
                    GradeComponent.course_id == course.id,
                    GradeItem.canvas_assignment_id.in_(wanted),
                )
            )
        )
        .scalars()
        .all()
    )
    if existing:
        raise HTTPException(
            status_code=409, detail="Some of those are already linked in this course"
        )
    by_id = {int(a["id"]): a for a in await _canvas_assignments(course.canvas_course_id)}
    position = (
        await db.execute(
            select(func.count()).select_from(GradeItem).where(GradeItem.component_id == comp.id)
        )
    ).scalar_one()
    for aid in sorted(wanted):
        a = by_id.get(aid)
        if a is None:
            continue
        earned, possible = _canvas_score(a)
        db.add(
            GradeItem(
                component_id=comp.id,
                title=str(a.get("name") or f"Assignment {aid}")[:255],
                earned=earned,
                possible=possible,
                canvas_assignment_id=aid,
                position=position,
            )
        )
        position += 1
    await db.commit()
    items = (
        (
            await db.execute(
                select(GradeItem)
                .where(GradeItem.component_id == comp.id)
                .order_by(GradeItem.position, GradeItem.id)
            )
        )
        .scalars()
        .all()
    )
    return _component_out(comp, list(items))


@router.post("/courses/{course_id}/grades/sync", dependencies=[Depends(require_csrf)])
async def sync_canvas_scores(
    course_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> SyncOut:
    """Refresh every linked row's score. Never adds or removes rows, so a
    re-sync is idempotent."""
    course = await _owned_course(db, user, course_id)
    if not course.canvas_course_id:
        raise HTTPException(status_code=409, detail="This course is not linked to Canvas")
    items = (
        (
            await db.execute(
                select(GradeItem)
                .join(GradeComponent, GradeComponent.id == GradeItem.component_id)
                .where(
                    GradeComponent.course_id == course.id,
                    GradeItem.canvas_assignment_id.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if not items:
        return SyncOut(updated=0, still_ungraded=0)
    by_id = {int(a["id"]): a for a in await _canvas_assignments(course.canvas_course_id)}
    updated = ungraded = 0
    for item in items:
        a = by_id.get(item.canvas_assignment_id)
        if a is None:
            continue  # deleted in Canvas — leave the row and its score alone
        earned, possible = _canvas_score(a)
        title = str(a.get("name") or item.title)[:255]
        if (item.earned, item.possible, item.title) != (earned, possible, title):
            item.earned, item.possible, item.title = earned, possible, title
            updated += 1
        if earned is None:
            ungraded += 1
    await db.commit()
    return SyncOut(updated=updated, still_ungraded=ungraded)


@router.delete("/courses/{course_id}/grades", dependencies=[Depends(require_csrf)])
async def clear_grades(
    course_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove the whole breakdown for a course (cutoffs are kept)."""
    course = await _owned_course(db, user, course_id)
    await db.execute(delete(GradeComponent).where(GradeComponent.course_id == course.id))
    await db.commit()
    return {"ok": True}
