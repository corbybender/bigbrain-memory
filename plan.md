# System Specification: BigBrain Flat-File Memory & Context Engine

## 1. System Overview & Architecture

BigBrain is a deterministic, filesystem-first memory and context-management engine for LLMs. It replaces vector databases and semantic search with structured, human-readable Markdown files, a centrally maintained index catalog, and explicit two-tier context ingestion (Load Index -> Select File -> Read File -> Flush/Compile).

### Core Architectural Principles
1. **No Opaque Embeddings:** Information is stored in standard Markdown (`.md`) files with YAML frontmatter.
2. **Context Economy:** The LLM does not ingest the entire memory directory. It ingests only a lightweight `INDEX.md` at session start, requesting detailed topic files on demand.
3. **Deterministic Compaction:** Sessions append to an append-only transaction log (`log.md`). Memory compilation is a structured reconciliation step that updates targeted files and rebuilds `INDEX.md`.

```
                  +----------------------------------------------+
                  |                 LLM Context                  |
                  |  +--------------+       +-----------------+  |
                  |  | System Base  |  <--  | Ingest INDEX.md |  |
                  |  +--------------+       +-----------------+  |
                  |         |                       ^            |
                  |         v                       |            |
                  |  +--------------+       +-----------------+  |
                  |  | Memory Read  |       | Memory Write    |  |
                  +--+--------------+-------+-----------------+--+
                            |                       |
                 read_memory(file_id)      append_log(entry)
                            |                       |
                            v                       v
                   .bigbrain/memory/*.md       .bigbrain/log.md
                                                    |
                                                    v
                                         [Compilation / Flush]
                                                    |
                                         +----------+----------+
                                         |                     |
                                         v                     v
                                Updated *.md               Rebuilt INDEX.md
```

---

## 2. Directory Layout & Schemas

All runtime assets reside in a `.bigbrain/` directory at the project root:

```text
.bigbrain/
├── INDEX.md
├── log.md
└── memory/
    ├── system_invariants.md
    ├── architecture.md
    ├── active_tasks.md
    ├── decisions.md
    └── domain_knowledge.md
```

### 2.1 File Schemas

#### A. Central Index (`.bigbrain/INDEX.md`)
Generated deterministically by the compile process. Ingested into the LLM system prompt.

```markdown
# BigBrain System Index
> Last Compiled: 2026-09-12T07:45:00Z | Active Files: 5 | Schema Version: 1.0.0

| File ID | Path | Domain | Summary | Token Est |
| :--- | :--- | :--- | :--- | :--- |
| `sys_invariants` | `memory/system_invariants.md` | Core | Non-negotiable technical bounds, platform rules, CLI conventions | 420 |
| `arch` | `memory/architecture.md` | Tech | Component boundaries, IPC interfaces, data pipelines | 1,250 |
| `tasks` | `memory/active_tasks.md` | State | Current execution state, milestones, blockers, task queues | 380 |
| `decisions` | `memory/decisions.md` | History | Architectural Decision Records (ADRs) with context and rationale | 910 |
| `domain_ref` | `memory/domain_knowledge.md` | Context | Business rules, schemas, external system API contracts | 1,600 |
```

#### B. Memory Leaf Files (`.bigbrain/memory/<file_id>.md`)
Each file maintains structured YAML frontmatter for machine parsing, followed by Markdown headings.

```markdown
---
id: architecture
title: System Architecture & Boundaries
domain: Tech
last_updated: 2026-09-12T07:45:00Z
tags: [ipc, engine, storage]
---

## 1. Engine Core
...
```

#### C. Transaction Log (`.bigbrain/log.md`)
Append-only log for active session traces, thoughts, decisions, and completed actions prior to compilation.

```markdown
# BigBrain Transaction Log

## [2026-09-12T07:50:12Z] - SESSION_ID: a9f83e20
- TYPE: DECISION
- TARGET: memory/decisions.md
- CONTENT: Chose SQLite for log indexing instead of JSONL to support ACID writes under concurrent CLI runs.
---
```

---

## 3. Tool Calling & API Interfaces

The local model must be provided with four core tools:

```json
[
  {
    "name": "read_index",
    "description": "Reads the current BigBrain INDEX.md catalog to discover available memory files.",
    "parameters": {
      "type": "object",
      "properties": {},
      "required": []
    }
  },
  {
    "name": "read_memory_file",
    "description": "Reads a specific memory markdown file from the BigBrain memory store.",
    "parameters": {
      "type": "object",
      "properties": {
        "file_id": {
          "type": "string",
          "description": "The File ID as listed in INDEX.md (e.g., 'architecture', 'active_tasks')"
        }
      },
      "required": ["file_id"]
    }
  },
  {
    "name": "append_transaction_log",
    "description": "Appends an atomic insight, decision, or state change to the session transaction log.",
    "parameters": {
      "type": "object",
      "properties": {
        "type": {
          "type": "string",
          "enum": ["DECISION", "TASK_UPDATE", "LEARNING", "INVARIANT"],
          "description": "Category of log entry"
        },
        "target_file_id": {
          "type": "string",
          "description": "The destination memory file ID to be updated during compile"
        },
        "summary": {
          "type": "string",
          "description": "Concise summary of the update"
        },
        "details": {
          "type": "string",
          "description": "Full context, technical details, code snippets, or rationale"
        }
      },
      "required": ["type", "target_file_id", "summary", "details"]
    }
  },
  {
    "name": "compile_memory",
    "description": "Triggers the BigBrain compiler to parse log.md, reconcile memory markdown files, and rebuild INDEX.md.",
    "parameters": {
      "type": "object",
      "properties": {
        "reason": {
          "type": "string",
          "description": "Reason for triggering compilation (e.g., 'Milestone reached', 'Session end')"
        }
      },
      "required": ["reason"]
    }
  }
]
```

---

## 4. Execution Lifecycle & Operational Protocols

### Phase 1: Boot & Ingestion
1. Harness loads `.bigbrain/INDEX.md`.
2. Harness prepends system prompt with:
   ```text
   You are operating under the BigBrain memory system.
   Below is the catalog of project memory (INDEX.md).
   If you require deep context on a domain, call `read_memory_file(file_id)`.
   Do not guess at project structure or past decisions if a relevant memory file exists.
   Log every non-trivial decision, architectural change, or task update using `append_transaction_log`.
   ```
3. The catalog content is appended directly below the prompt.

### Phase 2: Active Task Execution
- When the model encounters a task involving specific domain logic, it issues `read_memory_file`.
- When an invariant, architecture change, or new requirement is identified:
  - Model calls `append_transaction_log(...)`.
  - Transaction is validated against allowed types and appended to `.bigbrain/log.md`.

### Phase 3: Compilation (Reconciliation & Index Rebuilding)
Triggered explicitly via CLI command (`bigbrain compile`), through the `compile_memory` tool call, or at session end.

1. **Locking:** Acquire file lock `.bigbrain/.lock` to prevent concurrent write collisions.
2. **Log Parse:** Read uncompiled entries from `log.md`. Group entries by `target_file_id`.
3. **Reconciliation Pass (LLM-driven or AST merge):**
   - For each targeted `.bigbrain/memory/<file_id>.md`:
     - Load existing file content and pending log entries.
     - Execute a strict deduplication/compaction prompt:
       ```text
       Integrate the following transaction log entries into the existing markdown document.
       Maintain existing Markdown structure and YAML frontmatter.
       Remove obsolete statements, resolve contradictions in favor of newer log entries,
       and update the `last_updated` frontmatter field.
       Output ONLY the updated file contents.
       ```
     - Write back atomically via temporary file rename (`<file>.tmp` -> `<file>.md`).
4. **Index Rebuild:**
   - Scan `.bigbrain/memory/*.md`.
   - Parse YAML frontmatter (ID, Domain, Tags).
   - Generate a single-sentence summary for each file (first paragraph or description tag).
   - Calculate rough token counts (chars / 4).
   - Rewrite `.bigbrain/INDEX.md`.
5. **Log Truncation:** Clear processed entries from `log.md` (or rotate to `log.archive.md`).
6. **Unlock:** Remove `.bigbrain/.lock`.

---

## 5. Reference Implementation: Python Core Engine

Save as `bigbrain.py`. Provides both an importable library and a CLI interface.

```python
#!/usr/bin/env python3
import os
import sys
import yaml
import time
import glob
from pathlib import Path
from typing import Dict, Any

BIG_BRAIN_DIR = Path(".bigbrain")
MEMORY_DIR = BIG_BRAIN_DIR / "memory"
INDEX_FILE = BIG_BRAIN_DIR / "INDEX.md"
LOG_FILE = BIG_BRAIN_DIR / "log.md"
LOCK_FILE = BIG_BRAIN_DIR / ".lock"


def init_engine():
    """Initializes the BigBrain filesystem structure."""
    BIG_BRAIN_DIR.mkdir(exist_ok=True)
    MEMORY_DIR.mkdir(exist_ok=True)

    if not LOG_FILE.exists():
        LOG_FILE.write_text("# BigBrain Transaction Log\n\n", encoding="utf-8")

    # Seed baseline memory files if empty
    defaults = {
        "system_invariants.md": (
            "---\nid: system_invariants\ntitle: System Invariants\ndomain: Core\n"
            "tags: [invariants, rules]\n---\n\n## Core Rules\n"
            "- Deterministic execution over probabilistic inference.\n"
        ),
        "architecture.md": (
            "---\nid: architecture\ntitle: Architecture\ndomain: Tech\n"
            "tags: [arch, design]\n---\n\n## Component Overview\n"
        ),
        "active_tasks.md": (
            "---\nid: active_tasks\ntitle: Active Tasks\ndomain: State\n"
            "tags: [tasks, roadmap]\n---\n\n## Current Milestone\n"
        ),
        "decisions.md": (
            "---\nid: decisions\ntitle: Decisions\ndomain: History\n"
            "tags: [adr, history]\n---\n\n## Decision Register\n"
        ),
    }

    for filename, content in defaults.items():
        filepath = MEMORY_DIR / filename
        if not filepath.exists():
            filepath.write_text(content, encoding="utf-8")

    rebuild_index()


def parse_frontmatter(content: str) -> tuple[Dict[str, Any], str]:
    """Extracts YAML frontmatter and body from markdown."""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1])
                return (fm or {}), parts[2].strip()
            except yaml.YAMLError:
                pass
    return {}, content.strip()


def rebuild_index():
    """Deterministic, non-LLM index generator based on frontmatter and token estimates."""
    memory_files = glob.glob(str(MEMORY_DIR / "*.md"))
    rows = []

    for f_path in sorted(memory_files):
        path_obj = Path(f_path)
        content = path_obj.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)

        file_id = fm.get("id", path_obj.stem)
        domain = fm.get("domain", "General")
        rel_path = f"memory/{path_obj.name}"

        # First line of body as summary fallback
        first_line = "No description"
        for line in body.splitlines():
            clean = line.strip().lstrip("#").strip()
            if clean:
                first_line = clean[:80] + ("..." if len(clean) > 80 else "")
                break

        token_est = len(content) // 4
        rows.append(f"| `{file_id}` | `{rel_path}` | {domain} | {first_line} | {token_est} |")

    index_content = (
        f"# BigBrain System Index\n"
        f"> Last Compiled: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} | "
        f"Active Files: {len(rows)}\n\n"
        f"| File ID | Path | Domain | Summary | Token Est |\n"
        f"| :--- | :--- | :--- | :--- | :--- |\n"
        + "\n".join(rows)
        + "\n"
    )

    INDEX_FILE.write_text(index_content, encoding="utf-8")
    print(f"[BigBrain] Rebuilt INDEX.md with {len(rows)} entries.")


def append_log(entry_type: str, target: str, summary: str, details: str):
    """Atomically appends an entry to the transaction log."""
    timestamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    entry = (
        f"\n## [{timestamp}] - TYPE: {entry_type.upper()}\n"
        f"- TARGET: {target}\n"
        f"- SUMMARY: {summary}\n"
        f"### Details\n{details}\n\n---\n"
    )
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(entry)
    print(f"[BigBrain] Logged {entry_type} targeting {target}")


def read_memory(file_id: str) -> str:
    """Retrieves file contents by file_id matching frontmatter or filename."""
    for f_path in glob.glob(str(MEMORY_DIR / "*.md")):
        path_obj = Path(f_path)
        content = path_obj.read_text(encoding="utf-8")
        fm, _ = parse_frontmatter(content)
        if fm.get("id") == file_id or path_obj.stem == file_id:
            return content
    raise FileNotFoundError(f"Memory file with ID '{file_id}' not found.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: bigbrain.py [init|rebuild-index|read <file_id>]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "init":
        init_engine()
    elif cmd == "rebuild-index":
        rebuild_index()
    elif cmd == "read" and len(sys.argv) > 2:
        print(read_memory(sys.argv[2]))
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
```

---

## 6. Implementation Verification Test Plan

| Step | Action | Expected Output / Invariant |
| :--- | :--- | :--- |
| **1. Init** | Execute `python bigbrain.py init` | Creates `.bigbrain/`, `.bigbrain/memory/`, default markdown files, baseline `log.md`, and compiles `.bigbrain/INDEX.md`. |
| **2. Index Validation** | Inspect `.bigbrain/INDEX.md` | Contains valid Markdown table with columns: File ID, Path, Domain, Summary, Token Est. |
| **3. Read Tool** | Execute `python bigbrain.py read architecture` | Returns contents of `.bigbrain/memory/architecture.md` including YAML frontmatter. |
| **4. Log Append** | Call `append_log(...)` via harness or CLI | Appends structured entry to `log.md` without modifying files in `memory/`. |
| **5. Reconciliation** | Run compilation cycle | Updates designated `memory/*.md`, clears processed `log.md` records, and updates `INDEX.md` timestamps and token counts. |
