"""GPU-queue generation tasks: summary, flashcards, quiz.

Flow per task: load scoped context from Postgres → build numbered-source
context (+ notes as emphasis-only) → schema-constrained generation →
citation resolution against the job scope (drop, never invent) → persist
artifact + citations → defer support-scoring on the cpu queue.
"""

import logging
import math
import re
from datetime import UTC, datetime

from manabi_core.models import (
    AIFeedback,
    AIFeedbackKind,
    Artifact,
    ArtifactType,
    Citation,
    DocElement,
    Flashcard,
    Job,
    JobStatus,
    Module,
    Note,
    QuizQuestion,
)
from manabi_core.retrieval import (
    ScopedChunk,
    load_chunks_by_ids,
    load_context_chunks,
    source_fingerprint,
)
from procrastinate.exceptions import JobAborted
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_ai import prompts, quizplan
from manabi_ai.app import app
from manabi_ai.config import get_settings
from manabi_ai.context import (
    batch_chunks,
    build_context,
    count_defined,
    scan_acronym_candidates,
    scan_definition_candidates,
)
from manabi_ai.db import session_factory
from manabi_ai.ollama_client import GenerationError, generate_structured
from manabi_ai.recap import recap_block, should_refresh, turns_to_fold
from manabi_ai.validators import (
    ResolvedItem,
    dedup_cards,
    dedup_questions,
    match_element_ids,
    resolve_items,
)

log = logging.getLogger("manabi_ai")

SCORE_SUPPORT_TASK = "manabi_server.tasks.score_support"  # cpu queue contract
VERIFY_OUTPUTS_TASK = "manabi_server.tasks.verify_quiz_outputs"  # cpu queue contract

# Exercise-mode generation with no material in scope: the FOCUS instructions
# alone define the topic (the enqueue guard requires them for this path).
_NO_SOURCES_TEXT = (
    "SOURCE MATERIAL: (none provided — synthesize practice exercises on the FOCUS topic alone)"
)

# Multi-item generation calls (a quiz's worth of step-by-step explanations,
# a batch of cards) produce far more output than a chat reply — reserve real
# answer space in num_ctx or the window fills and the JSON is cut off
# mid-string ("Unterminated string" after 3 attempts).
_GEN_RESPONSE_HEADROOM = 6144
# One LLM call is never asked for more questions than this; the top-up loop
# fills any shortfall. Keeps the answer inside the reserved space.
_MAX_QUESTIONS_PER_CALL = 12


async def _progress(db: AsyncSession, job: Job, pct: int, note: str) -> None:
    job.progress_pct = pct
    job.progress_note = note
    await db.commit()


async def _load_notes_text(
    db: AsyncSession, module_ids: list[int], note_ids: list[int] | None = None
) -> str | None:
    """note_ids: None = all module notes, [] = notes excluded from scope."""
    if note_ids == []:
        return None
    stmt = select(Note.title, Note.plain_text).where(Note.module_id.in_(module_ids))
    if note_ids is not None:
        stmt = stmt.where(Note.id.in_(note_ids))
    stmt = stmt.order_by(Note.module_id, Note.position, Note.id)
    rows = (await db.execute(stmt)).all()
    text = "\n\n".join(f"## {title}\n{body}" for title, body in rows if body)
    return text or None


async def _elements_for_chunks(
    db: AsyncSession, chunks: list[ScopedChunk]
) -> dict[int, list[tuple[int, str]]]:
    """chunk_id → [(element_id, text)] for precise per-claim highlighting."""
    all_ids = {eid for c in chunks for eid in c.element_ids}
    if not all_ids:
        return {}
    rows = (
        await db.execute(
            select(DocElement.id, DocElement.text_content).where(DocElement.id.in_(all_ids))
        )
    ).all()
    text_by_id = {i: (t or "") for i, t in rows}
    return {c.id: [(eid, text_by_id.get(eid, "")) for eid in c.element_ids] for c in chunks}


def _citation_rows(
    artifact_id: int,
    item_ref: str,
    chunks: list[ScopedChunk],
    excerpt: str,
    elements_by_chunk: dict[int, list[tuple[int, str]]] | None = None,
) -> list[Citation]:
    rows = []
    for c in chunks:
        element_ids = None
        if elements_by_chunk and c.id in elements_by_chunk:
            matched = match_element_ids(excerpt, elements_by_chunk[c.id])
            element_ids = matched or None
        rows.append(
            Citation(
                artifact_id=artifact_id,
                item_ref=item_ref,
                chunk_id=c.id,
                element_ids=element_ids,
                document_id=c.document_id,
                document_title=c.document_title,
                page_start=c.page_start,
                page_end=c.page_end,
                quote_excerpt=excerpt[:400],
            )
        )
    return rows


def _preview_writer(db: AsyncSession, job: Job, *, from_head: bool = False):
    """Stream the model's partial output into job.preview for the live UI.
    `from_head=True` keeps the START of the text (chat: the answer field appears
    early in the JSON, so the client can type it out from the beginning); the
    default keeps the tail (long generation JSON where only the latest matters)."""

    async def write(text: str) -> None:
        job.preview = text[:8000] if from_head else text[-6000:]
        await db.commit()

    return write


async def _finish(db: AsyncSession, job: Job, artifact_id: int, dropped: int) -> None:
    job.status = JobStatus.succeeded
    job.progress_pct = 100
    job.progress_note = "Done" + (f" ({dropped} unsupported items dropped)" if dropped else "")
    job.result = {"artifact_id": artifact_id, "dropped": dropped}
    job.preview = None
    job.finished_at = datetime.now(UTC)
    await db.commit()
    # support scoring runs on the cpu queue (needs the app server's embed model)
    await app.configure_task(SCORE_SUPPORT_TASK, queue="cpu").defer_async(artifact_id=artifact_id)
    # Output questions get checked by actually running their code — also cpu, so
    # it costs the GPU nothing and does not hold up the job the user is watching.
    await app.configure_task(VERIFY_OUTPUTS_TASK, queue="cpu").defer_async(
        artifact_id=artifact_id
    )


async def _fail(db: AsyncSession, job: Job, exc: Exception) -> None:
    job.status = JobStatus.failed
    job.error = f"{type(exc).__name__}: {str(exc)[:400]}"
    job.preview = None
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


async def _abort_if_requested(db: AsyncSession, job: Job, context) -> None:
    """Cooperative cancellation checkpoint for long tasks. When the user cancels
    a running job, procrastinate flags it for abortion; we mark our own job row
    cancelled and raise JobAborted so procrastinate does NOT retry it. Callers
    place this at loop boundaries, before any artifact is persisted."""
    if context is not None and context.should_abort():
        job.status = JobStatus.cancelled
        job.progress_note = "Cancelled"
        job.preview = None
        job.finished_at = datetime.now(UTC)
        await db.commit()
        raise JobAborted()


COVERAGE_TARGET = 0.9
EXHAUSTIVE_CARD_CAP = 150


@app.task(name="manabi_ai.tasks.generate_summary", queue="gpu", retry=1, pass_context=True)
async def generate_summary(context, job_id: int, module_id: int) -> None:
    settings = get_settings()
    async with session_factory()() as db:
        job = await _start(db, job_id)
        preview = _preview_writer(db, job)
        try:
            chunks = await load_context_chunks(db, [module_id])
            notes = await _load_notes_text(db, [module_id])
            module = (await db.execute(select(Module).where(Module.id == module_id))).scalar_one()

            candidates = scan_acronym_candidates(chunks)
            candidate_note = (
                "\nAcronym candidates found in the sources — define each one "
                f"the sources explain: {', '.join(candidates)}\n"
                if candidates
                else ""
            )
            term_candidates = scan_definition_candidates(chunks)
            term_note = (
                "\nTerm candidates found in the sources (phrases the text itself defines or "
                "explains). Make sure each one the sources define appears in key_terms with "
                "its definition — ON TOP OF every other term you would extract; this list is "
                f"a floor, never the whole set: {', '.join(term_candidates)}\n"
                if term_candidates
                else ""
            )
            base_prompt = prompts.SUMMARY_PROMPT.replace(
                "{acronym_candidates}", candidate_note
            ).replace("{term_candidates}", term_note)

            sections: list[dict] = []
            key_terms: list[dict] = []
            acronyms: list[dict] = []
            people: list[dict] = []
            overview = ""
            all_citations: list[tuple[str, list[ScopedChunk], str]] = []
            dropped = 0

            def absorb(result: dict, ctx) -> None:
                nonlocal dropped, overview
                # Whole-document overview: keep the first non-empty one (batch 0
                # opens the document; later batches only cover their slice).
                if not overview and (ov := (result.get("overview") or "").strip()):
                    overview = ov
                for section in result.get("sections", []):
                    kept, d = resolve_items(section.get("blocks", []), ctx.index_map, {module_id})
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
                    if any(t["term"].lower() == resolved.item["term"].lower() for t in key_terms):
                        continue
                    ref = f"kt:{len(key_terms)}"
                    key_terms.append(
                        {
                            "term": resolved.item["term"],
                            "definition": resolved.item["definition"],
                        }
                    )
                    excerpt = f"{resolved.item['term']}: {resolved.item['definition']}"
                    all_citations.append((ref, resolved.chunks, excerpt))

                kept_acr, d = resolve_items(result.get("acronyms", []), ctx.index_map, {module_id})
                dropped += d
                for resolved in kept_acr:
                    if any(
                        a["acronym"].lower() == resolved.item["acronym"].lower() for a in acronyms
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

                kept_people, d = resolve_items(result.get("people", []), ctx.index_map, {module_id})
                dropped += d
                for resolved in kept_people:
                    if any(p["name"].lower() == resolved.item["name"].lower() for p in people):
                        continue
                    ref = f"pep:{len(people)}"
                    people.append(
                        {
                            "name": resolved.item["name"],
                            "description": resolved.item["description"],
                        }
                    )
                    excerpt = f"{resolved.item['name']}: {resolved.item['description']}"
                    all_citations.append((ref, resolved.chunks, excerpt))

            batches = batch_chunks(chunks)
            for bi, batch in enumerate(batches):
                await _abort_if_requested(db, job, context)
                await _progress(
                    db,
                    job,
                    15 + int(50 * bi / len(batches)),
                    f"Generating with {settings.generation_model}"
                    + (f" ({bi + 1}/{len(batches)})" if len(batches) > 1 else ""),
                )
                ctx = build_context(batch, notes if bi == 0 else None)
                result = await generate_structured(
                    base_prompt,
                    ctx.source_text,
                    prompts.SUMMARY_SCHEMA,
                    preview,
                    response_headroom=_GEN_RESPONSE_HEADROOM,
                )
                absorb(result, ctx)

            # Gap pass: one extra call over passages the first pass skipped
            cited_ids = {c.id for _, cited, _ in all_citations for c in cited}
            uncited = [c for c in chunks if c.id not in cited_ids]
            if chunks and len(cited_ids) / len(chunks) < COVERAGE_TARGET and uncited:
                await _progress(db, job, 72, f"Covering {len(uncited)} missed passages")
                ctx = build_context(uncited, None)
                result = await generate_structured(
                    base_prompt + prompts.GAP_PROMPT_SUFFIX,
                    ctx.source_text,
                    prompts.SUMMARY_SCHEMA,
                    preview,
                    response_headroom=_GEN_RESPONSE_HEADROOM,
                )
                absorb(result, ctx)
                cited_ids = {c.id for _, cited, _ in all_citations for c in cited}

            await _progress(db, job, 88, "Validating citations")
            elements_by_chunk = await _elements_for_chunks(
                db, [c for _, cited, _ in all_citations for c in cited]
            )
            artifact = Artifact(
                module_id=module_id,
                artifact_type=ArtifactType.summary,
                scope_module_ids=[module_id],
                title=f"Study summary — {module.title}",
                content={
                    "overview": overview,
                    "sections": sections,
                    "key_terms": key_terms,
                    "acronyms": acronyms,
                    "people": people,
                    "coverage": {
                        "cited": len(cited_ids),
                        "total": len(chunks),
                        # how many scanned term candidates the key_terms define
                        "term_candidates": len(term_candidates),
                        "terms_hit": count_defined(term_candidates, key_terms),
                    },
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
                for row in _citation_rows(artifact.id, ref, cited, excerpt, elements_by_chunk):
                    db.add(row)
            await _finish(db, job, artifact.id, dropped)
        except JobAborted:
            raise  # cancelled — do not fail/retry
        except (GenerationError, Exception) as exc:  # noqa: BLE001
            log.exception("summary generation failed")
            await db.rollback()
            await _fail(db, job, exc)
            raise


def _deck_title(
    module_title: str,
    mode: str,
    instructions: str | None,
    document_ids: list[int] | None,
) -> str:
    if instructions:
        snippet = instructions[:48] + ("…" if len(instructions) > 48 else "")
        return f"{'Practice' if mode == 'exercise' else 'Cards'} — {snippet}"
    if mode == "exercise":
        return f"Practice — {module_title}"
    if document_ids is not None:
        n = len(document_ids)
        return f"Cards — {n} source{'s' if n != 1 else ''} · {module_title}"
    return f"Flashcards — {module_title}"


@app.task(name="manabi_ai.tasks.generate_flashcards", queue="gpu", retry=1, pass_context=True)
async def generate_flashcards(
    context,
    job_id: int,
    module_id: int,
    count: int = 12,
    document_ids: list[int] | None = None,
    note_ids: list[int] | None = None,
    instructions: str | None = None,
    mode: str = "sources",
    chunk_ids: list[int] | None = None,
) -> None:
    settings = get_settings()
    exercise = mode == "exercise"
    # A scoped/custom deck is its own study object: no summary-derived cards,
    # no carry-over from the review deck, and it stays out of the SRS queue.
    scoped = document_ids is not None or note_ids is not None or bool(instructions) or exercise
    async with session_factory()() as db:
        job = await _start(db, job_id)
        preview = _preview_writer(db, job)
        try:
            chunks: list[ScopedChunk] = []
            if chunk_ids:
                # Focused retrieval (server-side, topic-steered). Hydration
                # doesn't module-filter — re-filter as defense in depth, and
                # fall back to the document scope if it all went stale.
                chunks = [
                    c for c in await load_chunks_by_ids(db, chunk_ids) if c.module_id == module_id
                ]
            if not chunks:
                chunks = await load_context_chunks(db, [module_id], document_ids=document_ids)
            notes = await _load_notes_text(db, [module_id], note_ids=note_ids)
            module = (await db.execute(select(Module).where(Module.id == module_id))).scalar_one()

            # ── Derived cards: exact term/acronym cards from the summary ──
            summary = None
            if not scoped:
                summary = (
                    await db.execute(
                        select(Artifact)
                        .where(
                            Artifact.module_id == module_id,
                            Artifact.artifact_type == ArtifactType.summary,
                        )
                        .order_by(Artifact.id.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
            derived: list[tuple[str, str, str]] = []  # (front, back, summary item_ref)
            summary_citations: dict[str, list[Citation]] = {}
            if summary is not None:
                for row in (
                    (await db.execute(select(Citation).where(Citation.artifact_id == summary.id)))
                    .scalars()
                    .all()
                ):
                    summary_citations.setdefault(row.item_ref, []).append(row)
                for i, t in enumerate(summary.content.get("key_terms", [])):
                    if t.get("term") and t.get("definition"):
                        derived.append((f"Define: {t['term']}", t["definition"], f"kt:{i}"))
                for i, a in enumerate(summary.content.get("acronyms", [])):
                    if a.get("acronym") and a.get("meaning"):
                        derived.append(
                            (
                                f"What does {a['acronym']} stand for?",
                                a["meaning"],
                                f"ac:{i}",
                            )
                        )
            # count == 0 → exhaustive mode: keep generating until the
            # material runs dry (a round adds <3 new cards) with hard stops.
            exhaustive = count == 0
            if exhaustive:
                count = EXHAUSTIVE_CARD_CAP
            else:
                # Leave at least a quarter of the deck for conceptual/
                # enumeration/comparison cards — definitions alone aren't
                # a study kit.
                derived = derived[: max(0, count - max(4, count // 4))]

            remaining = count - len(derived)
            existing_fronts = [front for front, _, _ in derived]
            batches = batch_chunks(chunks)
            resolved_cards: list[ResolvedItem] = []
            dropped = 0

            if exercise and not chunks:
                # Topic-only practice deck: no material in scope at all.
                await _progress(
                    db,
                    job,
                    30,
                    f"Writing practice cards with {settings.generation_model}",
                )
                base_prompt = prompts.EXERCISE_FLASHCARDS_PROMPT
                if instructions:
                    base_prompt += prompts.FOCUS_BLOCK.replace("{instructions}", instructions)
                result = await generate_structured(
                    base_prompt.replace("{count}", str(min(max(remaining, 4), 20))).replace(
                        "{existing_fronts}", "(none)"
                    ),
                    _NO_SOURCES_TEXT,
                    prompts.FLASHCARDS_EXERCISE_SCHEMA,
                    preview,
                    response_headroom=_GEN_RESPONSE_HEADROOM,
                )
                kept, d = resolve_items(
                    result.get("cards", []),
                    {},
                    {module_id},
                    require_sources=False,
                )
                dropped += d
                fresh = dedup_cards(kept, existing_fronts)
                resolved_cards.extend(fresh)
                existing_fronts.extend((f.item.get("front") or "") for f in fresh)

            rounds = 0
            max_rounds = 8 if exhaustive else 3
            while batches and remaining > len(resolved_cards) and rounds < max_rounds:
                await _abort_if_requested(db, job, context)
                rounds += 1
                added_this_round = 0
                for batch in batches:
                    need = remaining - len(resolved_cards)
                    if need <= 0:
                        break
                    await _progress(
                        db,
                        job,
                        15 + min(60, 60 * rounds // max_rounds),
                        f"Creating cards with {settings.generation_model}"
                        f" ({len(derived) + len(resolved_cards)}"
                        f"/{'∞' if exhaustive else count})",
                    )
                    ctx = build_context(batch, notes)
                    fronts_note = "\n".join(f"- {f}" for f in existing_fronts[-60:]) or "(none)"
                    base_prompt = (
                        prompts.EXERCISE_FLASHCARDS_PROMPT
                        if exercise
                        else prompts.FLASHCARDS_PROMPT
                    )
                    if instructions:
                        base_prompt += prompts.FOCUS_BLOCK.replace("{instructions}", instructions)
                    result = await generate_structured(
                        base_prompt.replace("{count}", str(min(need, 20))).replace(
                            "{existing_fronts}", fronts_note
                        ),
                        ctx.source_text,
                        prompts.FLASHCARDS_EXERCISE_SCHEMA
                        if exercise
                        else prompts.FLASHCARDS_SCHEMA,
                        preview,
                        response_headroom=_GEN_RESPONSE_HEADROOM,
                    )
                    kept, d = resolve_items(
                        result.get("cards", []),
                        ctx.index_map,
                        {module_id},
                        require_sources=not exercise,
                    )
                    dropped += d
                    fresh = dedup_cards(kept, existing_fronts)
                    if not fresh:
                        continue
                    added_this_round += len(fresh)
                    resolved_cards.extend(fresh)
                    existing_fronts.extend((f.item.get("front") or "") for f in fresh)
                if exhaustive and added_this_round < 3:
                    log.info("exhaustive card generation ran dry after %d rounds", rounds)
                    break

            await _progress(db, job, 85, "Validating citations")
            # Carry over user-edited cards — only when regenerating the
            # module's review deck (scoped/custom decks are fresh objects).
            carried: list[Flashcard] = []
            if not scoped:
                previous = (
                    await db.execute(
                        select(Artifact)
                        .where(
                            Artifact.module_id == module_id,
                            Artifact.artifact_type == ArtifactType.flashcard_deck,
                            Artifact.review_enabled.is_(True),
                        )
                        .order_by(Artifact.id.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
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
                # The new whole-module deck replaces its predecessors in the
                # SRS rotation (today's "latest deck" semantics).
                await db.execute(
                    update(Artifact)
                    .where(
                        Artifact.module_id == module_id,
                        Artifact.artifact_type == ArtifactType.flashcard_deck,
                        Artifact.review_enabled.is_(True),
                    )
                    .values(review_enabled=False)
                )

            artifact = Artifact(
                module_id=module_id,
                artifact_type=ArtifactType.flashcard_deck,
                scope_module_ids=[module_id],
                title=_deck_title(module.title, mode, instructions, document_ids),
                content={},
                model_name=settings.generation_model,
                prompt_version=prompts.PROMPT_VERSION,
                source_chunk_ids=[c.id for c in chunks],
                source_fingerprint=source_fingerprint(chunks),
                module_version_at_gen=module.content_version,
                job_id=job.id,
                scope_document_ids=document_ids,
                scope_note_ids=note_ids,
                instructions=instructions,
                generation_mode=mode,
                review_enabled=not scoped,
            )
            db.add(artifact)
            await db.flush()
            elements_by_chunk = await _elements_for_chunks(
                db, [c for r in resolved_cards for c in r.chunks]
            )
            ord_ = 0
            # Derived term/acronym cards: exact content, summary's citations cloned
            for front, back, ref in derived:
                db.add(Flashcard(artifact_id=artifact.id, ord=ord_, front=front, back=back))
                for src in summary_citations.get(ref, []):
                    db.add(
                        Citation(
                            artifact_id=artifact.id,
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
                ord_ += 1
            for resolved in resolved_cards[: max(0, count - len(derived))]:
                db.add(
                    Flashcard(
                        artifact_id=artifact.id,
                        ord=ord_,
                        front=resolved.item["front"],
                        back=resolved.item["back"],
                    )
                )
                excerpt = f"{resolved.item['front']} {resolved.item['back']}"
                for row in _citation_rows(
                    artifact.id, f"card:{ord_}", resolved.chunks, excerpt, elements_by_chunk
                ):
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
        except JobAborted:
            raise  # cancelled — do not fail/retry
        except (GenerationError, Exception) as exc:  # noqa: BLE001
            log.exception("flashcard generation failed")
            await db.rollback()
            await _fail(db, job, exc)
            raise


_FENCED_CODE = re.compile(r"```[A-Za-z0-9_+#-]*\n.*?\S.*?```", re.DOTALL)

# Answers that cannot be an "exact output": placeholders the model substitutes
# when it knows the real value is unknowable, and words admitting as much.
_NON_DETERMINISTIC = re.compile(
    r"(<[^>\n]{2,40}>"  # <some address>, <garbage>, <undefined>
    r"|\b(?:some|an?|the)\s+(?:memory\s+)?address\b"
    r"|\b(?:varies|random|garbage|undefined|indeterminate|unpredictable)\b"
    r"|\bdepends on\b"
    r"|\bimplementation[- ]defined\b"
    r"|\bmay differ\b)",
    re.I,
)


def fold_code_into_prompt(item: dict) -> None:
    """Move a question's `code` field into its prompt as a fenced block.

    The model reliably writes a stem referring to code ("Analyze the following
    C code snippet…") and then omits the snippet, leaving a question nobody can
    answer and nothing can verify. Giving it a dedicated optional slot to put
    the code in, and assembling the prompt here, turns that from a formatting
    instruction it ignores into a field it fills. Mutates `item` in place; safe
    to call on every question of any type.
    """
    code = (item.get("code") or "").strip()
    if not code:
        return
    prompt = item.get("prompt") or ""
    if "```" in prompt:  # already inline — nothing to do
        return
    # Tag every fence with its real language — an untagged mcq snippet could
    # not be run, and C++ fenced as ```c would not compile.
    fence = code if code.startswith("```") else f"```{code_lang(code)}\n{code}\n```"
    item["prompt"] = f"{prompt.rstrip()}\n\n{fence}"


_CPP_HINT = re.compile(
    r"#include\s*<(?:iostream|string|vector|iomanip|sstream|memory)>|\bstd::|\bcout\b"
    r"|\bcin\b|\bclass\s+\w+|\bvirtual\b|\bpublic\s*:|\bprivate\s*:|\bnamespace\b|::"
)
_PY_HINT = re.compile(r"^\s*(?:def |print\(|for \w+ in |import )", re.M)


def code_lang(code: str) -> str:
    """The fence tag for a snippet: cpp, c, python — or "" when unsure."""
    if _CPP_HINT.search(code):
        return "cpp"
    if re.search(r"#include|printf\s*\(|\bint\s+main\s*\(|;\s*$", code, re.M):
        return "c"
    if _PY_HINT.search(code):
        return "python"
    return ""


# Capital letters only: "(a)" is code (`max(a)`), "(A)" / "option B" is a label.
_NAMES_A_LETTER = re.compile(r"\b(?i:option|choice|answer)\s*\(?[A-D]\)?(?!\w)|\([A-D]\)")


def shuffle_mcq(item: dict) -> None:
    """Reorder an mcq's options deterministically (keyed on its prompt) so the
    right answer is not almost always A or B. Skipped when the explanation
    names an option by letter, which a shuffle would make wrong."""
    if item.get("qtype") != "mcq" or not isinstance(item.get("correct_option"), int):
        return
    text = f"{item.get('explanation') or ''} {item.get('working') or ''}"
    if _NAMES_A_LETTER.search(text):
        return
    opts, key = quizplan.shuffle_options(
        list(item.get("options") or []), item["correct_option"], item.get("prompt") or ""
    )
    item["options"], item["correct_option"] = opts, key


def finalize_question(item: dict) -> dict:
    """Shape a raw generated question for storage: fold its code into the
    prompt, and fall back to the working when the clean explanation is empty.
    Mutates and returns `item`."""
    fold_code_into_prompt(item)
    explanation = (item.get("explanation") or "").strip()
    if not explanation:
        item["explanation"] = (item.get("working") or "").strip()
    topic = (item.get("topic") or "").strip()
    item["topic"] = topic[:120] or None
    return item


_IDENTIFICATION_MAX_WORDS = 6  # "Term Frequency-Inverse Document Frequency" is 4


def _question_answer(item: dict) -> dict | None:
    qtype = item.get("qtype")
    if qtype == "mcq":
        options = item.get("options") or []
        correct = item.get("correct_option")
        if len(options) >= 2 and isinstance(correct, int) and 0 <= correct < len(options):
            return {"kind": "mcq", "correct_option": correct}
        return None
    if qtype == "tf":
        # A true/false item must be a statement. A real one asked "what is
        # the memory address of p + 3?" and was keyed True.
        stem = _FENCED_CODE.sub(" ", item.get("prompt") or "").strip()
        if stem.endswith("?") and not re.search(r"true|false", stem, re.I):
            return None
        # ...and not a multiple-choice question in disguise (a real one listed
        # options A) to D) inside a tf stem).
        if re.search(r"which of the following", stem, re.I) or len(
            re.findall(r"^\s*[A-D][).]\s", stem, re.M)
        ) >= 2:
            return None
        if isinstance(item.get("correct_bool"), bool):
            return {"kind": "tf", "value": item["correct_bool"]}
        return None
    if qtype == "short":
        if item.get("correct_text"):
            return {"kind": "short", "text": item["correct_text"]}
        return None
    if qtype == "enumeration":
        items = [
            s.strip() for s in (item.get("correct_items") or []) if isinstance(s, str) and s.strip()
        ]
        if len(items) >= 2:
            return {"kind": "enumeration", "items": items}
        return None
    if qtype == "identification":
        text = (item.get("correct_text") or "").strip()
        # The answer is a term. A real one asked "how does RAG address
        # hallucinations?" and keyed a whole sentence no typed answer matches.
        if not text or len(text.split()) > _IDENTIFICATION_MAX_WORDS:
            return None
        return {"kind": "identification", "text": text}
    if qtype == "essay":
        if item.get("correct_text"):
            return {
                "kind": "essay",
                "model_answer": item["correct_text"],
                "key_points": [
                    s.strip()
                    for s in (item.get("key_points") or [])
                    if isinstance(s, str) and s.strip()
                ],
            }
        return None
    if qtype == "coding":
        if item.get("correct_text"):
            return {"kind": "coding", "solution": item["correct_text"]}
        return None
    if qtype == "output":
        text = item.get("correct_text")
        if not text:
            return None
        # A question that says "the following C code" and then shows none is
        # not a question. Observed in a real run: the model wrote the stem and
        # simply omitted the snippet, and because nothing checked, it shipped —
        # and the executor then had nothing to verify against, so it passed
        # silently too.
        if not _FENCED_CODE.search(item.get("prompt") or ""):
            return None
        # "Exact output" and a non-deterministic value cannot both be true. The
        # same run produced the answer "10\n10\n<some address>" for code that
        # prints a pointer — unanswerable by construction.
        if _NON_DETERMINISTIC.search(text):
            return None
        return {"kind": "output", "text": text}
    return None


_TARGETS_PER_CALL = 6  # questions written per call against a plan
_OVERSAMPLE = 1.3  # targets planned per question owed (validation/dedup/audit eat some)
_AUDIT_PER_CALL = 6


def _targets_lines(targets: list[dict], qtypes: list[str]) -> str:
    return "\n".join(
        f"{i}. [{qt}] {(t.get('topic') or '').strip()} — {(t.get('skill') or '').strip()}"
        for i, (t, qt) in enumerate(zip(targets, qtypes, strict=True), start=1)
    )


async def _write_planned(
    db: AsyncSession,
    job: Job,
    preview,
    *,
    base_prompt: str,
    source_text: str,
    index_map: dict,
    types: list[str],
    mix: dict[str, float],
    need: int,
    instructions: str | None,
    exercise: bool,
    scope: set[int],
    label: str,
    avoid: list[str] | None = None,
) -> tuple[list[ResolvedItem], int]:
    """Plan `need`×oversample distinct targets from one context, give each a
    type, then write one question per target. Falls back to an unplanned ask
    when the plan comes back empty."""
    n_targets = max(need + 1, math.ceil(need * _OVERSAMPLE))
    avoid_block = (
        "\n\nDo NOT duplicate or trivially rephrase any of these existing questions:\n"
        + "\n".join(f"- {p[:120]}" for p in avoid[-30:])
        if avoid
        else ""
    )
    await _progress(db, job, job.progress_pct or 10, f"Planning questions — {label}")
    focus = (
        f"\nThe student asked for this focus — plan only targets within it:\n{instructions}\n"
        if instructions
        else ""
    )
    # The mix decides how many targets must be code: without saying so, a
    # planner on a pointers lecture marked most targets theory and the
    # requested output questions spilled into mcq.
    code_share = sum(w for t, w in mix.items() if t in quizplan.CODE_ONLY_TYPES) / max(
        1e-9, sum(mix.values())
    )
    code_need = math.ceil(n_targets * code_share)
    if code_need:
        focus += (
            f"\nAt least {code_need} of the {n_targets} targets MUST be code_based: a skill "
            "best tested by showing a short program and asking exactly what it prints.\n"
        )
    targets: list[dict] = []
    try:
        plan = await generate_structured(
            prompts.QUIZ_PLAN_PROMPT.replace("{count}", str(n_targets)).replace("{focus}", focus)
            + avoid_block,
            source_text,
            prompts.QUIZ_PLAN_SCHEMA,
            preview,
            response_headroom=3072,
        )
        targets = [
            t for t in plan.get("targets", []) if (t.get("topic") or "").strip()
        ][:n_targets]
    except GenerationError:
        log.warning("quiz plan failed for %s — writing unplanned", label)
    if not targets:
        targets = [{"topic": "", "skill": "", "code_based": True}] * n_targets
        planned = False
    else:
        planned = True
    qtypes = quizplan.assign_types([bool(t.get("code_based")) for t in targets], mix)

    kept_all: list[ResolvedItem] = []
    dropped = 0
    # Write each type's targets in their own calls, with the grammar narrowed
    # to that one type. Mixed calls let the model answer an [output] target
    # with an mcq (observed: 1 output of 8 when 4 were asked for).
    calls: list[tuple[list[dict], list[str]]] = []
    if planned:
        for qt in dict.fromkeys(qtypes):
            group = [t for t, q in zip(targets, qtypes, strict=True) if q == qt]
            for start in range(0, len(group), _TARGETS_PER_CALL):
                part = group[start : start + _TARGETS_PER_CALL]
                calls.append((part, [qt] * len(part)))
    else:
        for start in range(0, len(targets), _TARGETS_PER_CALL):
            end = start + _TARGETS_PER_CALL
            calls.append((targets[start:end], qtypes[start:end]))
    written = 0
    for chunk_t, chunk_q in calls:
        start = written
        written += len(chunk_t)
        call_types = [t for t in types if t in set(chunk_q)] or types
        system = base_prompt.replace("{count}", str(len(chunk_t))).replace(
            "{types}", ", ".join(call_types)
        )
        if planned:
            system += prompts.TARGETS_BLOCK.replace("{targets}", _targets_lines(chunk_t, chunk_q))
        system += avoid_block
        await _progress(
            db,
            job,
            job.progress_pct or 10,
            f"Writing questions {start + 1}-{start + len(chunk_t)} of {len(targets)} — {label}",
        )
        try:
            result = await generate_structured(
                system,
                source_text,
                prompts.quiz_schema_for(call_types, exercise=exercise),
                preview,
                response_headroom=_GEN_RESPONSE_HEADROOM,
            )
        except GenerationError as exc:
            # One bad batch must not sink a 50-question exam; the top-up
            # pass refills the shortfall.
            log.warning("quiz batch failed (%s): %s", label, exc)
            continue
        raw = result.get("questions", [])
        for i, q in enumerate(raw):
            finalize_question(q)
            if not q.get("topic") and planned and i < len(chunk_t):
                q["topic"] = (chunk_t[i].get("topic") or "")[:120] or None
        kept, d = resolve_items(raw, index_map, scope, require_sources=not exercise)
        dropped += d
        kept_all.extend(kept)
    return kept_all, dropped


def _audit_block(items: list[ResolvedItem]) -> str:
    lines = []
    for n, r in enumerate(items, start=1):
        q = r.item
        label = {"mcq": "multiple choice", "tf": "true/false"}.get(q["qtype"], "short answer")
        lines.append(f"QUESTION {n} ({label}):\n{q.get('prompt', '').strip()}")
        if q["qtype"] == "mcq":
            for i, opt in enumerate(q.get("options") or []):
                lines.append(f"  [{i}] {opt}")
    return "\n\n".join(lines)


def _solved_display(qtype: str, solved: dict, options: list | None) -> str:
    if qtype == "mcq":
        i = solved.get("answer_option")
        opts = options or []
        return f"option {i}: {opts[i]}" if isinstance(i, int) and 0 <= i < len(opts) else "?"
    if qtype == "tf":
        return "true" if solved.get("answer_bool") else "false"
    return solved.get("answer_text") or ""


def _apply_solve(item: dict, solved: dict) -> bool:
    """Move a question's key to the blind solver's answer. False when the
    solve cannot be expressed as a key for this question."""
    qtype = item["qtype"]
    if qtype == "mcq":
        i = solved.get("answer_option")
        if isinstance(i, int) and 0 <= i < len(item.get("options") or []):
            item["correct_option"] = i
            return True
        return False
    if qtype == "tf":
        item["correct_bool"] = bool(solved.get("answer_bool"))
        return True
    text = (solved.get("answer_text") or "").strip()
    if text:
        item["correct_text"] = text
        return True
    return False


async def _audit_candidates(
    db: AsyncSession,
    job: Job,
    preview,
    candidates: list[tuple[int, ResolvedItem]],
    source_by_unit: dict[int, str],
) -> tuple[list[tuple[int, ResolvedItem]], dict]:
    """Solve every objective, non-executable question blind and compare with
    its key. A disagreement goes to an adjudicator that sees both answers; the
    key is kept, moved to the solver's answer, or the question is dropped.

    Code-output questions are skipped — the app server runs their code, which
    beats any model. Returns the surviving candidates and audit counts."""
    stats = {"audited": 0, "agreed": 0, "upheld": 0, "corrected": 0, "dropped": 0}
    todo: dict[int, list[ResolvedItem]] = {}
    for ui, r in candidates:
        q = r.item
        if q["qtype"] in quizplan.AUDITABLE_TYPES and not quizplan.executable_check_applies(
            q["qtype"], q.get("prompt") or ""
        ):
            todo.setdefault(ui, []).append(r)
    total = sum(len(v) for v in todo.values())
    done = 0
    dropped_ids: set[int] = set()
    for ui, items in todo.items():
        source = source_by_unit.get(ui) or _NO_SOURCES_TEXT
        for start in range(0, len(items), _AUDIT_PER_CALL):
            batch = items[start : start + _AUDIT_PER_CALL]
            await _progress(
                db, job, 82, f"Checking answers {done + 1}-{done + len(batch)} of {total}"
            )
            done += len(batch)
            try:
                solved = await generate_structured(
                    prompts.AUDIT_SOLVE_PROMPT,
                    source + "\n\n" + _audit_block(batch),
                    prompts.AUDIT_SOLVE_SCHEMA,
                    preview,
                    response_headroom=4096,
                )
            except GenerationError as exc:
                log.warning("quiz audit batch failed: %s", exc)
                continue
            by_n = {a.get("n"): a for a in solved.get("answers", []) if isinstance(a, dict)}
            for n, r in enumerate(batch, start=1):
                a = by_n.get(n)
                if a is None:
                    continue  # unsolved — keep, unaudited
                stats["audited"] += 1
                answer = _question_answer(r.item) or {}
                if quizplan.answers_agree(r.item["qtype"], answer, a):
                    stats["agreed"] += 1
                    r.item["_audit"] = "agreed"
                    continue
                verdict = await _adjudicate(r.item, answer, a, source)
                if verdict is None:
                    continue  # adjudication failed — keep the key as written
                if verdict.get("stored_answer_correct"):
                    stats["upheld"] += 1
                    r.item["_audit"] = "upheld"
                elif verdict.get("user_answer_correct") and _apply_solve(r.item, a):
                    stats["corrected"] += 1
                    r.item["_audit"] = "corrected"
                    why = (verdict.get("verdict") or "").strip()
                    work = (a.get("working") or "").strip()
                    r.item["explanation"] = "\n\n".join(x for x in (why, work) if x)
                else:
                    stats["dropped"] += 1
                    dropped_ids.add(id(r))
    kept = [(ui, r) for ui, r in candidates if id(r) not in dropped_ids]
    return kept, stats


async def _adjudicate(item: dict, answer: dict, solved: dict, source: str) -> dict | None:
    options = item.get("options") if item["qtype"] == "mcq" else None
    block = (
        f"QUESTION ({item['qtype']}):\n{item.get('prompt', '')}\n\n"
        + (f"OPTIONS: {options}\n\n" if options else "")
        + f"STORED ANSWER: {_answer_display(answer, options)}\n"
        + f"STORED EXPLANATION: {item.get('working') or item.get('explanation') or '(none)'}\n\n"
        + f"STUDENT'S ANSWER: {_solved_display(item['qtype'], solved, options)}\n"
        + f"STUDENT'S WORKING: {solved.get('working') or '(none)'}\n\n"
        + source
    )
    try:
        return await generate_structured(
            prompts.VERIFY_QUESTION_PROMPT,
            block,
            prompts.VERIFY_QUESTION_SCHEMA,
            response_headroom=2048,
        )
    except GenerationError as exc:
        log.warning("adjudication failed: %s", exc)
        return None


@app.task(name="manabi_ai.tasks.generate_quiz", queue="gpu", retry=1, pass_context=True)
async def generate_quiz(
    context,
    job_id: int,
    module_ids: list[int],
    types: list[str],
    count: int = 10,
    document_ids: list[int] | None = None,
    note_ids: list[int] | None = None,
    instructions: str | None = None,
    mode: str = "sources",
    chunk_ids: list[int] | None = None,
    type_mix: dict | None = None,
    exam: bool = False,
    audit: bool = True,
    role: str | None = None,
    plan_id: int | None = None,
) -> None:
    """Plan → write → check → select.

    The material is split into units (module × context batch); each unit owes
    a share of `count` proportional to its size. Per unit, a planning call
    lists distinct targets, each target gets a type from `type_mix`, and one
    question is written per target. Objective questions are then solved blind
    and disputed keys adjudicated (`audit`); code questions are checked by
    running their code afterwards on the cpu queue. An `exam` is the same quiz
    spanning modules, kept in module order."""
    settings = get_settings()
    exercise = mode == "exercise"
    async with session_factory()() as db:
        job = await _start(db, job_id)
        preview = _preview_writer(db, job)
        try:
            order = [int(m) for m in module_ids]
            scope = set(order)
            notes = await _load_notes_text(db, list(scope), note_ids=note_ids)
            found = {
                m.id: m
                for m in (
                    await db.execute(select(Module).where(Module.id.in_(scope)))
                ).scalars()
            }
            modules = [found[m] for m in order if m in found]
            mix = quizplan.normalize_mix(types, type_mix)

            # Focused retrieval (server-side, topic-steered): partition the
            # hydrated chunks per module; a module the topic doesn't touch
            # simply contributes nothing.
            focus_by_module: dict[int, list[ScopedChunk]] | None = None
            if chunk_ids:
                hydrated = [
                    c for c in await load_chunks_by_ids(db, chunk_ids) if c.module_id in scope
                ]
                if hydrated:
                    focus_by_module = {}
                    for c in hydrated:
                        focus_by_module.setdefault(c.module_id, []).append(c)

            base_prompt = prompts.EXERCISE_QUIZ_PROMPT if exercise else prompts.QUIZ_PROMPT
            if instructions:
                base_prompt += prompts.FOCUS_BLOCK.replace("{instructions}", instructions)
            # Exercise stems legitimately look alike ("Trace this code…" with
            # different snippets) — practice quizzes dedup at 0.9.
            dedup_threshold = 0.9 if exercise else 0.8

            # 1. The material as units (module, batch of chunks).
            units: list[tuple[Module, list[ScopedChunk]]] = []
            used_chunks: list[ScopedChunk] = []
            for module in modules:
                await _abort_if_requested(db, job, context)
                if focus_by_module is not None:
                    chunks = focus_by_module.get(module.id, [])
                else:
                    chunks = await load_context_chunks(db, [module.id], document_ids=document_ids)
                if not chunks:
                    continue
                used_chunks.extend(chunks)
                for batch in batch_chunks(chunks):
                    units.append((module, batch))

            # 2. What each unit owes. Modules count equally — a generated
            # 40-question exam drew 20 from the one module with long readings
            # when shares followed text length — and within a module, its
            # context batches split that module's share by size.
            module_order = list(dict.fromkeys(m.id for m, _b in units))
            per_module = quizplan.allocate(count, {mid: 1 for mid in module_order}, minimum=1)
            owed: dict[int, int] = {}
            for mid in module_order:
                mine = {
                    i: sum(len(c.text) for c in b) for i, (m, b) in enumerate(units) if m.id == mid
                }
                owed.update(quizplan.allocate(per_module[mid], mine))
            candidates: list[tuple[int, ResolvedItem]] = []
            source_by_unit: dict[int, str] = {}
            index_by_unit: dict[int, dict] = {}
            dropped = 0
            for ui, (module, batch) in enumerate(units):
                await _abort_if_requested(db, job, context)
                if owed.get(ui, 0) <= 0:
                    continue
                ctx = build_context(batch, notes if ui == 0 else None)
                source_by_unit[ui] = ctx.source_text
                index_by_unit[ui] = ctx.index_map
                job.progress_pct = 10 + int(65 * ui / max(1, len(units)))
                kept, d = await _write_planned(
                    db,
                    job,
                    preview,
                    base_prompt=base_prompt,
                    source_text=ctx.source_text,
                    index_map=ctx.index_map,
                    types=types,
                    mix=mix,
                    need=owed[ui],
                    instructions=instructions,
                    exercise=exercise,
                    scope=scope,
                    label=module.title,
                )
                dropped += d
                candidates.extend((ui, k) for k in kept)

            if exercise and not units:
                # Topic-only practice quiz: no material in scope at all.
                ui = 0
                owed = {0: count}
                source_by_unit[0] = _NO_SOURCES_TEXT
                index_by_unit[0] = {}
                job.progress_pct = 15
                kept, d = await _write_planned(
                    db,
                    job,
                    preview,
                    base_prompt=base_prompt,
                    source_text=_NO_SOURCES_TEXT,
                    index_map={},
                    types=types,
                    mix=mix,
                    need=count,
                    instructions=instructions,
                    exercise=True,
                    scope=scope,
                    label="practice",
                )
                dropped += d
                candidates.extend((0, k) for k in kept)

            def usable(pairs: list[tuple[int, ResolvedItem]]) -> list[tuple[int, ResolvedItem]]:
                return [
                    (u, c)
                    for u, c in pairs
                    if c.item.get("qtype") in types and _question_answer(c.item) is not None
                ]

            def dedup(
                pairs: list[tuple[int, ResolvedItem]], against: list[ResolvedItem] | None = None
            ) -> list[tuple[int, ResolvedItem]]:
                base = list(against or [])
                survivors = dedup_questions(base + [c for _u, c in pairs], dedup_threshold)
                alive = {id(c) for c in survivors[len(base) :]}
                return [(u, c) for u, c in pairs if id(c) in alive]

            # 3. Validate, dedup, audit.
            await _progress(db, job, 78, "Deduplicating")
            candidates = dedup(usable(candidates))
            audit_stats: dict = {}
            if audit and candidates:
                candidates, audit_stats = await _audit_candidates(
                    db, job, preview, candidates, source_by_unit
                )

            # 4. Select: each unit gives what it owes; shortfalls are filled
            # from other units' spares, in unit order.
            Pair = tuple[int, ResolvedItem]

            def select_final(pairs: list[Pair]) -> list[Pair]:
                picked = quizplan.select_by_quota(
                    [(u, c.item["qtype"]) for u, c in pairs], owed, mix, count
                )
                return [pairs[i] for i in picked]

            final = select_final(candidates)

            # 5. Top up: re-plan for the shortfall in the units that fell
            # furthest behind, until full or a round adds nothing.
            topup_rounds = 0
            while len(final) < count and topup_rounds < 3 and source_by_unit:
                await _abort_if_requested(db, job, context)
                topup_rounds += 1
                have: dict[int, int] = {}
                for u, _c in final:
                    have[u] = have.get(u, 0) + 1
                ui = max(source_by_unit, key=lambda u: owed.get(u, 0) - have.get(u, 0))
                shortfall = count - len(final)
                await _progress(db, job, 88, f"Topping up questions ({len(final)}/{count})")
                kept, d = await _write_planned(
                    db,
                    job,
                    preview,
                    base_prompt=base_prompt,
                    source_text=source_by_unit[ui],
                    index_map=index_by_unit[ui],
                    types=types,
                    mix=mix,
                    need=shortfall,
                    instructions=instructions,
                    exercise=exercise,
                    scope=scope,
                    label=units[ui][0].title if units else "practice",
                    avoid=[c.item.get("prompt") or "" for _u, c in final],
                )
                dropped += d
                fresh = dedup(usable([(ui, k) for k in kept]), [c for _u, c in final])
                if audit and fresh:
                    fresh, more = await _audit_candidates(db, job, preview, fresh, source_by_unit)
                    for k, v in more.items():
                        audit_stats[k] = audit_stats.get(k, 0) + v
                if not fresh:
                    log.info(
                        "quiz top-up ran dry after %d rounds (%d/%d)",
                        topup_rounds,
                        len(final),
                        count,
                    )
                    break
                final.extend(fresh[: count - len(final)])

            # Exams read in module order (stable within a module).
            final.sort(key=lambda pair: pair[0])

            anchor_id = order[0]
            anchor = found[anchor_id]
            kind = "Mock exam" if exam or role == "final" else "Quiz"
            if role == "checkpoint":
                kind = "Topic test"
            elif role and role.startswith("section:"):
                kind = "Section check"
            title = f"{kind} — {len(final)} questions"
            if len(scope) > 1:
                title += f" · {len(scope)} modules"
            if instructions:
                title += " · " + instructions[:40] + ("…" if len(instructions) > 40 else "")
            elif exercise and not exam:
                title += " · practice"
            artifact = Artifact(
                module_id=anchor_id,
                artifact_type=ArtifactType.quiz,
                scope_module_ids=order,
                title=title,
                content={
                    "types": types,
                    "type_mix": mix,
                    "exam": exam,
                    "audit": audit_stats,
                    "role": role,
                    "plan_id": plan_id,
                },
                model_name=settings.generation_model,
                prompt_version=prompts.PROMPT_VERSION,
                source_chunk_ids=[c.id for c in used_chunks],
                source_fingerprint=source_fingerprint(used_chunks),
                module_version_at_gen=anchor.content_version,
                job_id=job.id,
                scope_document_ids=document_ids,
                scope_note_ids=note_ids,
                instructions=instructions,
                generation_mode=mode,
            )
            db.add(artifact)
            await db.flush()
            elements_by_chunk = await _elements_for_chunks(
                db, [c for _u, r in final for c in r.chunks]
            )
            for ord_, (ui, resolved) in enumerate(final):
                item = resolved.item
                shuffle_mcq(item)
                answer = _question_answer(item)
                if item.get("_audit"):
                    answer = {**answer, "audit": item["_audit"]}
                db.add(
                    QuizQuestion(
                        artifact_id=artifact.id,
                        ord=ord_,
                        qtype=item["qtype"],
                        prompt=item["prompt"],
                        options=item.get("options") if item["qtype"] == "mcq" else None,
                        answer=answer,
                        explanation=item.get("explanation"),
                        topic=item.get("topic"),
                        module_id=units[ui][0].id if units else None,
                    )
                )
                excerpt = f"{item['prompt']} {item.get('explanation', '')}"
                for row in _citation_rows(
                    artifact.id, f"q:{ord_}", resolved.chunks, excerpt, elements_by_chunk
                ):
                    db.add(row)
            await _finish(db, job, artifact.id, dropped)
        except JobAborted:
            raise  # cancelled — do not fail/retry
        except (GenerationError, Exception) as exc:  # noqa: BLE001
            log.exception("quiz generation failed")
            await db.rollback()
            await _fail(db, job, exc)
            raise


def _answer_display(answer: dict | None, options: list | None) -> str:
    """Human-readable form of a stored QuizQuestion.answer for prompts."""
    if not answer:
        return "(none)"
    kind = answer.get("kind")
    if kind == "mcq":
        i = answer.get("correct_option")
        opts = options or []
        label = opts[i] if isinstance(i, int) and 0 <= i < len(opts) else "?"
        return f"option {i}: {label}"
    if kind == "tf":
        return "true" if answer.get("value") else "false"
    if kind == "enumeration":
        return "; ".join(answer.get("items") or [])
    if kind == "essay":
        return answer.get("model_answer") or ""
    if kind == "coding":
        return answer.get("solution") or ""
    return answer.get("text") or ""  # short / identification / output


@app.task(name="manabi_ai.tasks.verify_question", queue="gpu", retry=1)
async def verify_question(job_id: int, question_id: int, user_answer: str = "") -> None:
    """Student disputes a generated answer: re-adjudicate it against the
    question's own cited sources (when it has any) and report who is right.
    Informational only — nothing is mutated; a wrong question is fixed via
    regenerate_question."""
    settings = get_settings()
    async with session_factory()() as db:
        job = await _start(db, job_id)
        preview = _preview_writer(db, job)
        try:
            question = (
                await db.execute(select(QuizQuestion).where(QuizQuestion.id == question_id))
            ).scalar_one()
            artifact = (
                await db.execute(select(Artifact).where(Artifact.id == question.artifact_id))
            ).scalar_one()
            cited_chunk_ids = [
                cid
                for (cid,) in (
                    await db.execute(
                        select(Citation.chunk_id).where(
                            Citation.artifact_id == artifact.id,
                            Citation.item_ref == f"q:{question.ord}",
                            Citation.chunk_id.is_not(None),
                        )
                    )
                ).all()
            ]
            chunks = await load_chunks_by_ids(db, cited_chunk_ids) if cited_chunk_ids else []
            source_text = (
                build_context(chunks, None).source_text
                if chunks
                else "SOURCE MATERIAL: (none — synthesized practice item; "
                "judge by re-deriving the answer)"
            )
            options_line = f"OPTIONS: {question.options}\n\n" if question.options else ""
            user_block = (
                f"QUESTION ({question.qtype}):\n{question.prompt}\n\n"
                + options_line
                + f"STORED ANSWER: {_answer_display(question.answer, question.options)}\n"
                + f"STORED EXPLANATION: {question.explanation or '(none)'}\n\n"
                + f"STUDENT'S ANSWER: {user_answer.strip() or '(blank)'}\n\n"
                + source_text
            )
            await _progress(db, job, 30, "Double-checking the answer")
            result = await generate_structured(
                prompts.VERIFY_QUESTION_PROMPT,
                user_block,
                prompts.VERIFY_QUESTION_SCHEMA,
                preview,
                model=settings.effective_chat_model,
            )
            job.status = JobStatus.succeeded
            job.progress_pct = 100
            job.progress_note = "Done"
            job.preview = None
            verdict = {
                "stored_answer_correct": bool(result.get("stored_answer_correct")),
                "user_answer_correct": bool(result.get("user_answer_correct")),
                "explanation": (result.get("verdict") or "").strip(),
                "corrected_answer": (result.get("corrected_answer") or "").strip(),
            }
            job.result = {"verdict": verdict}
            # A dispute is the richest label here: an explicit challenge plus an
            # adjudication. It used to live only in jobs.result, with no way
            # back to the question it was about.
            if not verdict["stored_answer_correct"]:
                db.add(
                    AIFeedback(
                        kind=AIFeedbackKind.answer_disputed,
                        artifact_id=question.artifact_id,
                        question_id=question.id,
                        rejected={"prompt": question.prompt, "answer": question.answer},
                        preferred={"answer": verdict["corrected_answer"] or None, **verdict},
                        model_name=settings.effective_chat_model,
                        prompt_version=prompts.PROMPT_VERSION,
                    )
                )
            job.finished_at = datetime.now(UTC)
            await db.commit()
        except (GenerationError, Exception) as exc:  # noqa: BLE001
            log.exception("answer verification failed")
            await db.rollback()
            await _fail(db, job, exc)
            raise


@app.task(name="manabi_ai.tasks.regenerate_question", queue="gpu", retry=1)
async def regenerate_question(job_id: int, question_id: int) -> None:
    """Replace ONE quiz question in place: same type, same quiz scope and
    mode, avoiding duplicates of the quiz's other questions. Citations for
    the question's item_ref are rebuilt; the artifact itself is untouched."""
    async with session_factory()() as db:
        job = await _start(db, job_id)
        preview = _preview_writer(db, job)
        try:
            question = (
                await db.execute(select(QuizQuestion).where(QuizQuestion.id == question_id))
            ).scalar_one()
            artifact = (
                await db.execute(select(Artifact).where(Artifact.id == question.artifact_id))
            ).scalar_one()
            scope = {int(m) for m in artifact.scope_module_ids}
            exercise = artifact.generation_mode == "exercise"

            # Rebuild the exact context the quiz was generated from; fall back
            # to the stored scope if those chunks no longer exist.
            chunks = [
                c
                for c in await load_chunks_by_ids(
                    db, [int(cid) for cid in artifact.source_chunk_ids]
                )
                if c.module_id in scope
            ]
            if not chunks and not exercise:
                chunks = await load_context_chunks(
                    db, sorted(scope), document_ids=artifact.scope_document_ids
                )
            # An exam question belongs to one module: replace it from that
            # module's material, or a Syntax & Translation slot comes back as
            # a C stack question (observed).
            if question.module_id is not None:
                own = [c for c in chunks if c.module_id == question.module_id]
                if not own:
                    own = await load_context_chunks(db, [question.module_id])
                chunks = own or chunks
            batch = batch_chunks(chunks)[0] if chunks else []
            ctx = build_context(batch, None) if batch else None

            existing = [
                p
                for (p,) in (
                    await db.execute(
                        select(QuizQuestion.prompt).where(QuizQuestion.artifact_id == artifact.id)
                    )
                ).all()
            ]
            avoid = "\n".join(f"- {p[:120]}" for p in existing[-30:]) or "(none)"
            base_prompt = prompts.EXERCISE_QUIZ_PROMPT if exercise else prompts.QUIZ_PROMPT
            if artifact.instructions:
                base_prompt += prompts.FOCUS_BLOCK.replace("{instructions}", artifact.instructions)
            base_prompt = (
                base_prompt.replace("{count}", "1").replace("{types}", question.qtype)
                + "\n\nDo NOT duplicate or trivially rephrase any of these existing "
                "questions:\n" + avoid
            )

            await _progress(db, job, 30, "Writing a replacement question")
            new_item: dict | None = None
            resolved_chunks: list[ScopedChunk] = []
            for _ in range(2):
                result = await generate_structured(
                    base_prompt,
                    ctx.source_text if ctx else _NO_SOURCES_TEXT,
                    prompts.quiz_schema_for([question.qtype], exercise=exercise),
                    preview,
                    response_headroom=2048,  # single question + working
                )
                for q in result.get("questions", []):
                    finalize_question(q)
                kept, _d = resolve_items(
                    result.get("questions", []),
                    ctx.index_map if ctx else {},
                    scope,
                    require_sources=not exercise,
                )
                for cand in kept:
                    if (
                        cand.item.get("qtype") == question.qtype
                        and _question_answer(cand.item) is not None
                    ):
                        new_item, resolved_chunks = cand.item, cand.chunks
                        break
                if new_item is not None:
                    break
            if new_item is None:
                raise GenerationError("Could not generate a valid replacement question")

            # Log what is about to be overwritten. The replacement happens in
            # place, so without this the rejected question - the clearest
            # "this one was wrong" label the app produces - is simply gone.
            db.add(
                AIFeedback(
                    kind=AIFeedbackKind.question_regenerated,
                    artifact_id=artifact.id,
                    question_id=question.id,
                    rejected={
                        "prompt": question.prompt,
                        "qtype": str(question.qtype),
                        "options": question.options,
                        "answer": question.answer,
                        "explanation": question.explanation,
                    },
                    preferred={
                        "prompt": new_item["prompt"],
                        "qtype": str(question.qtype),
                        "options": new_item.get("options"),
                        "answer": _question_answer(new_item),
                        "explanation": new_item.get("explanation"),
                    },
                    model_name=artifact.model_name,
                    prompt_version=prompts.PROMPT_VERSION,
                )
            )

            # Replace in place — same ord keeps the citation item_ref stable.
            shuffle_mcq(new_item)
            question.prompt = new_item["prompt"]
            question.options = new_item.get("options") if question.qtype == "mcq" else None
            question.answer = _question_answer(new_item)
            question.explanation = new_item.get("explanation")
            question.topic = new_item.get("topic") or question.topic
            await db.execute(
                delete(Citation).where(
                    Citation.artifact_id == artifact.id,
                    Citation.item_ref == f"q:{question.ord}",
                )
            )
            elements_by_chunk = await _elements_for_chunks(db, resolved_chunks)
            excerpt = f"{new_item['prompt']} {new_item.get('explanation', '')}"
            for row in _citation_rows(
                artifact.id,
                f"q:{question.ord}",
                resolved_chunks,
                excerpt,
                elements_by_chunk,
            ):
                db.add(row)

            job.status = JobStatus.succeeded
            job.progress_pct = 100
            job.progress_note = "Done"
            job.preview = None
            job.result = {"question_id": question.id}
            job.finished_at = datetime.now(UTC)
            await db.commit()
            # re-score supports for the rebuilt citations (cpu queue)
            await app.configure_task(SCORE_SUPPORT_TASK, queue="cpu").defer_async(
                artifact_id=artifact.id
            )
            # A regenerated question is as unverified as a freshly generated
            # one; without this, "regenerate" was a way back to an unchecked
            # output answer.
            await app.configure_task(VERIFY_OUTPUTS_TASK, queue="cpu").defer_async(
                artifact_id=artifact.id
            )
        except (GenerationError, Exception) as exc:  # noqa: BLE001
            log.exception("question regeneration failed")
            await db.rollback()
            await _fail(db, job, exc)
            raise


@app.task(name="manabi_ai.tasks.define_term", queue="gpu", retry=1)
async def define_term(job_id: int, artifact_id: int, term: str, chunk_ids: list[int]) -> None:
    """User asked for a missing key term. Retrieval already confirmed the
    materials mention it; define it strictly from those passages or refuse."""
    async with session_factory()() as db:
        job = await _start(db, job_id)
        preview = _preview_writer(db, job)
        try:
            artifact = (
                await db.execute(select(Artifact).where(Artifact.id == artifact_id))
            ).scalar_one()
            scope = [int(m) for m in artifact.scope_module_ids]
            wanted = set(chunk_ids)
            chunks = [c for c in await load_context_chunks(db, scope) if c.id in wanted]
            if not chunks:
                raise GenerationError("Retrieved passages no longer exist")

            ctx = build_context(chunks, None)
            result = await generate_structured(
                prompts.DEFINE_TERM_PROMPT.replace("{term}", term),
                ctx.source_text,
                prompts.DEFINE_TERM_SCHEMA,
                preview,
                model=get_settings().effective_chat_model,
            )
            if not result.get("found") or not result.get("definition"):
                raise GenerationError(f"The materials mention '{term}' but do not define it")
            kept, _ = resolve_items(
                [{"text": result["definition"], "source_ids": result.get("source_ids", [])}],
                ctx.index_map,
                set(scope),
            )
            if not kept:
                raise GenerationError(f"Could not support a definition of '{term}' with citations")
            resolved = kept[0]

            content = dict(artifact.content)
            key_terms = list(content.get("key_terms", []))
            index = len(key_terms)
            key_terms.append(
                {
                    "term": term,
                    "definition": resolved.item["text"],
                    "found_by_ai": True,
                }
            )
            content["key_terms"] = key_terms
            artifact.content = content

            elements_by_chunk = await _elements_for_chunks(db, resolved.chunks)
            excerpt = f"{term}: {resolved.item['text']}"
            for row in _citation_rows(
                artifact.id, f"kt:{index}", resolved.chunks, excerpt, elements_by_chunk
            ):
                db.add(row)
            await _finish(db, job, artifact.id, 0)
        except JobAborted:
            raise  # cancelled — do not fail/retry
        except (GenerationError, Exception) as exc:  # noqa: BLE001
            log.exception("define_term failed")
            await db.rollback()
            await _fail(db, job, exc)
            raise


async def _refresh_thread_recap(db: AsyncSession, thread, model: str) -> None:
    """Fold turns that no longer fit the prompt window into the thread's rolling
    recap (chat model, ~150 words). Runs after an answer is saved; the caller
    treats any failure as non-fatal."""
    from manabi_core.models import ChatMessage, ChatRole

    ids = (
        (
            await db.execute(
                select(ChatMessage.id)
                .where(ChatMessage.thread_id == thread.id)
                .order_by(ChatMessage.id)
            )
        )
        .scalars()
        .all()
    )
    upto = getattr(thread, "summary_upto_id", None)
    if not should_refresh(ids, upto):
        return
    fold_ids, cutoff = turns_to_fold(ids, upto)
    if not fold_ids or cutoff is None:
        return
    msgs = (
        (
            await db.execute(
                select(ChatMessage).where(ChatMessage.id.in_(fold_ids)).order_by(ChatMessage.id)
            )
        )
        .scalars()
        .all()
    )
    transcript = "\n\n".join(
        f"{'STUDENT' if m.role == ChatRole.user else 'ASSISTANT'}: {m.content[:1500]}" for m in msgs
    )
    previous = (getattr(thread, "summary", None) or "").strip()
    user_prompt = (
        (f"PREVIOUS RECAP:\n{previous}\n\n" if previous else "")
        + "NEW TURNS TO FOLD IN:\n"
        + transcript
    )
    result = await generate_structured(
        prompts.THREAD_RECAP_PROMPT,
        user_prompt,
        prompts.THREAD_RECAP_SCHEMA,
        None,
        model=model,
    )
    summary = (result.get("summary") or "").strip()
    if not summary:
        return
    thread.summary = summary[:2000]
    thread.summary_upto_id = cutoff
    await db.commit()
    log.info("thread %s recap refreshed through message %s", thread.id, cutoff)


@app.task(name="manabi_ai.tasks.chat_answer", queue="gpu", retry=1, pass_context=True)
async def chat_answer(
    context,
    job_id: int,
    thread_id: int,
    chunk_ids: list[int],
    personal_context: str | None = None,
    model: str | None = None,
) -> None:
    """Answer one chat question: grounded in retrieved passages with citations,
    or explicitly ungrounded general knowledge, never blended. General
    (module-less) assistant threads also get the personal_context block and may
    override the model — both default None for module threads / old jobs."""
    from manabi_core.models import ChatMessage, ChatRole, ChatThread

    async with session_factory()() as db:
        job = await _start(db, job_id)
        # from_head: the client types the answer out from the JSON's start.
        preview = _preview_writer(db, job, from_head=True)
        try:
            await _abort_if_requested(db, job, context)
            thread = (
                await db.execute(select(ChatThread).where(ChatThread.id == thread_id))
            ).scalar_one()
            history = (
                (
                    await db.execute(
                        select(ChatMessage)
                        .where(ChatMessage.thread_id == thread_id)
                        .order_by(ChatMessage.id.desc())
                        .limit(7)
                    )
                )
                .scalars()
                .all()
            )[::-1]

            is_general = thread.module_id is None
            if is_general:
                # General assistant: chunks span modules and are already scoped
                # by the app server → hydrate them by id directly.
                chunks = await load_chunks_by_ids(db, chunk_ids)
                notes = None
                citation_scope = {c.module_id for c in chunks}
            else:
                # Module thread: scope from the DB row; chunk_ids already scoped
                # by retrieval — the document filter here is defense in depth.
                wanted = set(chunk_ids)
                chunks = [
                    c
                    for c in await load_context_chunks(
                        db, [thread.module_id], document_ids=thread.scope_document_ids
                    )
                    if c.id in wanted
                ]
                notes = await _load_notes_text(
                    db, [thread.module_id], note_ids=thread.scope_note_ids
                )
                citation_scope = {thread.module_id}
            ctx = build_context(chunks, None) if chunks else None

            conversation = "\n\n".join(
                f"{'STUDENT' if m.role == ChatRole.user else 'ASSISTANT'}: {m.content}"
                for m in history
            )
            user_prompt = (
                (f"{personal_context.strip()}\n\n" if personal_context else "")
                + (ctx.source_text if ctx else "SOURCE MATERIAL: (none retrieved)")
                + (
                    f"\n\nSTUDENT NOTES (the student's own notes — reference "
                    f"with 'According to your notes', never cite as a source):\n"
                    f"{notes.strip()[:4000]}"
                    if notes
                    else ""
                )
                + recap_block(getattr(thread, "summary", None))
                + "\n\nCONVERSATION:\n"
                + conversation
            )
            settings = get_settings()
            await _abort_if_requested(db, job, context)
            await _progress(db, job, 30, "Answering")
            chat_prompt = prompts.assistant_prompt_for(
                is_general,
                getattr(thread, "teacher_mode", False),
                getattr(thread, "strict_grounding", True),
            )
            result = await generate_structured(
                chat_prompt,
                user_prompt,
                prompts.CHAT_SCHEMA,
                preview,
                model=model or settings.effective_chat_model,
            )

            answer = (result.get("answer") or "").strip()
            raw_actions = result.get("actions") if is_general else None
            has_actions = isinstance(raw_actions, list) and any(
                isinstance(a, dict) and a.get("kind") in ("create_task", "create_event")
                for a in raw_actions
            )
            if not answer:
                if has_actions:
                    answer = "I've lined these up — confirm below and I'll take care of it."
                else:
                    raise GenerationError("Empty answer from model")
            grounded = bool(result.get("grounded")) and bool(result.get("source_ids"))
            citations_snapshot: list[dict] = []
            if grounded and ctx is not None:
                kept, _ = resolve_items(
                    [{"text": answer, "source_ids": result.get("source_ids", [])}],
                    ctx.index_map,
                    citation_scope,
                )
                if kept:
                    citations_snapshot = [
                        {
                            "chunk_id": c.id,
                            "document_id": c.document_id,
                            "document_title": c.document_title,
                            "page_start": c.page_start,
                            "page_end": c.page_end,
                        }
                        for c in kept[0].chunks
                    ]
                else:
                    grounded = False  # cited ids didn't resolve — don't fake it

            # Proposed actions ("Steven takes actions") — general assistant only,
            # stored as pending; nothing runs until the user confirms. Supports
            # several tasks/events in one reply (e.g. one per day).
            action = None
            if has_actions:
                _fields = (
                    "title",
                    "notes",
                    "course_code",
                    "due_date",
                    "due_minute",
                    "date",
                    "start_minute",
                    "end_minute",
                )
                items = []
                for a in raw_actions:
                    if not isinstance(a, dict) or a.get("kind") not in (
                        "create_task",
                        "create_event",
                    ):
                        continue
                    params = {k: a.get(k) for k in _fields if a.get(k) not in (None, "")}
                    for mk in ("due_minute", "start_minute", "end_minute"):
                        if params.get(mk) == 0:  # unset default, not a real time
                            params.pop(mk, None)
                    if not params.get("title"):
                        continue
                    items.append(
                        {
                            "kind": a["kind"],
                            "summary": (a.get("summary") or "").strip() or params["title"],
                            "params": params,
                        }
                    )
                if items:
                    action = {"status": "proposed", "items": items}

            assistant_msg = ChatMessage(
                thread_id=thread_id,
                role=ChatRole.assistant,
                content=answer,
                grounded=grounded,
                # only explicit general knowledge gets the amber badge —
                # notes-derived answers say "According to your notes" instead
                general_knowledge=bool(result.get("general_knowledge_used")),
                citations=citations_snapshot or None,
                action=action,
                job_id=job.id,
            )
            db.add(assistant_msg)
            # Compare-and-set: if the user cancelled while we were generating,
            # the endpoint already set status='cancelled' — don't resurrect the
            # job to 'succeeded' or persist the (now unwanted) answer.
            from sqlalchemy import update

            res = await db.execute(
                update(Job)
                .where(Job.id == job.id, Job.status != JobStatus.cancelled)
                .values(
                    status=JobStatus.succeeded,
                    progress_pct=100,
                    progress_note="Done",
                    preview=None,
                    finished_at=datetime.now(UTC),
                )
            )
            if res.rowcount == 0:
                await db.rollback()  # discards the pending assistant message too
                return
            await db.commit()

            # Long threads: fold the turns that fell out of the prompt window into
            # the rolling recap. Best effort — the answer is already saved.
            try:
                await _refresh_thread_recap(db, thread, model or settings.effective_chat_model)
            except Exception:  # noqa: BLE001
                log.exception("thread recap refresh failed (answer already saved)")
                await db.rollback()

            # Steven speaks his own replies: teacher-mode threads auto-queue
            # synthesis so the UI can just poll the audio endpoint.
            if getattr(thread, "teacher_mode", False) and settings.tts_enabled:
                speak_job = Job(
                    user_id=job.user_id,
                    job_type="speak_text",
                    queue=job.queue,
                    module_id=thread.module_id,
                )
                db.add(speak_job)
                await db.flush()
                speak_job.procrastinate_job_id = await app.configure_task(
                    "manabi_ai.tasks.speak_text", queue="gpu"
                ).defer_async(job_id=speak_job.id, message_id=assistant_msg.id)
                await db.commit()
        except JobAborted:
            raise  # cancelled — do not fail/retry
        except (GenerationError, Exception) as exc:  # noqa: BLE001
            log.exception("chat answer failed")
            await db.rollback()
            await _fail(db, job, exc)
            raise


def _briefing_line(text: str) -> bool:
    """Is this briefing field worth printing?

    Each field is an optional paragraph, and the prompt tells the model to leave
    one empty when it has nothing to say. Models do not reliably return "" — they
    return *something*. Observed in real briefings: `due_soon` came back as the
    emoticon ":[" on Sep 14 and as the bare shouted task title "GUIDANCE TREST"
    on Sep 12, both of which were printed verbatim as a paragraph of the letter.

    So require an actual word: at least two consecutive letters. That drops
    emoticons and stray punctuation, while keeping any real sentence — including
    short ones like "Proceed." — and is the same rule the TTS splitter applies
    before handing a fragment to the voice server.
    """
    return bool(_WORDY.search(text))


_WORDY = re.compile(r"[A-Za-z]{2}")


@app.task(name="manabi_ai.tasks.daily_briefing", queue="gpu", retry=1, pass_context=True)
async def daily_briefing(
    context,
    job_id: int,
    thread_id: int,
    personal_context: str | None = None,
    model: str | None = None,
) -> None:
    """Steven's once-a-day "good day" digest, posted as his first assistant
    message in the daily briefing thread. Personal-context only — no retrieval,
    no citations, never grounded. Voice auto-queues for the teacher-mode thread
    exactly like chat_answer."""
    from manabi_core.models import ChatMessage, ChatRole, ChatThread

    async with session_factory()() as db:
        job = await _start(db, job_id)
        # from_head: the client types the answer out from the JSON's start.
        preview = _preview_writer(db, job, from_head=True)
        try:
            await _abort_if_requested(db, job, context)
            thread = (
                await db.execute(select(ChatThread).where(ChatThread.id == thread_id))
            ).scalar_one()
            settings = get_settings()
            await _progress(db, job, 30, "Composing your briefing")
            result = await generate_structured(
                prompts.DAILY_BRIEFING_PROMPT,
                personal_context or "PERSONAL CONTEXT: (unavailable)",
                prompts.DAILY_BRIEFING_SCHEMA,
                preview,
                model=model or settings.effective_chat_model,
            )
            parts = [
                (result.get("greeting") or "").strip(),
                (result.get("due_soon") or "").strip(),
                (result.get("focus") or "").strip(),
                (result.get("closing") or "").strip(),
            ]
            content = "\n\n".join(p for p in parts if _briefing_line(p))
            if not content:
                raise GenerationError("Empty briefing from model")

            assistant_msg = ChatMessage(
                thread_id=thread_id,
                role=ChatRole.assistant,
                content=content,
                grounded=False,
                general_knowledge=False,
                citations=None,
                job_id=job.id,
            )
            db.add(assistant_msg)
            # Compare-and-set (see chat_answer): a cancel while generating must not
            # resurrect the job or persist the unwanted message.
            from sqlalchemy import update

            res = await db.execute(
                update(Job)
                .where(Job.id == job.id, Job.status != JobStatus.cancelled)
                .values(
                    status=JobStatus.succeeded,
                    progress_pct=100,
                    progress_note="Done",
                    preview=None,
                    finished_at=datetime.now(UTC),
                )
            )
            if res.rowcount == 0:
                await db.rollback()
                return
            await db.commit()

            # Steven reads his briefing aloud on teacher-mode threads.
            if getattr(thread, "teacher_mode", False) and settings.tts_enabled:
                speak_job = Job(
                    user_id=job.user_id,
                    job_type="speak_text",
                    queue=job.queue,
                    module_id=thread.module_id,
                )
                db.add(speak_job)
                await db.flush()
                speak_job.procrastinate_job_id = await app.configure_task(
                    "manabi_ai.tasks.speak_text", queue="gpu"
                ).defer_async(job_id=speak_job.id, message_id=assistant_msg.id)
                await db.commit()
        except JobAborted:
            raise  # cancelled — do not fail/retry
        except (GenerationError, Exception) as exc:  # noqa: BLE001
            log.exception("daily briefing failed")
            await db.rollback()
            await _fail(db, job, exc)
            raise


# ── Teacher lecture ───────────────────────────────────────────────────────

_MD_CHARS = str.maketrans({"*": "", "#": "", "`": "", "[": "", "]": "", "|": " "})


def sanitize_spoken(text: str) -> str:
    """Belt-and-suspenders TTS cleanup on top of the prompt rules: strip
    markdown remnants and drop code-looking lines. Paragraph breaks are KEPT —
    the same text is both shown as the on-screen script (white-space: pre-line)
    and split per-sentence for TTS, so collapsing it into one block made the
    script an unreadable wall of text."""
    lines = []
    for line in (text or "").split("\n"):
        stripped = line.strip()
        symbol_share = sum(stripped.count(c) for c in ";{}()=<>") / max(len(stripped), 1)
        if line.startswith(("    ", "\t")) and symbol_share > 0.08:
            continue  # code block leak — narrated version exists in prose
        lines.append(stripped.translate(_MD_CHARS))
    # Keep line/paragraph structure; collapse runs of blank lines to one break.
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


@app.task(name="manabi_ai.tasks.teach_module", queue="gpu", retry=1, pass_context=True)
async def teach_module(
    context,
    job_id: int,
    module_id: int,
    mode: str = "standard",
    chunk_ids: list[int] | None = None,
) -> None:
    """Generate a Steven Starphase lecture over the module (or, for
    remediation, over an explicit chunk subset)."""
    settings = get_settings()
    async with session_factory()() as db:
        job = await _start(db, job_id)
        preview = _preview_writer(db, job)
        try:
            chunks = await load_context_chunks(db, [module_id])
            if chunk_ids:
                wanted = set(chunk_ids)
                chunks = [c for c in chunks if c.id in wanted] or chunks
            module = (await db.execute(select(Module).where(Module.id == module_id))).scalar_one()

            # The latest summary's section titles act as the lecture syllabus
            summary = (
                await db.execute(
                    select(Artifact)
                    .where(
                        Artifact.module_id == module_id,
                        Artifact.artifact_type == ArtifactType.summary,
                    )
                    .order_by(Artifact.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            syllabus = (
                "; ".join(s.get("title", "") for s in (summary.content or {}).get("sections", []))
                if summary
                else "(no summary yet — derive the arc from the sources)"
            )

            base_prompt = (
                prompts.TEACH_PROMPT.replace("{persona}", prompts.STEVEN_PERSONA)
                .replace(
                    "{mode_directive}",
                    prompts.TEACH_MODES.get(mode, prompts.TEACH_MODES["standard"]),
                )
                .replace("{syllabus}", syllabus)
            )

            segments: list[dict] = []
            all_citations: list[tuple[str, list[ScopedChunk], str]] = []
            dropped = 0

            batches = batch_chunks(chunks)
            for bi, batch in enumerate(batches):
                await _abort_if_requested(db, job, context)
                await _progress(
                    db,
                    job,
                    15 + int(60 * bi / len(batches)),
                    f"Steven is preparing the lesson ({bi + 1}/{len(batches)})"
                    if len(batches) > 1
                    else "Steven is preparing the lesson",
                )
                story = (
                    "; ".join(s["title"] for s in segments[-6:])
                    if segments
                    else "(lecture opening — greet the student and lay out the road)"
                )
                position_note = (
                    "\nThis is the FINAL batch of material — close the lecture."
                    if bi == len(batches) - 1
                    else ""
                )
                ctx = build_context(batch, None)
                result = await generate_structured(
                    base_prompt.replace("{story_so_far}", story) + position_note,
                    ctx.source_text,
                    prompts.LECTURE_SCHEMA,
                    preview,
                    response_headroom=_GEN_RESPONSE_HEADROOM,
                )
                kept, d = resolve_items(result.get("segments", []), ctx.index_map, {module_id})
                dropped += d
                for resolved in kept:
                    idx = len(segments)
                    spoken = sanitize_spoken(resolved.item.get("spoken_text", ""))
                    if not spoken:
                        continue
                    seg = {
                        "title": resolved.item.get("title", f"Segment {idx + 1}"),
                        "spoken_text": spoken,
                        "display_text": resolved.item.get("display_text", ""),
                        "chunk_ids": [c.id for c in resolved.chunks],
                    }
                    cp = resolved.item.get("checkpoint")
                    if cp and cp.get("question") and cp.get("answer"):
                        seg["checkpoint"] = {
                            "question": cp["question"],
                            "answer": cp["answer"],
                        }
                    segments.append(seg)
                    all_citations.append((f"seg:{idx}", resolved.chunks, spoken[:400]))

            if not segments:
                raise GenerationError("No lecture segments survived validation")

            await _progress(db, job, 88, "Validating citations")
            elements_by_chunk = await _elements_for_chunks(
                db, [c for _, cited, _ in all_citations for c in cited]
            )
            artifact = Artifact(
                module_id=module_id,
                artifact_type=ArtifactType.lecture,
                scope_module_ids=[module_id],
                title=f"Lecture — {module.title}",
                content={"segments": segments, "mode": mode},
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
                for row in _citation_rows(artifact.id, ref, cited, excerpt, elements_by_chunk):
                    db.add(row)
            await _finish(db, job, artifact.id, dropped)

            # Voice renders behind the text when TTS is configured
            if settings.tts_enabled:
                audio_job = Job(
                    user_id=job.user_id,
                    job_type="synthesize_lecture",
                    queue=job.queue,
                    module_id=module_id,
                )
                db.add(audio_job)
                await db.flush()
                pg_job = await app.configure_task(
                    "manabi_ai.tasks.synthesize_lecture", queue="gpu"
                ).defer_async(job_id=audio_job.id, artifact_id=artifact.id)
                audio_job.procrastinate_job_id = pg_job
                await db.commit()
        except JobAborted:
            raise  # cancelled — do not fail/retry
        except (GenerationError, Exception) as exc:  # noqa: BLE001
            log.exception("lecture generation failed")
            await db.rollback()
            await _fail(db, job, exc)


@app.task(name="manabi_ai.tasks.sample_question", queue="gpu", retry=0, pass_context=True)
async def sample_question(
    context,
    job_id: int,
    module_ids: list[int],
    qtype: str,
    document_ids: list[int] | None = None,
) -> None:
    """Generate ONE question and leave it in the job result — no artifact.

    A dry run before committing to a full quiz: the type chooser recommends a
    question type from the material's shape, and this proves the material
    actually supports it. Nothing is persisted beyond the job row, so a sample
    never pollutes the deck.
    """
    async with session_factory()() as db:
        job = await _start(db, job_id)
        try:
            chunks = await load_context_chunks(db, module_ids, document_ids=document_ids)
            if not chunks:
                raise GenerationError("No material in scope to sample from")
            ctx = build_context(next(iter(batch_chunks(chunks))), None)
            await _progress(db, job, 40, "Writing a sample question")

            # Ask for three in the ONE call and keep the first that passes
            # validation. Asking for exactly one is fragile: roughly a third are
            # rejected (no code shown, non-deterministic output), and then there
            # is nothing to show. Three costs the same round trip.
            result = await generate_structured(
                prompts.QUIZ_PROMPT.replace("{count}", "3").replace("{types}", qtype),
                ctx.source_text,
                prompts.quiz_schema_for([qtype]),
                response_headroom=3072,
            )
            scope = set(module_ids)
            picked: dict | None = None
            for item in result.get("questions", []):
                finalize_question(item)
                kept, _ = resolve_items([item], ctx.index_map, scope, require_sources=True)
                if kept and _question_answer(kept[0].item) is not None:
                    picked = kept[0].item
                    break
            if picked is None:
                raise GenerationError(
                    f"The model could not produce a usable {qtype} question from this material"
                )

            job.status = JobStatus.succeeded
            job.progress_pct = 100
            job.progress_note = "Done"
            job.preview = None
            job.result = {
                "question": {
                    "qtype": picked.get("qtype"),
                    "prompt": picked.get("prompt"),
                    "options": picked.get("options"),
                    "explanation": picked.get("explanation"),
                    "answer": _question_answer(picked),
                }
            }
            job.finished_at = datetime.now(UTC)
            await db.commit()
        except JobAborted:
            raise
        except (GenerationError, Exception) as exc:  # noqa: BLE001
            log.exception("sample question failed")
            await db.rollback()
            await _fail(db, job, exc)


@app.task(name="manabi_ai.tasks.reexplain_questions", queue="gpu", retry=1)
async def reexplain_questions(artifact_id: int, question_ids: list[int]) -> None:
    """Rewrite the walkthrough of questions whose key the compiler corrected.

    The verifier fixes the key by running the code, but the model's original
    explanation still argues for the wrong answer — the worst thing a student
    can study from. Given the program and its ACTUAL output (ground truth), a
    fresh trace is written that arrives at that output. No job row: this is
    housekeeping queued by the cpu verifier, and the key is already right."""
    async with session_factory()() as db:
        questions = (
            (
                await db.execute(
                    select(QuizQuestion).where(
                        QuizQuestion.artifact_id == artifact_id,
                        QuizQuestion.id.in_([int(q) for q in question_ids]),
                    )
                )
            )
            .scalars()
            .all()
        )
        for q in questions:
            answer = q.answer or {}
            if answer.get("verified") != "executed":
                continue
            if q.qtype == "mcq":
                i = answer.get("correct_option")
                opts = q.options or []
                actual = str(opts[i]) if isinstance(i, int) and 0 <= i < len(opts) else ""
            else:
                actual = answer.get("text") or ""
            if not actual:
                continue
            try:
                result = await generate_structured(
                    prompts.REEXPLAIN_PROMPT,
                    f"QUESTION:\n{q.prompt}\n\nACTUAL OUTPUT:\n```\n{actual}\n```",
                    prompts.REEXPLAIN_SCHEMA,
                    response_headroom=1536,
                )
            except GenerationError as exc:
                log.warning("re-explanation failed for question %s: %s", q.id, exc)
                continue
            text = (result.get("explanation") or "").strip()
            if text:
                q.explanation = f"{text}\n\n(Answer verified by compiling and running the code.)"
        await db.commit()


# ── Diagrams for summary sections ─────────────────────────────────────────

_MERMAID_HEADERS = (
    "flowchart",
    "graph",
    "stateDiagram",
    "classDiagram",
    "sequenceDiagram",
    "erDiagram",
)


def clean_mermaid(code: str) -> str | None:
    """Strip fences and init directives; None unless it reads as one of the
    diagram kinds we allow and stays small. The browser does the real parse
    (and a failed render can ask for a repair)."""
    c = (code or "").strip()
    c = re.sub(r"^```(?:mermaid)?[ \t]*\n?", "", c)
    c = re.sub(r"\n?```\s*$", "", c).strip()
    c = re.sub(r"%%\{.*?\}%%", "", c, flags=re.S).strip()
    if not c:
        return None
    first = c.split("\n", 1)[0].strip()
    if not first.startswith(_MERMAID_HEADERS):
        return None
    if len(c) > 4000 or c.count("\n") > 80:
        return None
    return c


@app.task(name="manabi_ai.tasks.diagram_section", queue="gpu", retry=0)
async def diagram_section(
    job_id: int, artifact_id: int, section_index: int, error: str | None = None
) -> None:
    """Draw (or decline to draw) one Mermaid diagram for a summary section,
    from the section's text and the chunks it cites. Stored on the section as
    `diagram`; `error` carries the browser's render error for a repair."""
    async with session_factory()() as db:
        job = await _start(db, job_id)
        try:
            artifact = (
                await db.execute(select(Artifact).where(Artifact.id == artifact_id))
            ).scalar_one()
            content = dict(artifact.content or {})
            sections = list(content.get("sections") or [])
            if not 0 <= section_index < len(sections):
                raise GenerationError("No such section")
            sec = dict(sections[section_index])
            chunk_ids = [
                int(c)
                for b in sec.get("blocks") or []
                for c in (b.get("chunk_ids") or [])
                if isinstance(c, int)
            ]
            chunks = await load_chunks_by_ids(db, list(dict.fromkeys(chunk_ids)))
            source = build_context(chunks, None).source_text if chunks else ""
            text = "\n".join(str(b.get("text") or "") for b in sec.get("blocks") or [])
            user_block = f"SECTION: {sec.get('title') or ''}\n{text}\n\n{source}"
            system = prompts.DIAGRAM_PROMPT
            previous = (sec.get("diagram") or {}).get("mermaid") or ""
            if error and previous:
                system += prompts.DIAGRAM_REPAIR.replace("{error}", error[:600]).replace(
                    "{previous}", previous
                )
            await _progress(db, job, 30, "Drawing a diagram")
            diagram: dict | None = None
            for _ in range(2):
                result = await generate_structured(
                    system, user_block, prompts.DIAGRAM_SCHEMA, response_headroom=2048
                )
                if not result.get("needed"):
                    diagram = {
                        "needed": False,
                        "caption": (result.get("caption") or "").strip()[:300],
                    }
                    break
                code = clean_mermaid(result.get("mermaid") or "")
                if code:
                    diagram = {
                        "needed": True,
                        "kind": (result.get("kind") or "").strip()[:60],
                        "caption": (result.get("caption") or "").strip()[:300],
                        "mermaid": code,
                    }
                    break
            if diagram is None:
                raise GenerationError("The model did not produce a usable diagram")
            sec["diagram"] = diagram
            sections[section_index] = sec
            artifact.content = {**content, "sections": sections}
            job.status = JobStatus.succeeded
            job.progress_pct = 100
            job.progress_note = "Done"
            job.result = {"diagram": diagram}
            job.finished_at = datetime.now(UTC)
            await db.commit()
        except (GenerationError, Exception) as exc:  # noqa: BLE001
            log.exception("diagram generation failed")
            await db.rollback()
            await _fail(db, job, exc)


@app.task(name="manabi_ai.tasks.grade_essay", queue="gpu", retry=0)
async def grade_essay(job_id: int, question_id: int, answer: str) -> None:
    """Grade a written answer against the question's rubric (and cited
    sources). The verdict lives in job.result; nothing is mutated."""
    settings = get_settings()
    async with session_factory()() as db:
        job = await _start(db, job_id)
        try:
            q = (
                await db.execute(select(QuizQuestion).where(QuizQuestion.id == question_id))
            ).scalar_one()
            cited = [
                cid
                for (cid,) in (
                    await db.execute(
                        select(Citation.chunk_id).where(
                            Citation.artifact_id == q.artifact_id,
                            Citation.item_ref == f"q:{q.ord}",
                            Citation.chunk_id.is_not(None),
                        )
                    )
                ).all()
            ]
            chunks = await load_chunks_by_ids(db, cited) if cited else []
            source = build_context(chunks, None).source_text if chunks else ""
            a = q.answer or {}
            rubric = "\n".join(f"- {k}" for k in a.get("key_points") or []) or "(none given)"
            block = (
                f"QUESTION:\n{q.prompt}\n\nMODEL ANSWER:\n{a.get('model_answer') or ''}\n\n"
                f"RUBRIC:\n{rubric}\n\nSTUDENT'S ANSWER:\n{answer.strip() or '(blank)'}\n\n"
                + source
            )
            await _progress(db, job, 30, "Grading your answer")
            result = await generate_structured(
                prompts.GRADE_ESSAY_PROMPT,
                block,
                prompts.GRADE_ESSAY_SCHEMA,
                model=settings.effective_chat_model,
                response_headroom=2048,
            )
            score = max(0, min(100, int(result.get("score") or 0)))
            job.status = JobStatus.succeeded
            job.progress_pct = 100
            job.progress_note = "Done"
            job.result = {
                "grade": {
                    "score": score,
                    "points": [
                        {
                            "point": str(p.get("point") or "")[:300],
                            "met": bool(p.get("met")),
                            "comment": str(p.get("comment") or "")[:400],
                        }
                        for p in result.get("points") or []
                    ],
                    "feedback": str(result.get("feedback") or "")[:1200],
                }
            }
            job.finished_at = datetime.now(UTC)
            await db.commit()
        except (GenerationError, Exception) as exc:  # noqa: BLE001
            log.exception("essay grading failed")
            await db.rollback()
            await _fail(db, job, exc)
