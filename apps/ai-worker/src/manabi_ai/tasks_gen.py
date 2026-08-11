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
    DocElement,
    Flashcard,
    Job,
    JobStatus,
    Module,
    Note,
    QuizQuestion,
)
from manabi_core.retrieval import ScopedChunk, load_context_chunks, source_fingerprint
from procrastinate.exceptions import JobAborted
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_ai import prompts
from manabi_ai.app import app
from manabi_ai.config import get_settings
from manabi_ai.context import batch_chunks, build_context, scan_acronym_candidates
from manabi_ai.db import session_factory
from manabi_ai.ollama_client import GenerationError, generate_structured
from manabi_ai.validators import (
    ResolvedItem,
    dedup_cards,
    dedup_questions,
    match_element_ids,
    resolve_items,
)

log = logging.getLogger("manabi_ai")

SCORE_SUPPORT_TASK = "manabi_server.tasks.score_support"  # cpu queue contract


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
    return {
        c.id: [(eid, text_by_id.get(eid, "")) for eid in c.element_ids] for c in chunks
    }


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


def _preview_writer(db: AsyncSession, job: Job):
    async def write(text: str) -> None:
        job.preview = text[-6000:]
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
    await app.configure_task(SCORE_SUPPORT_TASK, queue="cpu").defer_async(
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
            module = (
                await db.execute(select(Module).where(Module.id == module_id))
            ).scalar_one()

            candidates = scan_acronym_candidates(chunks)
            candidate_note = (
                "\nAcronym candidates found in the sources — define each one "
                f"the sources explain: {', '.join(candidates)}\n"
                if candidates
                else ""
            )
            base_prompt = prompts.SUMMARY_PROMPT.replace(
                "{acronym_candidates}", candidate_note
            )

            sections: list[dict] = []
            key_terms: list[dict] = []
            acronyms: list[dict] = []
            all_citations: list[tuple[str, list[ScopedChunk], str]] = []
            dropped = 0

            def absorb(result: dict, ctx) -> None:
                nonlocal dropped
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
                    if any(
                        t["term"].lower() == resolved.item["term"].lower()
                        for t in key_terms
                    ):
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

            batches = batch_chunks(chunks)
            for bi, batch in enumerate(batches):
                await _abort_if_requested(db, job, context)
                await _progress(
                    db, job, 15 + int(50 * bi / len(batches)),
                    f"Generating with {settings.generation_model}"
                    + (f" ({bi + 1}/{len(batches)})" if len(batches) > 1 else ""),
                )
                ctx = build_context(batch, notes if bi == 0 else None)
                result = await generate_structured(
                    base_prompt, ctx.source_text, prompts.SUMMARY_SCHEMA, preview
                )
                absorb(result, ctx)

            # Gap pass: one extra call over passages the first pass skipped
            cited_ids = {c.id for _, cited, _ in all_citations for c in cited}
            uncited = [c for c in chunks if c.id not in cited_ids]
            if chunks and len(cited_ids) / len(chunks) < COVERAGE_TARGET and uncited:
                await _progress(
                    db, job, 72, f"Covering {len(uncited)} missed passages"
                )
                ctx = build_context(uncited, None)
                result = await generate_structured(
                    base_prompt + prompts.GAP_PROMPT_SUFFIX,
                    ctx.source_text,
                    prompts.SUMMARY_SCHEMA,
                    preview,
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
                    "sections": sections,
                    "key_terms": key_terms,
                    "acronyms": acronyms,
                    "coverage": {"cited": len(cited_ids), "total": len(chunks)},
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
                for row in _citation_rows(
                    artifact.id, ref, cited, excerpt, elements_by_chunk
                ):
                    db.add(row)
            await _finish(db, job, artifact.id, dropped)
        except JobAborted:
            raise  # cancelled — do not fail/retry
        except (GenerationError, Exception) as exc:  # noqa: BLE001
            log.exception("summary generation failed")
            await db.rollback()
            await _fail(db, job, exc)
            raise


@app.task(name="manabi_ai.tasks.generate_flashcards", queue="gpu", retry=1, pass_context=True)
async def generate_flashcards(
    context, job_id: int, module_id: int, count: int = 12
) -> None:
    settings = get_settings()
    async with session_factory()() as db:
        job = await _start(db, job_id)
        preview = _preview_writer(db, job)
        try:
            chunks = await load_context_chunks(db, [module_id])
            notes = await _load_notes_text(db, [module_id])
            module = (
                await db.execute(select(Module).where(Module.id == module_id))
            ).scalar_one()

            # ── Derived cards: exact term/acronym cards from the summary ──
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
                    (
                        await db.execute(
                            select(Citation).where(Citation.artifact_id == summary.id)
                        )
                    )
                    .scalars()
                    .all()
                ):
                    summary_citations.setdefault(row.item_ref, []).append(row)
                for i, t in enumerate(summary.content.get("key_terms", [])):
                    if t.get("term") and t.get("definition"):
                        derived.append(
                            (f"Define: {t['term']}", t["definition"], f"kt:{i}")
                        )
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
            rounds = 0
            max_rounds = 8 if exhaustive else 3
            while remaining > len(resolved_cards) and rounds < max_rounds:
                await _abort_if_requested(db, job, context)
                rounds += 1
                added_this_round = 0
                for batch in batches:
                    need = remaining - len(resolved_cards)
                    if need <= 0:
                        break
                    await _progress(
                        db, job, 15 + min(60, 60 * rounds // max_rounds),
                        f"Creating cards with {settings.generation_model}"
                        f" ({len(derived) + len(resolved_cards)}"
                        f"/{'∞' if exhaustive else count})",
                    )
                    ctx = build_context(batch, notes)
                    fronts_note = "\n".join(f"- {f}" for f in existing_fronts[-60:]) or "(none)"
                    result = await generate_structured(
                        prompts.FLASHCARDS_PROMPT.replace(
                            "{count}", str(min(need, 20))
                        ).replace("{existing_fronts}", fronts_note),
                        ctx.source_text,
                        prompts.FLASHCARDS_SCHEMA,
                        preview,
                    )
                    kept, d = resolve_items(
                        result.get("cards", []), ctx.index_map, {module_id}
                    )
                    dropped += d
                    fresh = dedup_cards(kept, existing_fronts)
                    if not fresh:
                        continue
                    added_this_round += len(fresh)
                    resolved_cards.extend(fresh)
                    existing_fronts.extend(
                        (f.item.get("front") or "") for f in fresh
                    )
                if exhaustive and added_this_round < 3:
                    log.info("exhaustive card generation ran dry after %d rounds", rounds)
                    break

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
            elements_by_chunk = await _elements_for_chunks(
                db, [c for r in resolved_cards for c in r.chunks]
            )
            ord_ = 0
            # Derived term/acronym cards: exact content, summary's citations cloned
            for front, back, ref in derived:
                db.add(
                    Flashcard(artifact_id=artifact.id, ord=ord_, front=front, back=back)
                )
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


@app.task(name="manabi_ai.tasks.generate_quiz", queue="gpu", retry=1, pass_context=True)
async def generate_quiz(
    context, job_id: int, module_ids: list[int], types: list[str], count: int = 10
) -> None:
    settings = get_settings()
    async with session_factory()() as db:
        job = await _start(db, job_id)
        preview = _preview_writer(db, job)
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
                await _abort_if_requested(db, job, context)
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
                        preview,
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
            elements_by_chunk = await _elements_for_chunks(
                db, [c for r in final for c in r.chunks]
            )
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


@app.task(name="manabi_ai.tasks.define_term", queue="gpu", retry=1)
async def define_term(
    job_id: int, artifact_id: int, term: str, chunk_ids: list[int]
) -> None:
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
            chunks = [
                c for c in await load_context_chunks(db, scope) if c.id in wanted
            ]
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
                raise GenerationError(
                    f"The materials mention '{term}' but do not define it"
                )
            kept, _ = resolve_items(
                [{"text": result["definition"], "source_ids": result.get("source_ids", [])}],
                ctx.index_map,
                set(scope),
            )
            if not kept:
                raise GenerationError(
                    f"Could not support a definition of '{term}' with citations"
                )
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


@app.task(name="manabi_ai.tasks.chat_answer", queue="gpu", retry=1, pass_context=True)
async def chat_answer(context, job_id: int, thread_id: int, chunk_ids: list[int]) -> None:
    """Answer one chat question: grounded in retrieved module passages with
    citations, or explicitly ungrounded general knowledge, never blended."""
    from manabi_core.models import ChatMessage, ChatRole, ChatThread

    async with session_factory()() as db:
        job = await _start(db, job_id)
        preview = _preview_writer(db, job)
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

            # Thread material scope is read from the DB row (not the payload)
            # so the defer contract stays frozen; chunk_ids are already scoped
            # by retrieval — the document filter here is defense in depth.
            wanted = set(chunk_ids)
            chunks = [
                c
                for c in await load_context_chunks(
                    db, [thread.module_id], document_ids=thread.scope_document_ids
                )
                if c.id in wanted
            ]
            ctx = build_context(chunks, None) if chunks else None
            notes = await _load_notes_text(
                db, [thread.module_id], note_ids=thread.scope_note_ids
            )

            conversation = "\n\n".join(
                f"{'STUDENT' if m.role == ChatRole.user else 'ASSISTANT'}: {m.content}"
                for m in history
            )
            user_prompt = (
                (ctx.source_text if ctx else "SOURCE MATERIAL: (none retrieved)")
                + (
                    f"\n\nSTUDENT NOTES (the student's own notes — reference "
                    f"with 'According to your notes', never cite as a source):\n"
                    f"{notes.strip()[:4000]}"
                    if notes
                    else ""
                )
                + "\n\nCONVERSATION:\n"
                + conversation
            )
            settings = get_settings()
            await _abort_if_requested(db, job, context)
            await _progress(db, job, 30, "Answering")
            chat_prompt = prompts.chat_prompt_for(
                getattr(thread, "teacher_mode", False),
                getattr(thread, "strict_grounding", True),
            )
            result = await generate_structured(
                chat_prompt,
                user_prompt,
                prompts.CHAT_SCHEMA,
                preview,
                model=settings.effective_chat_model,
            )

            answer = (result.get("answer") or "").strip()
            if not answer:
                raise GenerationError("Empty answer from model")
            grounded = bool(result.get("grounded")) and bool(result.get("source_ids"))
            citations_snapshot: list[dict] = []
            if grounded and ctx is not None:
                kept, _ = resolve_items(
                    [{"text": answer, "source_ids": result.get("source_ids", [])}],
                    ctx.index_map,
                    {thread.module_id},
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

            assistant_msg = ChatMessage(
                thread_id=thread_id,
                role=ChatRole.assistant,
                content=answer,
                grounded=grounded,
                # only explicit general knowledge gets the amber badge —
                # notes-derived answers say "According to your notes" instead
                general_knowledge=bool(result.get("general_knowledge_used")),
                citations=citations_snapshot or None,
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


# ── Teacher lecture ───────────────────────────────────────────────────────

_MD_CHARS = str.maketrans({"*": "", "#": "", "`": "", "[": "", "]": "", "|": " "})


def sanitize_spoken(text: str) -> str:
    """Belt-and-suspenders TTS cleanup on top of the prompt rules: strip
    markdown remnants and drop code-looking lines."""
    lines = []
    for line in (text or "").split("\n"):
        stripped = line.strip()
        symbol_share = (
            sum(stripped.count(c) for c in ";{}()=<>") / max(len(stripped), 1)
        )
        if line.startswith(("    ", "\t")) and symbol_share > 0.08:
            continue  # code block leak — narrated version exists in prose
        lines.append(stripped.translate(_MD_CHARS))
    return " ".join(x for x in lines if x).strip()


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
            module = (
                await db.execute(select(Module).where(Module.id == module_id))
            ).scalar_one()

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
                "; ".join(
                    s.get("title", "")
                    for s in (summary.content or {}).get("sections", [])
                )
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
                    db, job, 15 + int(60 * bi / len(batches)),
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
                )
                kept, d = resolve_items(
                    result.get("segments", []), ctx.index_map, {module_id}
                )
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
                    all_citations.append(
                        (f"seg:{idx}", resolved.chunks, spoken[:400])
                    )

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
                for row in _citation_rows(
                    artifact.id, ref, cited, excerpt, elements_by_chunk
                ):
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
