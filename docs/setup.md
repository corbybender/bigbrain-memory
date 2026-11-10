# Installing, upgrading and using source context

The README contains the installation commands. Install BigBrain's Python
package once per Python environment, then run `bigbrain install` in each
project. For an existing installation, upgrade the package and run
`bigbrain install --force` in each project. This refreshes generated agent
instructions and MCP tool schemas while preserving memory, project settings
and unrelated instruction/configuration content.

## What happens automatically

1. `bigbrain install` creates memory and integration files. It does not scan
   source or start a daemon.
2. The first `source-status`, `source-files`, `source-search`, `source-read` or
   source MCP call creates `.bigbrain/cache/source.sqlite3` and an ignore file
   that keeps cache contents out of Git.
3. Every subsequent source call reconciles the selected Git working tree,
   including eligible untracked and uncommitted files. Content hashes detect
   edits; changed files are reindexed and deleted/excluded files are removed.
   Renames and branch switches are handled on that next source call.
4. Unchanged content reuses its indexed chunks. Files are still read and hashed
   on each scan, so repository size affects query latency.

There is no background watcher. If no source tools are called, the cache is
not updated in the background. Memory `compile`, `status`, `index` and
`doctor` commands manage memory; `source-status` checks source coverage and
freshness. Memory compilation hooks do not refresh the source index.

## Verify an installation

Run in the target project:

```bash
bigbrain status
bigbrain index
bigbrain source-status
bigbrain source-files --limit 10
bigbrain source-search "a known identifier from your project"
```

The source status should have `complete: true` and a plausible `indexed_files`
count. A complete report covers eligible files, not excluded files. Inspect
`skipped`, `settings` and `errors` if expected content is missing. Use a real
project identifier in the last command. To verify automatic changes, edit an
eligible file, search for a new identifier, then undo that temporary edit.

The source tools require Git and SQLite FTS5. UTF-8 source, documentation and
configuration are eligible. Git ignores, credential filename exclusions,
dependency/cache directories, output exclusions and file-size limits apply
to browsing, searching and reading consistently. See the README's source
configuration section to change output exclusions or size limits.

## MCP and agent setup

The installer updates `AGENTS.md` and other supported agent instruction files,
and registers the server in `.mcp.json` and `.cursor/mcp.json`. It also writes
`.bigbrain/tools.json` for custom function-calling hosts. Other MCP hosts must
use their own server registration mechanism to launch `bigbrain --path
<absolute-project-root> serve-mcp`; the installer does not configure every
host application automatically.

After upgrading, restart/reconnect the host and verify that it lists all five
source tools: `source_status`, `list_source_files`, `refresh_source_index`,
`search_source` and `read_source`, alongside the six memory tools. An already
running server retains its loaded Python modules until restarted. Package
upgrade alone does not refresh existing generated project instructions.

New project MCP registrations use absolute roots. Rerun `bigbrain install
--force` after moving/cloning a project. Each MCP server instance uses its
configured project root; running a source CLI command in a different project
does not retarget an existing MCP server.

Agents should read memory for project decisions, browse/search current source,
and read relevant lines before editing. Source results include hashes and a
coverage/freshness report. Inspect `complete` and errors before inferring that
missing search results mean missing code. Files may change after a scan.

## Windows: multiple Python installations

Check which executables you are using in PowerShell:

```powershell
Get-Command python, bigbrain | Select-Object Name, Source
python -m pip show bigbrain-memory
```

If `python` and `bigbrain` belong to different installations, upgrade using the
Python executable belonging to the selected BigBrain installation. For the
usual Windows `Scripts\bigbrain.exe` layout, resolve that interpreter with:

```powershell
$bbPython = Join-Path (Split-Path (Split-Path (Get-Command bigbrain).Source)) 'python.exe'
& $bbPython -m pip install --upgrade 'git+https://github.com/corbybender/bigbrain-memory.git'
& $bbPython -c "import importlib.metadata; print(importlib.metadata.version('bigbrain-memory'))"
```

For virtual environments or a different launcher layout, activate that
environment or use its actual Python executable. Then refresh the project's
installation and reconnect its MCP host as described above.

## Recovery

- No source tools in the host: check package version, run `bigbrain install
  --force` in the target project, and reconnect the server. For other MCP
  hosts, check their configured command and root too.
- Source discovery fails: verify Git is on PATH and `git status` succeeds
  in the selected project. Memory remains usable outside a Git working tree.
- Missing files: inspect Git ignores and source exclusions before rebuilding.
  Rebuilding does not override exclusions or support binary/non-UTF-8 files.
- Corrupt or incompatible cache: run `bigbrain source-refresh --rebuild`.
  This discards derived source data and leaves Markdown memory intact.
- `complete: false`: resolve the reported file read errors and query again.
  The CLI exits 1 for incomplete coverage; MCP clients must inspect the report.
- FTS5 unavailable: use a Python/SQLite build with FTS5 enabled. Confirm with
  `python -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute('CREATE VIRTUAL TABLE t USING fts5(text)'); print('FTS5 available')"`.
