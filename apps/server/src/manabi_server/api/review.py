"""Spaced-repetition review queue over the latest flashcard decks."""

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
from manabi_server.srs import RATINGS, ReviewState, apply_rating
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


class QueueOut(BaseModel):
    due: list[ReviewCardOut]
    due_count: int


def _latest_deck_cards():
    latest_decks = (
        select(func.max(Artifact.id))
        .where(Artifact.artifact_type == ArtifactType.flashcard_deck)
        .group_by(Artifact.module_id)
        .scalar_subquery()
    )
    return (
        select(Flashcard, Module, Course)
        .join(Artifact, Artifact.id == Flashcard.artifact_id)
        .join(Module, Module.id == Artifact.module_id)
        .join(Course, Course.id == Module.course_id)
        .where(
            Artifact.id.in_(latest_decks),
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
            _latest_deck_cards()
            .join(CardReview, CardReview.flashcard_id == Flashcard.id, isouter=True)
            .where(
                Course.user_id == user.id,
                (CardReview.id.is_(None)) | (CardReview.due_date <= today),
            )
            .order_by(CardReview.due_date.nulls_first(), Flashcard.id)
        )
    ).all()
    due = [
        ReviewCardOut(
            flashcard_id=f.id,
            front=f.front,
            back=f.back,
            module_id=m.id,
            module_title=m.title,
            course_code=c.code,
            accent_color=c.accent_color,
            reps=0,
        )
        for f, m, c in rows[: max(1, min(limit, 200))]
    ]
    return QueueOut(due=due, due_count=len(rows))


@router.get("/due-count")
async def review_due_count(
    user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> dict:
    today = today_manila()
    subq = (
        _latest_deck_cards()
        .join(CardReview, CardReview.flashcard_id == Flashcard.id, isouter=True)
        .where(
            Course.user_id == user.id,
            (CardReview.id.is_(None)) | (CardReview.due_date <= today),
        )
        .subquery()
    )
    count = (
        await db.execute(select(func.count()).select_from(subq))
    ).scalar_one()
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
            _latest_deck_cards().where(
                Course.user_id == user.id, Flashcard.id == flashcard_id
            )
        )
    ).first()
    if owned is None:
        raise HTTPException(status_code=404, detail="Card not found")

    review = (
        await db.execute(
            select(CardReview).where(CardReview.flashcard_id == flashcard_id)
        )
    ).scalar_one_or_none()
    state = (
        ReviewState(
            interval_days=review.interval_days,
            ease=review.ease,
            reps=review.reps,
            lapses=review.lapses,
        )
        if review
        else ReviewState()
    )
    new_state, due = apply_rating(state, data.rating, today_manila())
    if review is None:
        review = CardReview(flashcard_id=flashcard_id, due_date=due)
        db.add(review)
    review.due_date = due
    review.interval_days = new_state.interval_days
    review.ease = new_state.ease
    review.reps = new_state.reps
    review.lapses = new_state.lapses
    review.last_rating = data.rating
    review.reviewed_at = now_manila()
    await db.commit()
    return {"due_date": due.isoformat(), "interval_days": new_state.interval_days}
