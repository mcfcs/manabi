"""Spaced-repetition review queue over the review-enabled flashcard decks.

A module can hold several named decks; only those with review_enabled feed
the daily queue. Whole-module regeneration moves the flag to the new deck;
scoped/practice decks stay out unless the user toggles them in.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from manabi_core.models import (
    Artifact,
    ArtifactType,
    CardReview,
    Course,
    Flashcard,
    FlashcardStatus,
    Module,
    User,
)
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.db import get_db
from manabi_server.security import get_default_user, require_csrf
from manabi_server.srs import (
    NEW_CARDS_PER_LOAD,
    RATINGS,
    QueueItem,
    ReviewState,
    apply_rating,
    forecast,
    is_leech,
    order_queue,
    preview_intervals,
    restore_review,
    retention,
    snapshot_review,
)
from manabi_server.timeutil import MANILA, now_manila, today_manila

router = APIRouter(prefix="/api/review", tags=["review"])


class ReviewCardOut(BaseModel):
    flashcard_id: int
    front: str
    back: str
    module_id: int
    module_title: str
    course_id: int | None
    course_code: str | None
    accent_color: str | None
    reps: int
    lapses: int = 0
    interval_days: float = 0.0
    # rating -> days until the next review if chosen now
    previews: dict[str, int] = {}


class QueueOut(BaseModel):
    due: list[ReviewCardOut]
    due_count: int  # every due card, including new ones held back by the cap
    new_total: int = 0  # never-reviewed cards that are due
    new_shown: int = 0  # of those, how many are in `due`
    new_offset: int = 0  # echo of the request; next page starts at offset + shown


def _review_deck_cards():
    return (
        select(Flashcard, Module, Course)
        .join(Artifact, Artifact.id == Flashcard.artifact_id)
        .join(Module, Module.id == Artifact.module_id)
        .join(Course, Course.id == Module.course_id)
        .where(
            Artifact.artifact_type == ArtifactType.flashcard_deck,
            Artifact.review_enabled.is_(True),
            Flashcard.status == FlashcardStatus.active,
            # An archived term's cards must stop coming due.
            Course.archived_at.is_(None),
        )
    )


@router.get("/queue")
async def review_queue(
    limit: int = 60,
    new_offset: int = 0,
    course_id: int | None = None,
    module_id: int | None = None,
    cram: bool = False,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> QueueOut:
    """Today's session: overdue reviews (most overdue, weakest first), then up
    to NEW_CARDS_PER_LOAD never-reviewed cards, both interleaved across
    modules. `new_offset` pages through the held-back new cards.

    `course_id` / `module_id` narrow the session to one course or module.
    `cram` additionally drops the due-date filter and the new-card cap, for
    working through everything in a scope before an exam; it requires a scope,
    because cramming every deck at once is not a session anyone wants. Ratings
    schedule normally either way — answering a card early still moves it.
    """
    if cram and course_id is None and module_id is None:
        raise HTTPException(
            status_code=422, detail="Cramming needs a course or module to work through"
        )
    today = today_manila()
    q = (
        _review_deck_cards()
        .join(CardReview, CardReview.flashcard_id == Flashcard.id, isouter=True)
        .add_columns(CardReview)
        .where(Course.user_id == user.id)
    )
    if not cram:
        q = q.where((CardReview.id.is_(None)) | (CardReview.due_date <= today))
    if course_id is not None:
        q = q.where(Course.id == course_id)
    if module_id is not None:
        q = q.where(Module.id == module_id)
    rows = (await db.execute(q)).all()
    by_id = {f.id: (f, m, c, r) for f, m, c, r in rows}
    ordered, new_total = order_queue(
        (
            QueueItem(
                card_id=f.id,
                module_id=m.id,
                due_date=r.due_date if r is not None else None,
                ease=r.ease if r is not None else ReviewState().ease,
            )
            for f, m, c, r in rows
        ),
        # A scoped cram is a deliberate act, not a daily drip: no new-card cap.
        new_cap=10**6 if cram else NEW_CARDS_PER_LOAD,
        new_offset=new_offset,
    )
    shown = ordered[: max(1, min(limit, 200))]
    due = [_card_out(*by_id[i], today) for i in shown]
    return QueueOut(
        due=due,
        due_count=len(rows),
        new_total=new_total,
        new_shown=sum(1 for i in shown if by_id[i][3] is None),
        new_offset=new_offset,
    )


def _state_of(review: CardReview | None) -> ReviewState:
    if review is None:
        return ReviewState()
    return ReviewState(
        interval_days=review.interval_days,
        ease=review.ease,
        reps=review.reps,
        lapses=review.lapses,
    )


def _card_out(
    card: Flashcard, module: Module, course: Course, review: CardReview | None, today
) -> ReviewCardOut:
    state = _state_of(review)
    return ReviewCardOut(
        flashcard_id=card.id,
        front=card.front,
        back=card.back,
        module_id=module.id,
        module_title=module.title,
        course_id=course.id,
        course_code=course.code,
        accent_color=course.accent_color,
        reps=state.reps,
        lapses=state.lapses,
        interval_days=state.interval_days,
        previews=preview_intervals(state, today),
    )


class ScopeOut(BaseModel):
    """One course's share of the deck, for choosing what to work through."""

    course_id: int
    code: str
    accent_color: str | None
    due: int  # cards a normal session would draw from
    total: int  # every active card, i.e. what a cram would cover


@router.get("/scopes")
async def review_scopes(
    user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> list[ScopeOut]:
    """Per-course counts so a session can be narrowed before an exam. The rail
    badge is a single number across everything, which says nothing about which
    course is behind."""
    today = today_manila()
    rows = (
        await db.execute(
            _review_deck_cards()
            .join(CardReview, CardReview.flashcard_id == Flashcard.id, isouter=True)
            .add_columns(CardReview.id, CardReview.due_date)
            .where(Course.user_id == user.id)
        )
    ).all()
    by_course: dict[int, ScopeOut] = {}
    for _card, _module, course, review_id, due_date in rows:
        row = by_course.setdefault(
            course.id,
            ScopeOut(
                course_id=course.id,
                code=course.code,
                accent_color=course.accent_color,
                due=0,
                total=0,
            ),
        )
        row.total += 1
        if review_id is None or (due_date is not None and due_date <= today):
            row.due += 1
    return sorted(by_course.values(), key=lambda r: (-r.due, r.code))


@router.get("/due-count")
async def review_due_count(
    user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> dict:
    today = today_manila()
    subq = (
        _review_deck_cards()
        .join(CardReview, CardReview.flashcard_id == Flashcard.id, isouter=True)
        .where(
            Course.user_id == user.id,
            (CardReview.id.is_(None)) | (CardReview.due_date <= today),
        )
        .subquery()
    )
    count = (await db.execute(select(func.count()).select_from(subq))).scalar_one()
    return {"count": count}


class RatingIn(BaseModel):
    rating: str


@router.post("/{flashcard_id}", dependencies=[Depends(require_csrf)])
async def rate_card(
    flashcard_id: int,
    data: RatingIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if data.rating not in RATINGS:
        raise HTTPException(status_code=422, detail=f"rating must be one of {RATINGS}")
    owned = (
        await db.execute(
            _review_deck_cards().where(Course.user_id == user.id, Flashcard.id == flashcard_id)
        )
    ).first()
    if owned is None:
        raise HTTPException(status_code=404, detail="Card not found")
    card: Flashcard = owned[0]

    review = (
        await db.execute(select(CardReview).where(CardReview.flashcard_id == flashcard_id))
    ).scalar_one_or_none()
    state = _state_of(review)
    new_state, due = apply_rating(state, data.rating, today_manila())
    if review is None:
        review = CardReview(flashcard_id=flashcard_id, due_date=due, prev_state={"new": True})
        db.add(review)
    else:
        review.prev_state = snapshot_review(review)
    review.due_date = due
    review.interval_days = new_state.interval_days
    review.ease = new_state.ease
    review.reps = new_state.reps
    review.lapses = new_state.lapses
    review.last_rating = data.rating
    review.reviewed_at = now_manila()
    # Leech: too many lapses -> suspend and flag; undo restores both.
    became_leech = data.rating == "again" and is_leech(new_state) and not review.is_leech
    if became_leech:
        review.is_leech = True
        card.status = FlashcardStatus.suspended
    await db.commit()
    return {
        "due_date": due.isoformat(),
        "interval_days": new_state.interval_days,
        "leech": became_leech,
    }


async def _owned_card_review(
    db: AsyncSession, user: User, flashcard_id: int
) -> tuple[CardReview, Flashcard] | None:
    """The card's review row (+ the card) if it belongs to this user — any
    status, because undo and leech actions must reach suspended cards."""
    row = (
        await db.execute(
            select(CardReview, Flashcard)
            .join(Flashcard, Flashcard.id == CardReview.flashcard_id)
            .join(Artifact, Artifact.id == Flashcard.artifact_id)
            .join(Module, Module.id == Artifact.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(Course.user_id == user.id, Flashcard.id == flashcard_id)
        )
    ).first()
    return (row[0], row[1]) if row is not None else None


@router.post("/{flashcard_id}/undo", dependencies=[Depends(require_csrf)])
async def undo_rating(
    flashcard_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Revert the last rating (one level). A card whose only rating is undone
    goes back to never-reviewed; a rating that suspended a leech un-suspends it."""
    found = await _owned_card_review(db, user, flashcard_id)
    if found is None or not found[0].prev_state:
        raise HTTPException(status_code=404, detail="Nothing to undo for this card")
    review, card = found
    snap = review.prev_state
    was_new = bool(snap.get("new"))
    if was_new:
        await db.delete(review)
    else:
        was_leech = review.is_leech
        restore_review(review, snap)
        review.prev_state = None
        if was_leech and not review.is_leech and card.status == FlashcardStatus.suspended:
            card.status = FlashcardStatus.active
    await db.commit()
    return {"ok": True, "new": was_new}


# ── Leeches ────────────────────────────────────────────────────────────────


class LeechOut(BaseModel):
    flashcard_id: int
    front: str
    back: str
    module_id: int
    module_title: str
    course_code: str | None
    accent_color: str | None
    lapses: int
    reviewed_at: str | None


@router.get("/leeches")
async def list_leeches(
    user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> list[LeechOut]:
    rows = (
        await db.execute(
            select(Flashcard, Module, Course, CardReview)
            .join(Artifact, Artifact.id == Flashcard.artifact_id)
            .join(Module, Module.id == Artifact.module_id)
            .join(Course, Course.id == Module.course_id)
            .join(CardReview, CardReview.flashcard_id == Flashcard.id)
            .where(Course.user_id == user.id, CardReview.is_leech.is_(True))
            .order_by(CardReview.reviewed_at.desc().nulls_last(), Flashcard.id)
        )
    ).all()
    return [
        LeechOut(
            flashcard_id=f.id,
            front=f.front,
            back=f.back,
            module_id=m.id,
            module_title=m.title,
            course_code=c.code,
            accent_color=c.accent_color,
            lapses=r.lapses,
            reviewed_at=r.reviewed_at.isoformat() if r.reviewed_at else None,
        )
        for f, m, c, r in rows
    ]


@router.post("/{flashcard_id}/leech-reset", dependencies=[Depends(require_csrf)])
async def reset_leech(
    flashcard_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Start the card over: fresh scheduling state, active again, due today."""
    found = await _owned_card_review(db, user, flashcard_id)
    if found is None or not found[0].is_leech:
        raise HTTPException(status_code=404, detail="Card is not a leech")
    review, card = found
    fresh = ReviewState()
    review.interval_days = fresh.interval_days
    review.ease = fresh.ease
    review.reps = fresh.reps
    review.lapses = fresh.lapses
    review.due_date = today_manila()
    review.last_rating = None
    review.prev_state = None
    review.is_leech = False
    card.status = FlashcardStatus.active
    await db.commit()
    return {"ok": True}


@router.post("/{flashcard_id}/leech-dismiss", dependencies=[Depends(require_csrf)])
async def dismiss_leech(
    flashcard_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Keep the card suspended but drop it from the Leeches list (it stays
    visible as suspended in its deck)."""
    found = await _owned_card_review(db, user, flashcard_id)
    if found is None or not found[0].is_leech:
        raise HTTPException(status_code=404, detail="Card is not a leech")
    review, _card = found
    review.is_leech = False
    review.prev_state = None
    await db.commit()
    return {"ok": True}


# ── Stats ──────────────────────────────────────────────────────────────────


class ReviewStatsOut(BaseModel):
    reviewed_today: int
    due_now: int
    in_rotation: int  # active cards in review-enabled decks
    leeches: int
    retention_30d: float | None  # share of cards reviewed in the last 30 days last rated good/easy
    forecast: list[int]  # due per day for the next 7 days; index 0 = today (incl. overdue + new)


@router.get("/stats")
async def review_stats(
    user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> ReviewStatsOut:
    today = today_manila()
    rows = (
        await db.execute(
            select(CardReview.due_date, CardReview.last_rating, CardReview.reviewed_at)
            .select_from(Flashcard)
            .join(Artifact, Artifact.id == Flashcard.artifact_id)
            .join(Module, Module.id == Artifact.module_id)
            .join(Course, Course.id == Module.course_id)
            .join(CardReview, CardReview.flashcard_id == Flashcard.id, isouter=True)
            .where(
                Artifact.artifact_type == ArtifactType.flashcard_deck,
                Artifact.review_enabled.is_(True),
                Flashcard.status == FlashcardStatus.active,
                Course.user_id == user.id,
            )
        )
    ).all()
    due_dates = [r.due_date for r in rows]
    counts = forecast(today, due_dates)
    since = today - timedelta(days=30)
    recent = [
        r.last_rating
        for r in rows
        if r.reviewed_at is not None and r.reviewed_at.astimezone(MANILA).date() >= since
    ]
    reviewed_today = sum(
        1
        for r in rows
        if r.reviewed_at is not None and r.reviewed_at.astimezone(MANILA).date() == today
    )
    leeches = (
        await db.execute(
            select(func.count())
            .select_from(CardReview)
            .join(Flashcard, Flashcard.id == CardReview.flashcard_id)
            .join(Artifact, Artifact.id == Flashcard.artifact_id)
            .join(Module, Module.id == Artifact.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(Course.user_id == user.id, CardReview.is_leech.is_(True))
        )
    ).scalar_one()
    return ReviewStatsOut(
        reviewed_today=reviewed_today,
        due_now=counts[0],
        in_rotation=len(rows),
        leeches=leeches,
        retention_30d=retention(recent),
        forecast=counts,
    )
