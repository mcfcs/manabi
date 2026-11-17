---
name: manabi-generation-check
description: Audit Manabi's generated content end to end against the source reading — extraction/OCR, summary, quiz keys, flashcards, lecture, narration, RAG retrieval. Use when Gio asks for "generation checks" on a reading, when a generated quiz/summary/deck/lecture/narration is reported wrong, or after changing prompts.py, validators.py, quizplan.py, tasks_gen.py or the extraction pipeline.
---

# Manabi generation check

The procedure lives in `docs/generation-checks.md` — read it first; it is the
authority and this skill only adds the order of work and which skill to load at
each step. The rule behind it: outputs must be right **against the source**, and
the pipeline changes only where evidence shows a systematic cause. Model-vs-model
checking is not enough (the blind audit agreed with real misreadings of Sen).

## Order

1. **Ground truth.** Read the source yourself (Read tool, `pages`, ≤ 20 per call).
2. **Extraction before generation.** Chunks, OCR health, page text. Re-extracting
   after generation orphans citations, so fix extraction first.
3. **Generate** with the course's settings — **ask Gio before any model run**
   unless the request includes it (RULES.md §5); check `/api/jobs/active` first and
   watch jobs in the background.
4. **Audit every output by hand** (doc §3).
   - Many outputs to review (a whole deck, several quizzes, an export): load
     **`error-discovery`** to build the review app — bind it to `127.0.0.1`, no CDN
     scripts (inline or plain text), keep its files in the scratchpad, never commit
     it. Course content must not leave this machine.
5. **Retrieval:** load **`evaluate-rag`** (doc §4: ~20 student questions, MRR and
   Recall@k in module and course scope via `manabi_core.retrieval.retrieve()`).
6. **Fix** (doc §5):
   - A defect that repeats → load **`systematic-debugging`** to find the cause,
     then **`write-code-eval`** to turn it into a deterministic guard in
     `validators.py` / `quizplan.py` with a regression test from the real case
     (one commit each), redeploy (**`manabi-deploy`**), regenerate, re-audit.
   - Only when the rule needs interpretation (no code can check it) →
     **`write-judge-prompt`**.
   - A one-off misreading → fix the artifact in place; don't re-extract.
   - A prompt change needs evidence first, and bumps `prompts.PROMPT_VERSION`
     and its test.
7. **Record** defects, commits, artifact ids and residuals in `handoff.md`.
   Before claiming the check is done, load **`verification-before-completion`**.
