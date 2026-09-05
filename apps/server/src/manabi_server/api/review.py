"""Spaced-repetition review queue over the review-enabled flashcard decks.

A module can hold several named decks; only those with review_enabled feed
the daily queue. Whole-module regeneration moves the flag to the new deck;
scoped/practice decks stay out unless the user toggles them in.
"""

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
    RATINGS,
    ReviewState,
    apply_rating,
    preview_intervals,
    restore_review,
    snapshot_review,
)
from manabi_server.timeutil import now_manila, today_manila

router = APIRouter(prefix="/api/review", tags=["review"])


class ReviewCardOut(BaseModel):
    flashcard_id: int
    front: str
    back: str
    module_id: int
    module_title: str
    course_code: str | None
    accent_color: str | None
    reps: int
    lapses: int = 0
    interval_days: float = 0.0
    # rating -> days until the next review if chosen now
    previews: dict[str, int] = {}


class QueueOut(BaseModel):
    due: list[ReviewCardOut]
    due_count: int


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
        )
    )


@router.get("/queue")
async def review_queue(
    limit: int = 60,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> QueueOut:
    today = today_manila()
    rows = (
        await db.execute(
            _review_deck_cards()
            .join(CardReview, CardReview.flashcard_id == Flashcard.id, isouter=True)
            .add_columns(CardReview)
            .where(
                Course.user_id == user.id,
                (CardReview.id.is_(None)) | (CardReview.due_date <= today),
            )
            .order_by(CardReview.due_date.nulls_first(), Flashcard.id)
        )
    ).all()
    due = [_card_out(f, m, c, r, today) for f, m, c, r in rows[: max(1, min(limit, 200))]]
    return QueueOut(due=due, due_count=len(rows))


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
        course_code=course.code,
        accent_color=course.accent_color,
        reps=state.reps,
        lapses=state.lapses,
        interval_days=state.interval_days,
        previews=preview_intervals(state, today),
    )


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
    await db.commit()
    return {"due_date": due.isoformat(), "interval_days": new_state.interval_days}


async def _owned_card_review(db: AsyncSession, user: User, flashcard_id: int) -> CardReview | None:
    """The card's review row if the card belongs to this user (any status —
    undo must also reach a card that the rating just suspended)."""
    row = (
        await db.execute(
            select(CardReview)
            .join(Flashcard, Flashcard.id == CardReview.flashcard_id)
            .join(Artifact, Artifact.id == Flashcard.artifact_id)
            .join(Module, Module.id == Artifact.module_id)
            .join(Course, Course.id == Module.course_id)
            .where(Course.user_id == user.id, Flashcard.id == flashcard_id)
        )
    ).scalar_one_or_none()
    return row


@router.post("/{flashcard_id}/undo", dependencies=[Depends(require_csrf)])
async def undo_rating(
    flashcard_id: int,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Revert the last rating (one level). A card whose only rating is undone
    goes back to never-reviewed."""
    review = await _owned_card_review(db, user, flashcard_id)
    if review is None or not review.prev_state:
        raise HTTPException(status_code=404, detail="Nothing to undo for this card")
    snap = review.prev_state
    was_new = bool(snap.get("new"))
    if was_new:
        await db.delete(review)
    else:
        restore_review(review, snap)
        review.prev_state = None
    await db.commit()
    return {"ok": True, "new": was_new}
