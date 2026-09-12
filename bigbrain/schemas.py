"""Canonical tool schemas and boot prompt text for BigBrain.

These are the source of truth used by:
- the MCP server (bigbrain.mcp_server), for hosts with native tool-calling
- the generated AGENTS.md / CLAUDE.md wiring (bigbrain.install), for hosts
  that only have shell access
"""
from __future__ import annotations

LOG_TYPES = ["DECISION", "TASK_UPDATE", "LEARNING", "INVARIANT"]

TOOLS = [
    {
        "name": "read_index",
        "description": "Reads the current BigBrain INDEX.md catalog to discover available memory files.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_memory_file",
        "description": "Reads a specific memory markdown file from the BigBrain memory store.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "The File ID as listed in INDEX.md (e.g., 'architecture', 'active_tasks')",
                }
            },
            "required": ["file_id"],
        },
    },
    {
        "name": "append_transaction_log",
        "description": "Appends an atomic insight, decision, or state change to the session transaction log.",
        "parameters": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": LOG_TYPES,
                    "description": "Category of log entry",
                },
                "target_file_id": {
                    "type": "string",
                    "description": "The destination memory file ID to be updated during compile",
                },
                "summary": {
                    "type": "string",
                    "description": "Concise summary of the update",
                },
                "details": {
                    "type": "string",
                    "description": "Full context, technical details, code snippets, or rationale",
                },
            },
            "required": ["type", "target_file_id", "summary", "details"],
        },
    },
    {
        "name": "compile_memory",
        "description": "Triggers the BigBrain compiler to parse log.md, reconcile memory markdown files, and rebuild INDEX.md.",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Reason for triggering compilation (e.g., 'Milestone reached', 'Session end')",
                },
                "use_llm": {
                    "type": "boolean",
                    "description": (
                        "If true, use a configured LLM CLI to properly dedupe/resolve contradictions "
                        "per file instead of the default deterministic append-merge. Falls back to the "
                        "deterministic merge automatically for any file where the LLM call fails."
                    ),
                    "default": False,
                },
            },
            "required": ["reason"],
        },
    },
    {
        "name": "search_memory",
        "description": (
            "Ranked, fuzzy/word-overlap discovery across memory files for when you know roughly what "
            "you're looking for but not the exact wording or which file_id it lives in. Deterministic "
            "word-overlap scoring, not embeddings. Prefer read_index first; use grep_memory instead "
            "when you know the exact substring/quote to find."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language description of what to find"},
                "top_n": {"type": "integer", "description": "Max results to return", "default": 8},
            },
            "required": ["query"],
        },
    },
    {
        "name": "grep_memory",
        "description": (
            "Exact case-insensitive substring search across memory files (and optionally the "
            "transaction log). Use when you know the precise word, name, or phrase to find."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "Exact text to search for (case-insensitive substring)"},
                "include_log": {
                    "type": "boolean",
                    "description": "Also search the pending and archived transaction logs",
                    "default": False,
                },
            },
            "required": ["term"],
        },
    },
]

BOOT_PROMPT = """You are operating under the BigBrain memory system.
Below is the catalog of project memory (.bigbrain/INDEX.md).
If you require deep context on a domain, read the relevant memory file before assuming project structure or past decisions.
Log every non-trivial decision, architectural change, or task update to the transaction log.
Periodically (or at natural milestones / session end) trigger compilation so the log is reconciled into memory files and INDEX.md is rebuilt.
"""


def shell_wiring_block(cli_name: str = "bigbrain") -> str:
    """Universal instructions for hosts that only have shell/bash access
    (i.e. every coding agent, regardless of native tool-calling support).
    """
    return f"""<!-- BEGIN BIGBRAIN -->
## BigBrain Memory System

This project uses [BigBrain](https://github.com/) for deterministic,
filesystem-first memory. All state lives in plain Markdown under `.bigbrain/`.

{BOOT_PROMPT}
### Available commands (run via shell)

| Action | Command |
| :--- | :--- |
| Read the index (do this at session start) | `{cli_name} index` |
| Read one memory file | `{cli_name} read <file_id>` |
| Find a file by exact word/phrase | `{cli_name} grep <term>` |
| Find a file by rough description (unknown wording) | `{cli_name} search <query>` |
| Log a decision/task/learning/invariant | `{cli_name} log --type <{'|'.join(LOG_TYPES)}> --target <file_id> --summary "..." --details "..."` |
| Reconcile the log into memory + rebuild the index | `{cli_name} compile --reason "..."` |
| Same, with LLM-assisted dedup/contradiction-resolution | `{cli_name} compile --reason "..." --llm` |
| Inspect engine state | `{cli_name} status` |
| Validate and repair .bigbrain/ (stale locks, missing frontmatter, stale index, schema migration) | `{cli_name} doctor --fix` |

Rules:
- Read `.bigbrain/INDEX.md` (via `{cli_name} index`) before assuming project structure, past decisions, or invariants.
- Never hand-edit files under `.bigbrain/memory/` or `.bigbrain/INDEX.md` directly — write through `{cli_name} log` and `{cli_name} compile` so the index stays consistent.
- Log non-trivial decisions, architecture changes, and task-state updates as they happen, not in a batch at the end.
- `{cli_name} compile` alone is deterministic and needs no API key/model access — it's always safe to run. `--llm` is an opt-in upgrade that asks a configured LLM CLI (see `.bigbrain/config.yml`) to properly merge/dedupe each file instead of appending; it never loses data, since any file where the LLM call fails or looks malformed is compiled deterministically instead.
- A git pre-commit hook and (for Claude Code) SessionStart/SessionEnd/PreCompact hooks already call `{cli_name} index`/`{cli_name} compile` automatically — you generally don't need to remember to compile yourself, but do it explicitly after a big milestone.
- If a host-native BigBrain MCP tool (`read_index`, `read_memory_file`, `append_transaction_log`, `compile_memory`, `search_memory`, `grep_memory`) is available, prefer it over the shell commands above — they are equivalent.
<!-- END BIGBRAIN -->"""
