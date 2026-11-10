# BigBrain Log Archive


## [2026-11-10T15:42:39Z] - TYPE: DECISION
- TARGET: architecture
- SUMMARY: Add a derived source index alongside existing memory
### Details
Approved first release: Git-aware incremental UTF-8 source indexing, ignored SQLite cache, bounded CLI/MCP source search and reads, freshness reconciliation before retrieval, and end-to-end regression tests. Memory interfaces remain compatible. Watchers and language-aware symbol graphs are deferred; query-time reconciliation provides automatic updates without a daemon.
---

## [2026-11-10T15:47:49Z] - TYPE: TASK_UPDATE
- TARGET: active_tasks
- SUMMARY: Source indexing and CLI/MCP integration implemented
### Details
Added Git-aware discovery, UTF-8 eligibility/exclusions, SHA-256 change detection, transactional SQLite FTS5 chunks, automatic reconciliation before retrieval, bounded source reads, source status and rebuild. Added integration tests for Git changes and installed MCP stdio configuration. Six repository keyword retrieval benchmark questions found expected files within top five; this is a smoke benchmark, not an agent-performance claim. First Windows run exposed a connection cleanup bug and CRLF-sensitive test expectation; both corrected.
---

## [2026-11-10T15:54:33Z] - TYPE: LEARNING
- TARGET: architecture
- SUMMARY: Windows lock contention can raise access denied
### Details
Python 3.13 validation exposed an existing concurrency failure: exclusive lock creation can raise PermissionError while a deleted Windows lock is closing. Updated shared locking to retry bounded contention with a monotonic deadline and close descriptors reliably. Added deterministic transient/permanent permission tests. Also preserve owner-managed config during force install and bind new MCP registrations to explicit roots.
---

## [2026-11-10T15:56:16Z] - TYPE: TASK_UPDATE
- TARGET: active_tasks
- SUMMARY: BigBrain 1.1 source indexing validated and installed locally
### Details
Completed source inventory/search/read/status/rebuild through CLI and five MCP tools. All 19 existing tests and 25 new source/integration tests pass on Python 3.13; one real Windows symlink test skips for missing privilege, with a deterministic boundary test passing. Six keyword benchmark questions achieve recall@5 1.0. Added Windows/Linux Python 3.9/3.13 CI, reproducible benchmark evidence, README and contributor guidance. Installed editable package 1.1.0 for the existing bigbrain command. MCP hosts need reconnection to discover new tools. Watchers and language-aware symbols remain deferred; reconciliation is automatic at query time.
---

## [2026-11-10T15:57:09Z] - TYPE: TASK_UPDATE
- TARGET: active_tasks
- SUMMARY: Upstream delivery pending write-capable GitHub authentication
### Details
Implementation committed locally as 18192f5 and installed as editable BigBrain 1.1.0. Final local Python 3.13 validation: 19 memory tests plus 25 source/integration tests pass, one real symlink test skipped; six benchmark queries find expected files. git push origin main failed because no non-interactive credential was available. GitHub CLI and connected GitHub app both use CGB2_Valmont, which has READ permission on corbybender/bigbrain-memory. Remote main remains 978fb18949814b3104b782beac0927c2cc3b0fce. Push and Windows/Linux CI verification remain pending an account with write access. Source cache is ignored; no source changes remain outside the local commits.
---
