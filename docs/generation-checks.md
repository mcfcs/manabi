# Generation checks — auditing a new reading end to end

When Gio asks for "the proper generation checks" on a reading (done for Quimpo,
Oct 2026, and Sen ch. 6, Oct 25 2026), this is the procedure. The goal: outputs are
right **against the source**, and the pipeline is only changed where evidence shows a
systematic cause.

Lesson that shapes the order: most real defects were upstream (extraction) or
deterministic (selection, dedup, validation); the model's own blind audit agreed
with interpretive errors (Botswana "counter-example", quinine analogy inverted) —
model-vs-model checking is not enough.

## 0. Ground truth

Read the source yourself (Read tool with `pages`, ≤ 20 per call). Note the facts a
quiz could hinge on: definitions, numbered lists, names, dates, figures, the
author's key distinctions and anything easy to misread (contrasts, "any more than…").

## 1. Extraction — before generating anything

Generation cites chunk ids; re-extracting later orphans those citations. So:

- Chunks: `SELECT id, page_start, page_end, heading_path, left(text, 120) FROM chunks
  WHERE document_id = …`. Glyph soup (`=@!"@,<)Q`) means an unreadable text layer —
  `layout.text_layer_readable` should now route it to OCR.
- OCR health: runs of 1–2-letter tokens (junk lines), numbers and years
  (old-style figures read as `r.7`, `x970s`), lists present (element type `list`),
  every distinctive name/phrase from step 0 findable.
- Page text (`document_pages.text_html`) for the viewer; known residuals: swapped
  OCR lines inside a paragraph, glued footnote markers, lost "fi" ligatures.
- To re-extract: `POST /api/documents/{id}/retry`. Docling output is cached by
  content hash in `storage/parse-cache/` — delete that file if the fix changes the
  parse itself (e.g. OCR on/off).

## 2. Generate with the course's settings

Ask first unless the request includes the runs. SocSc 14 defaults: quiz 12 =
identification 4 / tf 3 / essay 2 / short 1, document-scoped, `audit: true`; deck 24,
styles term + definition; module summary; optional lecture (standard mode).
Endpoints: `POST /api/modules/{id}/summary/generate`, `POST /api/quizzes`,
`POST /api/modules/{id}/flashcards/generate`, `POST /api/modules/{id}/lecture/generate`
(all need header `X-Requested-With: fetch`). Watch jobs in the background (status,
progress note, free RAM).

## 3. Audit every output by hand

- **Summary**: each block's claims vs. its cited pages; key terms (term ↔ definition
  actually match); coverage chip (cited / total chunks).
- **Quiz**: every key correct against the text; the question stands alone (no "the
  sample dataset", "the slides"); coverage across the whole reading (cite pages);
  item-writing flaws (answer in stem, essay that only asks for a list, two questions
  testing one fact, vague identification answers); type mix vs. requested.
- **Deck**: concept duplicates asked both ways; invented labels that aren't the
  author's terms; requested count reached.
- **Lecture**: display and spoken text both faithful (they can differ).
- **Narration**: script order, lists and headings present (short headings are
  deliberately folded into the next paragraph); pronunciation list (it also exposes
  OCR damage); speaking rate per paragraph (~140–210 wpm normal); `word_times` off
  the recogniser's 20 ms grid ≈ words not heard as written (< 1% is healthy).

## 4. RAG check (`evaluate-rag` skill)

Write ~20 realistic student questions; ground truth = the chunk containing a
distinctive answer phrase. Run the real `manabi_core.retrieval.retrieve()` in module
scope and course scope; report MRR and Recall@1/3/5 and list misses. Sen ch. 6:
MRR 0.90 / 0.92 — no change needed.

## 5. Fix, record, report

- Systematic defect → deterministic guard + regression test (one commit each), redeploy,
  regenerate the affected artifact, re-audit.
- One-off misreading → fix the artifact in place (API endpoints for summary terms /
  sections and cards; direct SQL for quiz keys — no question-edit API yet), or
  Regenerate; don't re-extract.
- Delete superseded artifacts only when Gio agrees.
- Log everything in `handoff.md`: defects found, commits, artifact ids, residuals.
