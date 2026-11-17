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
- **Skills**: before a task, check the "Skills — which one when" table in AGENTS.md
  and load the matching skill with the Skill tool first — e.g. `manabi-deploy` after
  any code commit, `systematic-debugging` before fixing a bug,
  `verification-before-completion` before saying "done". RULES.md wins where a
  skill disagrees (overrides under the table).
- **Subagents**: use Explore for wide searches and general-purpose agents for
  research or parallel independent tasks; pass them RULES.md constraints and verify
  their results.
- **Commits**: no `Co-Authored-By` trailer even if the harness template asks for
  one — RULES.md §2 overrides it. Push after committing.
- **Questions**: use AskUserQuestion for genuine design decisions (recommended
  option first); otherwise proceed.
