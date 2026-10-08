"""The Mistakes deck: every quiz question answered wrong becomes a flashcard.

One deck per module (generation_mode "mistakes"), review-enabled so it feeds
the spaced-repetition queue, and never displaced when the module's main deck
is regenerated. Each question is added once; the deck remembers which
question ids it holds in `content.question_ids`.
"""

from __future__ import annotations

from manabi_core.models import (
    Artifact,
    ArtifactType,
    Citation,
    Flashcard,
    Module,
    QuizQuestion,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

MISTAKES_MODE = "mistakes"
EXPLANATION_MAX = 600


def response_is_wrong(value) -> bool:
    """Exams store {"response", "grade"}; topic tests store {"response",
    "grade"} too (older attempts stored the bare answer and say nothing)."""
    return isinstance(value, dict) and value.get("grade") == "wrong"


def answer_text(q: QuizQuestion) -> str:
    a = q.answer or {}
    kind = a.get("kind", q.qtype)
    if kind == "mcq":
        opts = q.options or []
        i = a.get("correct_option")
        if isinstance(i, int) and 0 <= i < len(opts):
            return f"{'ABCDEFGH'[i]}. {opts[i]}"
        return ""
    if kind == "tf":
        return "True" if a.get("value") else "False"
    if kind == "enumeration":
        return ", ".join(a.get("items") or [])
    if kind == "essay":
        return a.get("model_answer") or ""
    if kind == "coding":
        return a.get("solution") or ""
    return a.get("text") or ""


def card_sides(q: QuizQuestion) -> tuple[str, str] | None:
    """Front: the question as it was asked (options lettered). Back: the
    answer, then the explanation. None when the key is unusable."""
    answer = answer_text(q)
    if not answer.strip():
        return None
    front = (q.prompt or "").strip()
    if q.qtype == "mcq" and q.options:
        front += "\n\n" + "\n".join(f"{'ABCDEFGH'[i]}. {o}" for i, o in enumerate(q.options))
    back = answer.strip()
    explanation = (q.explanation or "").strip()
    if explanation:
        if len(explanation) > EXPLANATION_MAX:
            explanation = explanation[:EXPLANATION_MAX].rsplit(" ", 1)[0] + "…"
        back += "\n\n" + explanation
    return front, back


async def _mistakes_deck(db: AsyncSession, module: Module, model_name: str) -> Artifact:
    deck = (
        await db.execute(
            select(Artifact).where(
                Artifact.module_id == module.id,
                Artifact.artifact_type == ArtifactType.flashcard_deck,
                Artifact.generation_mode == MISTAKES_MODE,
            )
        )
    ).scalar_one_or_none()
    if deck is None:
        deck = Artifact(
            module_id=module.id,
            artifact_type=ArtifactType.flashcard_deck,
            scope_module_ids=[module.id],
            title=f"Mistakes — {module.title}"[:255],
            content={"question_ids": []},
            model_name=model_name,
            prompt_version="mistakes",
            source_chunk_ids=[],
            source_fingerprint="",
            module_version_at_gen=module.content_version,
            generation_mode=MISTAKES_MODE,
            review_enabled=True,
        )
        db.add(deck)
        await db.flush()
    return deck


async def record_mistakes(db: AsyncSession, quiz: Artifact, responses: dict) -> int:
    """Add the wrongly answered questions of one attempt to their modules'
    Mistakes decks. Returns how many cards were added. Caller commits."""
    wrong_ids = {
        int(k) for k, v in (responses or {}).items() if k.isdigit() and response_is_wrong(v)
    }
    if not wrong_ids:
        return 0
    questions = (
        (
            await db.execute(
                select(QuizQuestion).where(
                    QuizQuestion.artifact_id == quiz.id, QuizQuestion.id.in_(wrong_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    added = 0
    for q in questions:
        if str((q.answer or {}).get("verified", "")).startswith("rejected"):
            continue  # a retired question teaches nothing
        sides = card_sides(q)
        if sides is None:
            continue
        module = await db.get(Module, q.module_id or quiz.module_id)
        if module is None:
            continue
        deck = await _mistakes_deck(db, module, quiz.model_name)
        held = list((deck.content or {}).get("question_ids", []))
        if q.id in held:
            continue
        ord_ = (
            await db.execute(
                select(func.coalesce(func.max(Flashcard.ord) + 1, 0)).where(
                    Flashcard.artifact_id == deck.id
                )
            )
        ).scalar_one()
        db.add(Flashcard(artifact_id=deck.id, ord=ord_, front=sides[0], back=sides[1]))
        # The card points at the same pages the question cited.
        for src in (
            await db.execute(
                select(Citation).where(
                    Citation.artifact_id == quiz.id, Citation.item_ref == f"q:{q.ord}"
                )
            )
        ).scalars():
            db.add(
                Citation(
                    artifact_id=deck.id,
                    item_ref=f"card:{ord_}",
                    chunk_id=src.chunk_id,
                    element_ids=src.element_ids,
                    document_id=src.document_id,
                    document_title=src.document_title,
                    page_start=src.page_start,
                    page_end=src.page_end,
                    quote_excerpt=src.quote_excerpt,
                    support_score=src.support_score,
                    status=src.status,
                )
            )
        deck.content = {**(deck.content or {}), "question_ids": [*held, q.id]}
        await db.flush()
        added += 1
    return added
