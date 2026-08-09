"""GPU-queue generation tasks: summary, flashcards, quiz.

Flow per task: load scoped context from Postgres → build numbered-source
context (+ notes as emphasis-only) → schema-constrained generation →
citation resolution against the job scope (drop, never invent) → persist
artifact + citations → defer support-scoring on the cpu queue.
"""

import logging
from datetime import UTC, datetime

from manabi_core.models import (
    Artifact,
    ArtifactType,
    Citation,
    Flashcard,
    Job,
    JobStatus,
    Module,
    Note,
    QuizQuestion,
)
from manabi_core.retrieval import ScopedChunk, load_context_chunks, source_fingerprint
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_ai import prompts
from manabi_ai.app import app
from manabi_ai.config import get_settings
from manabi_ai.context import batch_chunks, build_context
from manabi_ai.db import session_factory
from manabi_ai.ollama_client import GenerationError, generate_structured
from manabi_ai.validators import ResolvedItem, dedup_questions, resolve_items

log = logging.getLogger("manabi_ai")

SCORE_SUPPORT_TASK = "manabi_server.tasks.score_support"  # cpu queue contract


async def _progress(db: AsyncSession, job: Job, pct: int, note: str) -> None:
    job.progress_pct = pct
    job.progress_note = note
    await db.commit()


async def _load_notes_text(db: AsyncSession, module_ids: list[int]) -> str | None:
    rows = (
        (await db.execute(select(Note.plain_text).where(Note.module_id.in_(module_ids))))
        .scalars()
        .all()
    )
    text = "\n\n".join(r for r in rows if r)
    return text or None


def _citation_rows(
    artifact_id: int, item_ref: str, chunks: list[ScopedChunk], excerpt: str
) -> list[Citation]:
    return [
        Citation(
            artifact_id=artifact_id,
            item_ref=item_ref,
            chunk_id=c.id,
            document_id=c.document_id,
            document_title=c.document_title,
            page_start=c.page_start,
            page_end=c.page_end,
            quote_excerpt=excerpt[:400],
        )
        for c in chunks
    ]


async def _finish(db: AsyncSession, job: Job, artifact_id: int, dropped: int) -> None:
    job.status = JobStatus.succeeded
    job.progress_pct = 100
    job.progress_note = "Done" + (f" ({dropped} unsupported items dropped)" if dropped else "")
    job.result = {"artifact_id": artifact_id, "dropped": dropped}
    job.finished_at = datetime.now(UTC)
    await db.commit()
    # support scoring runs on the cpu queue (needs the app server's embed model)
    await app.configure_task(SCORE_SUPPORT_TASK, queue="cpu").defer_async(
        artifact_id=artifact_id
    )


async def _fail(db: AsyncSession, job: Job, exc: Exception) -> None:
    job.status = JobStatus.failed
    job.error = f"{type(exc).__name__}: {str(exc)[:400]}"
    job.finished_at = datetime.now(UTC)
    await db.commit()


async def _start(db: AsyncSession, job_id: int) -> Job:
    job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()
    job.status = JobStatus.running
    job.started_at = datetime.now(UTC)
    job.progress_pct = 5
    job.progress_note = "Preparing context"
    await db.commit()
    return job


@app.task(name="manabi_ai.tasks.generate_summary", queue="gpu", retry=1)
async def generate_summary(job_id: int, module_id: int) -> None:
    settings = get_settings()
    async with session_factory()() as db:
        job = await _start(db, job_id)
        try:
            chunks = await load_context_chunks(db, [module_id])
            notes = await _load_notes_text(db, [module_id])
            module = (
                await db.execute(select(Module).where(Module.id == module_id))
            ).scalar_one()

            sections: list[dict] = []
            key_terms: list[dict] = []
            acronyms: list[dict] = []
            all_citations: list[tuple[str, list[ScopedChunk], str]] = []
            dropped = 0
            batches = batch_chunks(chunks)
            for bi, batch in enumerate(batches):
                await _progress(
                    db, job, 15 + int(60 * bi / len(batches)),
                    f"Generating with {settings.generation_model}"
                    + (f" ({bi + 1}/{len(batches)})" if len(batches) > 1 else ""),
                )
                ctx = build_context(batch, notes if bi == 0 else None)
                result = await generate_structured(
                    prompts.SUMMARY_PROMPT, ctx.source_text, prompts.SUMMARY_SCHEMA
                )
                for section in result.get("sections", []):
                    kept, d = resolve_items(
                        section.get("blocks", []), ctx.index_map, {module_id}
                    )
                    dropped += d
                    if not kept:
                        continue
                    si = len(sections)
                    blocks = []
                    for bj, resolved in enumerate(kept):
                        ref = f"s{si}:b{bj}"
                        blocks.append(
                            {
                                "text": resolved.item["text"],
                                "chunk_ids": [c.id for c in resolved.chunks],
                            }
                        )
                        all_citations.append((ref, resolved.chunks, resolved.item["text"]))
                    sections.append({"title": section.get("title", ""), "blocks": blocks})

                kept_terms, d = resolve_items(
                    result.get("key_terms", []), ctx.index_map, {module_id}
                )
                dropped += d
                for resolved in kept_terms:
                    ref = f"kt:{len(key_terms)}"
                    key_terms.append(
                        {
                            "term": resolved.item["term"],
                            "definition": resolved.item["definition"],
                        }
                    )
                    excerpt = f"{resolved.item['term']}: {resolved.item['definition']}"
                    all_citations.append((ref, resolved.chunks, excerpt))

                kept_acr, d = resolve_items(
                    result.get("acronyms", []), ctx.index_map, {module_id}
                )
                dropped += d
                for resolved in kept_acr:
                    if any(
                        a["acronym"].lower() == resolved.item["acronym"].lower()
                        for a in acronyms
                    ):
                        continue
                    ref = f"ac:{len(acronyms)}"
                    acronyms.append(
                        {
                            "acronym": resolved.item["acronym"],
                            "meaning": resolved.item["meaning"],
                        }
                    )
                    excerpt = f"{resolved.item['acronym']} means {resolved.item['meaning']}"
                    all_citations.append((ref, resolved.chunks, excerpt))

            await _progress(db, job, 85, "Validating citations")
            artifact = Artifact(
                module_id=module_id,
                artifact_type=ArtifactType.summary,
                scope_module_ids=[module_id],
                title=f"Study summary — {module.title}",
                content={
                    "sections": sections,
                    "key_terms": key_terms,
                    "acronyms": acronyms,
                },
                model_name=settings.generation_model,
                prompt_version=prompts.PROMPT_VERSION,
                source_chunk_ids=[c.id for c in chunks],
                source_fingerprint=source_fingerprint(chunks),
                module_version_at_gen=module.content_version,
                job_id=job.id,
            )
            db.add(artifact)
            await db.flush()
            for ref, cited, excerpt in all_citations:
                for row in _citation_rows(artifact.id, ref, cited, excerpt):
                    db.add(row)
            await _finish(db, job, artifact.id, dropped)
        except (GenerationError, Exception) as exc:  # noqa: BLE001
            log.exception("summary generation failed")
            await db.rollback()
            await _fail(db, job, exc)
            raise


@app.task(name="manabi_ai.tasks.generate_flashcards", queue="gpu", retry=1)
async def generate_flashcards(job_id: int, module_id: int, count: int = 12) -> None:
    settings = get_settings()
    async with session_factory()() as db:
        job = await _start(db, job_id)
        try:
            chunks = await load_context_chunks(db, [module_id])
            notes = await _load_notes_text(db, [module_id])
            module = (
                await db.execute(select(Module).where(Module.id == module_id))
            ).scalar_one()

            batches = batch_chunks(chunks)
            per_batch = max(2, round(count / len(batches)))
            resolved_cards: list[ResolvedItem] = []
            dropped = 0
            for bi, batch in enumerate(batches):
                await _progress(
                    db, job, 15 + int(60 * bi / len(batches)),
                    f"Creating cards with {settings.generation_model}"
                    + (f" ({bi + 1}/{len(batches)})" if len(batches) > 1 else ""),
                )
                ctx = build_context(batch, notes)
                n = per_batch if bi < len(batches) - 1 else max(
                    2, count - per_batch * (len(batches) - 1)
                )
                result = await generate_structured(
                    prompts.FLASHCARDS_PROMPT.replace("{count}", str(n)),
                    ctx.source_text,
                    prompts.FLASHCARDS_SCHEMA,
                )
                kept, d = resolve_items(result.get("cards", []), ctx.index_map, {module_id})
                dropped += d
                resolved_cards.extend(kept)

            await _progress(db, job, 85, "Validating citations")
            # carry over user-edited cards from the previous deck
            previous = (
                await db.execute(
                    select(Artifact)
                    .where(
                        Artifact.module_id == module_id,
                        Artifact.artifact_type == ArtifactType.flashcard_deck,
                    )
                    .order_by(Artifact.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            carried: list[Flashcard] = []
            if previous is not None:
                carried = (
                    (
                        await db.execute(
                            select(Flashcard).where(
                                Flashcard.artifact_id == previous.id,
                                Flashcard.edited.is_(True),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )

            artifact = Artifact(
                module_id=module_id,
                artifact_type=ArtifactType.flashcard_deck,
                scope_module_ids=[module_id],
                title=f"Flashcards — {module.title}",
                content={},
                model_name=settings.generation_model,
                prompt_version=prompts.PROMPT_VERSION,
                source_chunk_ids=[c.id for c in chunks],
                source_fingerprint=source_fingerprint(chunks),
                module_version_at_gen=module.content_version,
                job_id=job.id,
            )
            db.add(artifact)
            await db.flush()
            ord_ = 0
            for resolved in resolved_cards[:count]:
                db.add(
                    Flashcard(
                        artifact_id=artifact.id,
                        ord=ord_,
                        front=resolved.item["front"],
                        back=resolved.item["back"],
                    )
                )
                excerpt = f"{resolved.item['front']} {resolved.item['back']}"
                for row in _citation_rows(artifact.id, f"card:{ord_}", resolved.chunks, excerpt):
                    db.add(row)
                ord_ += 1
            for old in carried:
                db.add(
                    Flashcard(
                        artifact_id=artifact.id,
                        ord=ord_,
                        front=old.front,
                        back=old.back,
                        edited=True,
                        status=old.status,
                    )
                )
                ord_ += 1
            await _finish(db, job, artifact.id, dropped)
        except (GenerationError, Exception) as exc:  # noqa: BLE001
            log.exception("flashcard generation failed")
            await db.rollback()
            await _fail(db, job, exc)
            raise


def _question_answer(item: dict) -> dict | None:
    qtype = item.get("qtype")
    if qtype == "mcq":
        options = item.get("options") or []
        correct = item.get("correct_option")
        if len(options) >= 2 and isinstance(correct, int) and 0 <= correct < len(options):
            return {"kind": "mcq", "correct_option": correct}
        return None
    if qtype == "tf":
        if isinstance(item.get("correct_bool"), bool):
            return {"kind": "tf", "value": item["correct_bool"]}
        return None
    if qtype == "short":
        if item.get("correct_text"):
            return {"kind": "short", "text": item["correct_text"]}
        return None
    return None


@app.task(name="manabi_ai.tasks.generate_quiz", queue="gpu", retry=1)
async def generate_quiz(
    job_id: int, module_ids: list[int], types: list[str], count: int = 10
) -> None:
    settings = get_settings()
    async with session_factory()() as db:
        job = await _start(db, job_id)
        try:
            scope = {int(m) for m in module_ids}
            notes = await _load_notes_text(db, list(scope))
            modules = (
                (await db.execute(select(Module).where(Module.id.in_(scope))))
                .scalars()
                .all()
            )
            per_module = max(2, round(count * 1.4 / len(scope)))  # oversample for dedup

            candidates: list[ResolvedItem] = []
            dropped = 0
            for mi, module in enumerate(modules):
                chunks = await load_context_chunks(db, [module.id])
                if not chunks:
                    continue
                for bi, batch in enumerate(batch_chunks(chunks)):
                    await _progress(
                        db, job, 10 + int(60 * mi / len(modules)),
                        f"Writing questions — {module.title}",
                    )
                    ctx = build_context(batch, notes if mi == 0 and bi == 0 else None)
                    result = await generate_structured(
                        prompts.QUIZ_PROMPT.replace("{count}", str(per_module)).replace(
                            "{types}", ", ".join(types)
                        ),
                        ctx.source_text,
                        prompts.QUIZ_SCHEMA,
                    )
                    kept, d = resolve_items(
                        result.get("questions", []), ctx.index_map, scope
                    )
                    dropped += d
                    candidates.extend(kept)

            await _progress(db, job, 78, "Deduplicating and balancing")
            candidates = [
                c
                for c in candidates
                if c.item.get("qtype") in types and _question_answer(c.item) is not None
            ]
            candidates = dedup_questions(candidates)
            # round-robin balance across types up to count
            by_type: dict[str, list[ResolvedItem]] = {t: [] for t in types}
            for c in candidates:
                by_type[c.item["qtype"]].append(c)
            final: list[ResolvedItem] = []
            while len(final) < count and any(by_type.values()):
                for t in types:
                    if by_type[t] and len(final) < count:
                        final.append(by_type[t].pop(0))

            all_chunks = await load_context_chunks(db, list(scope))
            anchor_id = int(module_ids[0])
            anchor = next(m for m in modules if m.id == anchor_id)
            title = f"Quiz — {len(final)} questions"
            if len(scope) > 1:
                title += f" · {len(scope)} modules"
            artifact = Artifact(
                module_id=anchor_id,
                artifact_type=ArtifactType.quiz,
                scope_module_ids=sorted(scope),
                title=title,
                content={"types": types},
                model_name=settings.generation_model,
                prompt_version=prompts.PROMPT_VERSION,
                source_chunk_ids=[c.id for c in all_chunks],
                source_fingerprint=source_fingerprint(all_chunks),
                module_version_at_gen=anchor.content_version,
                job_id=job.id,
            )
            db.add(artifact)
            await db.flush()
            for ord_, resolved in enumerate(final):
                item = resolved.item
                db.add(
                    QuizQuestion(
                        artifact_id=artifact.id,
                        ord=ord_,
                        qtype=item["qtype"],
                        prompt=item["prompt"],
                        options=item.get("options") if item["qtype"] == "mcq" else None,
                        answer=_question_answer(item),
                        explanation=item.get("explanation"),
                    )
                )
                excerpt = f"{item['prompt']} {item.get('explanation', '')}"
                for row in _citation_rows(artifact.id, f"q:{ord_}", resolved.chunks, excerpt):
                    db.add(row)
            await _finish(db, job, artifact.id, dropped)
        except (GenerationError, Exception) as exc:  # noqa: BLE001
            log.exception("quiz generation failed")
            await db.rollback()
            await _fail(db, job, exc)
            raise
