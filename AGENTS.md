# BigBrain contributor instructions

Preserve the memory CLI/API and Markdown formats when extending source retrieval.
Keep source data disposable and excluded from Git; source operations must not rewrite memory.
Test with python tests/test_core.py, python -m unittest discover -s tests -p test_source.py -v, and python benchmarks/source_retrieval.py.
The benchmark measures keyword retrieval only; do not claim improved agent success from it.
Keep CLI, MCP schemas, installer wiring and README consistent.

<!-- BEGIN BIGBRAIN -->
## BigBrain Memory System

This project uses [BigBrain](https://github.com/corbybender/bigbrain-memory) for deterministic,
filesystem-first memory. Project memory lives in plain Markdown under `.bigbrain/`;
the optional source index is a disposable local cache.

You are operating under the BigBrain memory system.
Below is the catalog of project memory (.bigbrain/INDEX.md).
If you require deep context on a domain, read the relevant memory file before assuming project structure or past decisions.
Log every non-trivial decision, architectural change, or task update to the transaction log.
Periodically (or at natural milestones / session end) trigger compilation so the log is reconciled into memory files and INDEX.md is rebuilt.

### Available commands (run via shell)

| Action | Command |
| :--- | :--- |
| Read the index (do this at session start) | `bigbrain index` |
| Read one memory file | `bigbrain read <file_id>` |
| Find a file by exact word/phrase | `bigbrain grep <term>` |
| Find a file by rough description (unknown wording) | `bigbrain search <query>` |
| Search current source and docs | `bigbrain source-search "query"` |
| Browse indexed source files | `bigbrain source-files --prefix <directory/>` |
| Read bounded source lines | `bigbrain source-read <relative-path> --start-line 1 --max-lines 80` |
| Check source scope, errors and freshness | `bigbrain source-status` |
| Refresh/rebuild derived source cache | `bigbrain source-refresh [--rebuild]` |
| Log a decision/task/learning/invariant | `bigbrain log --type <DECISION|TASK_UPDATE|LEARNING|INVARIANT> --target <file_id> --summary "..." --details "..."` |
| Reconcile the log into memory + rebuild the index | `bigbrain compile --reason "..."` |
| Same, with LLM-assisted dedup/contradiction-resolution | `bigbrain compile --reason "..." --llm` |
| Inspect engine state | `bigbrain status` |
| Validate and repair .bigbrain/ (stale locks, missing frontmatter, stale index, schema migration) | `bigbrain doctor --fix` |

Rules:
- The first source tool call creates the source index automatically; every subsequent source call reconciles working-tree changes. No enable step or watcher setup is needed. Memory compile hooks do not refresh source in the background.
- When native source MCP tools are available, prefer `source_status`, `list_source_files`, `search_source`, `read_source` and `refresh_source_index` over the equivalent source CLI commands.
- Use source search/read tools for current implementation and memory tools for decisions and intent. Source queries reconcile changes automatically; check coverage/errors before assuming absence. Content hashes identify snapshots, not a guarantee that files cannot change afterward.
- Source indexing requires Git and stores disposable data under `.bigbrain/cache/`, separate from authoritative Markdown memory. Do not commit the cache. Symbols/call graphs are not available in this release.
- Read `.bigbrain/INDEX.md` (via `bigbrain index`) before assuming project structure, past decisions, or invariants.
- Never hand-edit files under `.bigbrain/memory/` or `.bigbrain/INDEX.md` directly — write through `bigbrain log` and `bigbrain compile` so the index stays consistent.
- Log non-trivial decisions, architecture changes, and task-state updates as they happen, not in a batch at the end.
- `bigbrain compile` alone is deterministic and needs no API key/model access — it's always safe to run. `--llm` is an opt-in upgrade that asks a configured LLM CLI (see `.bigbrain/config.yml`) to properly merge/dedupe each file instead of appending; it never loses data, since any file where the LLM call fails or looks malformed is compiled deterministically instead.
- A git pre-commit hook and (for Claude Code) SessionStart/SessionEnd/PreCompact hooks already call `bigbrain index`/`bigbrain compile` automatically — you generally don't need to remember to compile yourself, but do it explicitly after a big milestone.
- If a host-native BigBrain MCP tool (`read_index`, `read_memory_file`, `append_transaction_log`, `compile_memory`, `search_memory`, `grep_memory`) is available, prefer it over the shell commands above — they are equivalent.
<!-- END BIGBRAIN -->
