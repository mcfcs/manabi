# Testing Manabi

Rules for *when* to test live in [RULES.md §4](../RULES.md#4-testing). This page is the
*how*. Every command below was run on this machine.

## 1. Unit tests

From the repo root (PowerShell):

```powershell
uv run --package manabi-server pytest apps/server/tests -q        # ~450 tests, ~1 min
uv run --package manabi-ai-worker pytest apps/ai-worker/tests -q  # ~160 tests, ~2 s
uv run ruff check <changed files>
```

From `apps/web`:

```powershell
pnpm exec tsc -b --noEmit
pnpm exec vitest run
```

Notes:

- `apps/server/tests` also imports ai-worker modules (`sys.path` insert), so a
  validator or prompt change is usually tested from both suites.
- Async code is tested with stubbed sessions (`_ScriptedDB` in `test_assistant.py`)
  or by monkeypatching the model call (`generate_structured`) — see
  `test_quizplan.py::test_a_correction_that_breaks_the_key_rules_drops_the_question`.
  No test talks to Ollama, the TTS server or Canvas.
- Prove a regression test: `git stash push <src file>`, run the test (must fail),
  `git stash pop`, run again (must pass).
- Flaky by design: `test_code_exec.py::test_a_program_that_frees_memory_twice_has_no_defined_output`.

## 2. Driving the real app — `playwright-cli` skill

The `playwright-cli` agent skill (`~/.claude/skills/playwright-cli/SKILL.md`, from
`microsoft/playwright-cli`) is the standard way to check anything a user sees. It
drives a real browser through short commands and returns accessibility snapshots
with element refs (`e15`) you can click.

Which binary: the repo's Playwright (1.62) bundles it — run from `apps/web`:

```powershell
cd apps/web
npx --no-install playwright cli open http://127.0.0.1:56690/
```

(a global `playwright-cli` is also installed; either works). Always test the
**deployed** app on port 56690 — redeploy with the bat first; never start a dev
server.

### Recipe: check a page at phone and desktop width

```powershell
npx --no-install playwright cli open http://127.0.0.1:56690/schedule
npx --no-install playwright cli resize 390 844
npx --no-install playwright cli find "SocSc"                  # assert content is there
npx --no-install playwright cli screenshot --filename=shots/schedule-390.png
npx --no-install playwright cli console                       # must report 0 errors
npx --no-install playwright cli resize 1280 900
npx --no-install playwright cli screenshot --filename=shots/schedule-1280.png
npx --no-install playwright cli close
```

Look at the screenshots (the Read tool shows images) — "it rendered" is not the
same as "it looks right". `shots/` and `.playwright-cli/` are gitignored.

### Recipe: interact

```powershell
npx --no-install playwright cli snapshot          # lists refs, e.g. button "Skip" [ref=e42]
npx --no-install playwright cli click e42
npx --no-install playwright cli fill e17 "Lee thesis" --submit
npx --no-install playwright cli eval "document.querySelectorAll('.quiz-question table').length"
```

PowerShell: quote URLs containing `&`, or use `--%` (see the skill's notes).

### Side effects to avoid

The app is Gio's real data. Opening pages is safe. These are not:

- **starting a quiz** creates a quiz attempt; **Generate / Regenerate / Re-record /
  Listen** queue model or TTS jobs on the shared GPU;
- deleting/editing cards, notes, tasks, marks changes real records.

Prefer read-only checks; when an interaction is the point of the test, say so to Gio
first, and clean up what you created.

### Whole-app layout sweep

`node apps/web/scripts/mobile-audit.mjs [outdir]` screenshots every main route at
the phone/tablet/desktop tiers against the running server and prints rail width,
horizontal overflow and column widths (`SIZES=390,1024`, `ONLY=module-,viewer`,
`MANABI_COURSE/MODULE/DOC` env vars).

## 3. Rendering a component in isolation

When the data you need isn't on any page (e.g. a markdown table inside a quiz
question), render the built CSS + the same `marked` options into a temporary HTML
file and screenshot it with Playwright — then delete the scratch script. This is how
the quiz-table styling was checked (Oct 2026).

## 4. Generated content and RAG

Not unit-testable by assertion alone — follow [generation-checks.md](generation-checks.md).
