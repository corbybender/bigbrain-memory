# BigBrain

Deterministic, filesystem-first memory and context-management engine for LLM
coding agents.

## TL;DR

- **What it is:** persistent project memory as plain Markdown files under
  `.bigbrain/` — no vector DB, no embeddings, human-readable, git-friendly.
- **Why:** so an AI coding agent can carry decisions, architecture notes, and
  task state across sessions instead of re-deriving them (or forgetting them)
  every time.
- **Works with:** any AI coding tool — Claude Code, Cursor, Windsurf, Gemini
  CLI, Copilot, Aider, whatever — via plain shell commands, with a bonus MCP
  server for hosts that support native tool-calling.

### Setup

```bash
pip install git+https://github.com/CGB2_Valmont/bigbrain.git
cd /path/to/your/project
bigbrain install
```

That's it. `bigbrain install` scaffolds `.bigbrain/`, wires instructions into
whatever AI-instructions files your tools use (`AGENTS.md`, `CLAUDE.md`,
`.cursor/rules/`, etc.), registers an MCP server for hosts that support it,
and sets up auto-compile hooks (git pre-commit + Claude Code session hooks)
so nobody has to remember to run anything. Re-running it later is safe —
it's idempotent.

Verify it worked:

```bash
bigbrain status   # should report initialized: true
bigbrain index    # should print a Markdown table of memory files
```

---

## Detailed guide

See [`plan.md`](plan.md) for the original design spec this implements.

### Core idea

Information lives in standard Markdown files with YAML frontmatter. An agent
reads a lightweight `INDEX.md` catalog at session start instead of ingesting
the whole memory directory, and pulls specific files on demand. New facts get
appended to an append-only transaction log (`log.md`) during a session, then
reconciled into the real memory files by a compile step — either a free
deterministic merge, or an optional LLM-assisted pass that actually dedupes
and resolves contradictions.

### Install into a repo

```bash
pip install git+https://github.com/CGB2_Valmont/bigbrain.git
cd /path/to/your/project
bigbrain install
```

`bigbrain install`:

1. Scaffolds `.bigbrain/` (index, log, default memory files) at the repo root.
2. Writes `.bigbrain/tools.json` — the raw tool schema, for hosts that do
   custom function-calling.
3. Appends a marked BigBrain instructions block to every well-known
   agent-instructions file it finds or creates: `AGENTS.md`, `CLAUDE.md`,
   `GEMINI.md`, `.windsurfrules`, `.github/copilot-instructions.md`, and a
   Cursor rule at `.cursor/rules/bigbrain.mdc`. That block tells the agent
   how to drive BigBrain through the `bigbrain` shell command — which needs
   no protocol support at all, so it works with literally any agent that can
   run a shell command.
4. Registers a BigBrain MCP server in `.mcp.json` and `.cursor/mcp.json` for
   hosts with native MCP tool-calling (Claude Code, Cursor, ...), so those
   hosts get real tool calls instead of shelling out.
5. Wires **auto-compile**, so nobody has to remember to run it:
   - a `.git/hooks/pre-commit` hook that compiles before every commit (any
     host, no-op in ~10ms if there's nothing pending), and
   - for Claude Code specifically, `SessionStart` / `SessionEnd` /
     `PreCompact` hooks in `.claude/settings.json` — `SessionStart` also
     auto-injects `INDEX.md` into context, so the agent never has to
     remember to read it either.
6. Drops `.bigbrain/config.yml` with commented defaults for the LLM CLI
   override and archive rotation size (below).

Re-running `bigbrain install` is idempotent (existing hooks/files aren't
duplicated). Pass `--force` to refresh the wiring blocks after upgrading
BigBrain. If a target file already has other content (an existing pre-commit
hook, an existing `AGENTS.md`), BigBrain appends a marked block rather than
overwriting it.

### Directory layout

```text
.bigbrain/
├── INDEX.md              # compiled catalog, ingested at session start
├── log.md                # append-only transaction log (pending entries)
├── log.archive.md        # compiled/processed log entries (rotates when it gets big)
├── log.archive.<ts>.md   # rotated-out archive segments, once log.archive.md exceeds archive_max_bytes
├── config.yml            # llm_command override, archive_max_bytes
├── tools.json            # raw tool schemas for function-calling hosts
└── memory/
    ├── system_invariants.md
    ├── architecture.md
    ├── active_tasks.md
    ├── decisions.md
    └── domain_knowledge.md
    └── ...               # compile can create new memory files on demand
```

### CLI

```bash
bigbrain init                     # scaffold .bigbrain/ only
bigbrain install                  # scaffold + wire into AI tooling (recommended)
bigbrain index                    # print INDEX.md
bigbrain read <file_id>           # print one memory file
bigbrain grep <term>              # exact-substring fallback search when you don't know the file_id
bigbrain search <query>           # ranked fuzzy/word-overlap search when you don't know the exact wording either
bigbrain doctor [--fix]           # validate .bigbrain/ (stale locks, bad frontmatter, stale index); repair with --fix
bigbrain log --type DECISION --target decisions \
  --summary "Chose SQLite for log indexing" \
  --details "ACID writes matter under concurrent CLI runs."
bigbrain compile --reason "session end"        # reconcile log.md -> memory/*.md, rebuild INDEX.md
bigbrain compile --reason "session end" --llm  # same, but LLM-assisted dedup/contradiction-resolution
bigbrain status                   # JSON snapshot of engine state
bigbrain serve-mcp                # run the MCP stdio server
```

`--type` must be one of `DECISION`, `TASK_UPDATE`, `LEARNING`, `INVARIANT`.

### Deterministic vs. `--llm` compile

Plain `bigbrain compile` never calls a model: pending log entries are grouped
by target file and appended under a dated "Log Reconciliation" section. It's
free, instant, and can't fail in a surprising way — but memory files only
ever grow; nothing gets deduped or rewritten to resolve contradictions.

`bigbrain compile --llm` pipes each target file + its pending entries to a
configured LLM CLI and asks it to properly rewrite the file: merge related
facts, drop obsolete statements, and resolve contradictions in favor of the
newer entry — matching the reconciliation behavior in the original design
(`plan.md` §4, Phase 3). It needs a local LLM CLI:

- auto-detected from PATH (tries `claude -p`, then `llm`), or
- pinned explicitly in `.bigbrain/config.yml`:
  ```yaml
  llm_command: "claude -p"
  ```

`--llm` never risks your data: if the CLI is missing, times out, errors, or
returns output that doesn't parse as a valid memory file (frontmatter with an
`id` + non-empty body), that *one file* silently falls back to the
deterministic merge and a warning is printed — compile always succeeds.

### Archive rotation

`log.archive.md` accumulates every compiled log entry. Once it exceeds
`archive_max_bytes` (default 2MB, configurable in `.bigbrain/config.yml`), the
next compile rotates it to `log.archive.<timestamp>.md` and starts fresh, so
it doesn't grow without bound.

### `grep` vs `search`

- `bigbrain grep <term>` — exact, case-insensitive substring match. Use when
  you know the precise word/name/quote.
- `bigbrain search <query>` — deterministic word-overlap ranking across every
  memory file's body/title/tags, with a phrase-match bonus. Use when you know
  roughly what you're looking for but not the exact wording or which file it's
  in. This is **not** embeddings/vector search — BigBrain's core principle is
  no opaque embeddings — just explainable keyword scoring, good enough to
  replace "guess the file_id" at the scale a flat-file memory store is meant
  for. If your project outgrows this, that's a signal to split memory more,
  not to bolt on a vector DB.

### Concurrency

Every write path (`log`, `compile`) takes the same advisory lock
(`.bigbrain/.lock`), so two agent sessions (or an agent and the pre-commit
hook) writing at the same time serialize instead of interleaving/corrupting
files. A lock older than 120s is treated as abandoned and reclaimed
automatically; `bigbrain status` shows the current lock's pid and age if one
is held, and `bigbrain doctor --fix` will clear a stuck one manually.

### `doctor` (validation, repair, and schema migration)

`bigbrain doctor` checks for: a stale lock file, memory files missing
required frontmatter (`id`, `domain`, `last_updated`), duplicate `id`s across
files, a `log.md` containing content that doesn't match the expected entry
format (e.g. from hand-editing), an invalid `config.yml`, and a stale
`INDEX.md`. Run it plain to see what's wrong (exits 1 if anything is); run
`--fix` to repair everything that's safely auto-fixable (exits 0 once clean —
a fixed issue is never also reported as still-broken). The one thing it never
auto-fixes is malformed `log.md` content, since guessing what a corrupted
entry meant risks losing data — that always needs a human look.

Each memory file also carries a `schema_version` field; `doctor` stamps files
onto the current version. There's only ever been one version so far, but this
is the hook a future BigBrain release would register a real migration
against — `doctor --fix` is the migration command.

### How an agent is expected to use it

1. At session start, read `.bigbrain/INDEX.md` (`bigbrain index`) instead of
   guessing at project structure or past decisions.
2. Pull a specific memory file on demand (`bigbrain read architecture`) when
   it needs deep context on a domain.
3. Log non-trivial decisions, task-state changes, learnings, and invariants
   as they happen (`bigbrain log ...`), rather than trying to remember them.
4. Trigger compilation at milestones or session end (`bigbrain compile`) to
   reconcile the log into `memory/*.md` and rebuild `INDEX.md`.

### MCP server

For hosts with native MCP tool-calling, `bigbrain serve-mcp` exposes six
tools matching the schema in `bigbrain/schemas.py` / `.bigbrain/tools.json`:
`read_index`, `read_memory_file`, `append_transaction_log`, `compile_memory`
(with an optional `use_llm` argument), `search_memory` (ranked fuzzy
discovery), and `grep_memory` (exact substring). It speaks newline-delimited
JSON-RPC 2.0 over stdio — no MCP SDK dependency.

### Library usage

```python
from pathlib import Path
from bigbrain import core

core.init_engine(Path("."))
core.append_log(Path("."), "LEARNING", "domain_knowledge", "Payments API v2", "Uses cursor pagination.")
core.compile_memory(Path("."), reason="milestone")
```

### Tests

```bash
pip install -e .
python tests/test_core.py
```
