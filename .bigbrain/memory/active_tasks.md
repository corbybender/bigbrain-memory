---
id: active_tasks
title: Active Tasks
domain: State
last_updated: '2026-11-10T15:56:16Z'
tags:
- tasks
- roadmap
schema_version: 1.0.0
---

## Current Milestone

## Log Reconciliation (2026-11-10T15:54:33Z)
- **[TASK_UPDATE]** Source indexing and CLI/MCP integration implemented
  - Added Git-aware discovery, UTF-8 eligibility/exclusions, SHA-256 change detection, transactional SQLite FTS5 chunks, automatic reconciliation before retrieval, bounded source reads, source status and rebuild. Added integration tests for Git changes and installed MCP stdio configuration. Six repository keyword retrieval benchmark questions found expected files within top five; this is a smoke benchmark, not an agent-performance claim. First Windows run exposed a connection cleanup bug and CRLF-sensitive test expectation; both corrected.

## Log Reconciliation (2026-11-10T15:56:16Z)
- **[TASK_UPDATE]** BigBrain 1.1 source indexing validated and installed locally
  - Completed source inventory/search/read/status/rebuild through CLI and five MCP tools. All 19 existing tests and 25 new source/integration tests pass on Python 3.13; one real Windows symlink test skips for missing privilege, with a deterministic boundary test passing. Six keyword benchmark questions achieve recall@5 1.0. Added Windows/Linux Python 3.9/3.13 CI, reproducible benchmark evidence, README and contributor guidance. Installed editable package 1.1.0 for the existing bigbrain command. MCP hosts need reconnection to discover new tools. Watchers and language-aware symbols remain deferred; reconciliation is automatic at query time.
