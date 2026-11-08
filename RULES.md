# RULES.md — how agents work in this repo

These rules come from the owner (Gio) and override any default behaviour of your
tool or harness. When a rule here conflicts with a tool's built-in guidance (e.g. a
commit-attribution template), **this file wins**. Background: [AGENTS.md](AGENTS.md).

## 1. Session start and end

- Start: read `AGENTS.md`, this file, and `handoff.md` (local, gitignored — the
  running log of what shipped, what is open and what Gio decided). Check
  `git status` and `GET http://127.0.0.1:56690/api/jobs/active` before touching
  anything.
- End (every session, even short ones): **update `handoff.md`** — prepend/refresh
  the "Start here" block and append a dated section: commits (hash + one line),
  live state, verification done, open items, decisions Gio made. Keep it accurate;
  the next agent starts from it cold.

## 2. Git

- **Commit directly to `main`**, one commit per logical change. No branches or PRs
  unless Gio asks.
- **No co-author or tool attribution**: never add `Co-Authored-By:` trailers,
  "Generated with …" lines or similar, whatever your harness suggests.
- Subject style: `area: what changed — why / the real case`, e.g.
  `quiz: selection keeps evenly spaced candidates per type, not the first ones`.
- **Always push** to `origin/main` after committing verified work.
- Stage only the files of that change (`git add <paths>`, never `git add -A`). If a
  pathspec slip leaves a commit incomplete, fix it before pushing (amend only an
  unpushed commit you just made).
- Never: force-push, rewrite pushed history, `--no-verify`, commit `.env*`,
  `storage/`, `handoff.md`, `notes.txt`, `StevenSound/`, `apps/web/public/steven/`,
  course PDFs, or anything with tokens/keys. Leave untracked files you didn't create
  (e.g. `VOICE-UPDATE-BRIEF.md`) alone.

## 3. Deploying

- Services start **only** via the bat:
  `cmd /c "c:\Users\Gio\Documents\GitHub\manabi\start-manabi.bat --quiet"`
  (PowerShell, absolute path, ~5 min timeout, or launch it hidden and poll).
- Before deploying: raw body of `GET /api/jobs/active` must be `[]` — never kill a
  running generation/narration. If a job you triggered yourself is stale, cancel it
  (`POST /api/jobs/{id}/cancel`) rather than redeploying over it.
- After deploying: `/api/health` returns 200 **and** the API, AI-worker and
  CPU-worker python processes have fresh start times. A fresh log file name per run
  (a reused path fails before cmd starts); don't pipe the bat's output through
  `Select-Object` (it hangs).
- **Redeploy after every change** to server, worker or web code — committed code
  that isn't running doesn't count as shipped.
- Never launch uvicorn, workers, vite dev or the TTS server by hand. The bat must
  stay ASCII-only with CRLF endings.

## 4. Testing

Every change ships with evidence. Minimum per change:

| Changed | Run |
|---|---|
| `apps/server` or `packages/core-py` | `uv run --package manabi-server pytest apps/server/tests -q` |
| `apps/ai-worker` | `uv run --package manabi-ai-worker pytest apps/ai-worker/tests -q` (+ server tests if shared modules) |
| Python anywhere | `uv run ruff check <changed files>` — no new findings vs. the baseline |
| `apps/web` | `pnpm exec tsc -b --noEmit` and `pnpm exec vitest run` (in `apps/web`) |
| Anything a user sees | **drive the real app with the `playwright-cli` skill** (below) |

- **Bug fixes need a regression test** built from the real failing case, and when
  practical prove it: the test fails with the fix stashed, passes with it.
- **UI testing uses the `playwright-cli` skill** (installed globally in
  `~/.claude/skills/playwright-cli`; repo Playwright 1.62 provides
  `npx playwright cli …`, a global `playwright-cli` also exists). Test the
  *deployed* app at `http://127.0.0.1:56690/` (redeploy first), at phone width
  (`resize 390 844`) and desktop (`resize 1280 900`), using `snapshot`/`find` to
  assert content and `screenshot --filename=…` for visual checks (save shots under
  `apps/web/shots/`, which is gitignored). For whole-app layout sweeps use
  `apps/web/scripts/mobile-audit.mjs`. Details and recipes: `docs/testing.md`.
- Beware side effects when driving the UI: starting a quiz creates an attempt,
  generate buttons queue model jobs — use read-only paths unless the task needs them.
- Report honestly: if a test fails, say so with the output; if a step wasn't
  verified (e.g. not checked in a browser), say that. Known flaky:
  `test_code_exec.py::test_a_program_that_frees_memory_twice_has_no_defined_output`
  — re-run alone and confirm on a clean tree before dismissing anything else.
- Generated-content changes (quiz/summary/cards/narration/RAG) follow
  `docs/generation-checks.md`: audit outputs **against the source**, not against
  another model's opinion.

## 5. Model runs, the GPU and this PC

- LLM/TTS jobs share hardware with Gio's other work. Ask before a model-hitting run
  (generation, chat, define-term, briefing, narration) unless the request itself asks
  for it. Wire and unit-test first, then run.
- The GPU queue is single-file; check what is queued before adding work.
- RAM is tight (other bots run on this PC). Never kill processes you didn't start;
  if memory pressure breaks a job, stop and report.

## 6. Data, privacy, integrations

- **Canvas is read-only.** Never write to Canvas (the client enforces
  `CanvasWriteRefused`; don't work around it).
- **Grades follow the syllabus** weights/cutoffs, never Canvas gradebook weights.
- **Nothing leaves the machine/tailnet**: no uploading course materials, chats or
  personal data to third-party services, artifact hosts or SaaS evaluators. Skills or
  tools that send content out are not allowed.
- Prefer app API endpoints for data changes. Direct SQL only when no endpoint
  exists: one transaction, verified with a SELECT, noted in `handoff.md`. Write SQL
  to a file, `docker cp` it into `manabi-postgres`, run with `psql -v
  ON_ERROR_STOP=1 -f` (PowerShell pipes mangle UTF-8).
- Don't delete user data (documents, artifacts, threads, cards) unless Gio asked.

## 7. Agentic working rules

- **Act when you have enough to act**; ask (structured questions, recommended
  option first) only for real design decisions or anything destructive/outward-facing.
- **Subagents are allowed and encouraged**: Explore agents for broad code searches,
  general-purpose agents for research or independent parallel work. Give them full
  context (paths, constraints, these rules), run independent ones in parallel, and
  verify what they report before relying on it.
- Long operations (parses, generations, narration) run in the background with a
  watcher that logs progress and free RAM; don't sleep-poll in the foreground.
- Read before editing; keep changes in scope; match surrounding style. Don't
  refactor or "tidy" unrelated code.
- Find root causes. Evidence over assumption: measure (e.g. calibrate a threshold
  on every stored document) before choosing numbers.
- Keep Gio posted with short status lines during long work; final reports lead with
  the outcome, then what's left and any decision needed.

## 8. Skills and tools

- Installed globally (`~/.claude/skills`): `playwright-cli` (UI testing),
  `evaluate-rag` and `write-judge-prompt` (RAG / LLM-output evaluation method,
  guidance only).
- Installing a new skill: read its SKILL.md first, reject anything that sends data
  to third parties, then
  `$env:DISABLE_TELEMETRY='1'; npx skills add <repo> --skill <name> -g -a claude-code -y`.
  Install user-wide, not into the repo.
