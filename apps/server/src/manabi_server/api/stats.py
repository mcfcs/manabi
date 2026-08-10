"""Study dashboard stats: activity per day, streak, per-course totals."""

from datetime import timedelta

from fastapi import APIRouter, Depends
from manabi_core.models import (
    CardReview,
    LectureCheckpointResult,
    Note,
    QuizAttempt,
    User,
)
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.db import get_db
from manabi_server.security import get_default_user
from manabi_server.timeutil import today_manila

router = APIRouter(prefix="/api/stats", tags=["stats"])


class DayActivity(BaseModel):
    date: str
    reviews: int
    quizzes: int


class StatsOut(BaseModel):
    streak_days: int
    reviews_total: int
    quizzes_taken: int
    avg_quiz_score: float | None
    checkpoints_answered: int
    days: list[DayActivity]  # last 14


def _local_date(col):
    return func.date(func.timezone("Asia/Manila", col))


@router.get("")
async def stats(
    user: User = Depends(get_default_user), db: AsyncSession = Depends(get_db)
) -> StatsOut:
    today = today_manila()
    since14 = today - timedelta(days=13)
    since60 = today - timedelta(days=60)

    review_day = _local_date(CardReview.reviewed_at).label("d")
    review_days = dict(
        (
            await db.execute(
                select(review_day, func.count(CardReview.id))
                .where(CardReview.reviewed_at.is_not(None))
                .group_by(review_day)
            )
        ).all()
    )
    quiz_day = _local_date(QuizAttempt.finished_at).label("d")
    quiz_days = dict(
        (
            await db.execute(
                select(quiz_day, func.count(QuizAttempt.id))
                .where(QuizAttempt.finished_at.is_not(None))
                .group_by(quiz_day)
            )
        ).all()
    )
    note_days = {
        d
        for (d,) in (
            await db.execute(
                select(_local_date(Note.updated_at))
                .where(Note.updated_at.is_not(None))
                .distinct()
            )
        ).all()
    }
    checkpoint_days = {
        d
        for (d,) in (
            await db.execute(
                select(_local_date(LectureCheckpointResult.answered_at)).distinct()
            )
        ).all()
    }

    active_days = (
        set(review_days) | set(quiz_days) | note_days | checkpoint_days
    ) - {None}

    streak = 0
    day = today
    # today counts if active; otherwise the streak may still be alive from yesterday
    if day not in active_days:
        day = day - timedelta(days=1)
    while day in active_days and day >= since60:
        streak += 1
        day -= timedelta(days=1)

    reviews_total = (
        await db.execute(select(func.count(CardReview.id)).where(CardReview.reps > 0))
    ).scalar_one()
    quiz_count, avg_score = (
        await db.execute(
            select(func.count(QuizAttempt.id), func.avg(QuizAttempt.score)).where(
                QuizAttempt.finished_at.is_not(None)
            )
        )
    ).one()
    checkpoints = (
        await db.execute(select(func.count(LectureCheckpointResult.id)))
    ).scalar_one()

    days = []
    for i in range(14):
        d = since14 + timedelta(days=i)
        days.append(
            DayActivity(
                date=d.isoformat(),
                reviews=review_days.get(d, 0),
                quizzes=quiz_days.get(d, 0),
            )
        )

    return StatsOut(
        streak_days=streak,
        reviews_total=reviews_total,
        quizzes_taken=quiz_count,
        avg_quiz_score=round(float(avg_score), 1) if avg_score is not None else None,
        checkpoints_answered=checkpoints,
        days=days,
    )
