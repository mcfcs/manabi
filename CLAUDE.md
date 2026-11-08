# CLAUDE.md

Claude Code loads this file. The real instructions are shared with every other agent:

@AGENTS.md
@RULES.md

## Claude Code specifics

- **Local state**: `handoff.md` (repo root, gitignored) is the session log — read it
  at start, update it at the end (RULES.md §1). Durable preferences also live in
  Claude's project memory for this repo.
- **Shells**: the PowerShell tool reaches the tailnet and Docker; the Bash tool is
  network-sandboxed. Use the Write/Edit tools for any file with backslashes,
  quotes or non-ASCII (see AGENTS.md gotchas).
- **Skills**: `playwright-cli` for UI testing (docs/testing.md), `evaluate-rag` and
  `write-judge-prompt` for RAG / LLM-output evaluation (docs/generation-checks.md).
- **Subagents**: use Explore for wide searches and general-purpose agents for
  research or parallel independent tasks; pass them RULES.md constraints and verify
  their results.
- **Commits**: no `Co-Authored-By` trailer even if the harness template asks for
  one — RULES.md §2 overrides it. Push after committing.
- **Questions**: use AskUserQuestion for genuine design decisions (recommended
  option first); otherwise proceed.
