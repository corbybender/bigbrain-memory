---
id: active_tasks
title: Active Tasks
domain: State
last_updated: '2026-11-10T16:44:04Z'
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

## Log Reconciliation (2026-11-10T15:57:09Z)
- **[TASK_UPDATE]** Upstream delivery pending write-capable GitHub authentication
  - Implementation committed locally as 18192f5 and installed as editable BigBrain 1.1.0. Final local Python 3.13 validation: 19 memory tests plus 25 source/integration tests pass, one real symlink test skipped; six benchmark queries find expected files. git push origin main failed because no non-interactive credential was available. GitHub CLI and connected GitHub app both use CGB2_Valmont, which has READ permission on corbybender/bigbrain-memory. Remote main remains 978fb18949814b3104b782beac0927c2cc3b0fce. Push and Windows/Linux CI verification remain pending an account with write access. Source cache is ignored; no source changes remain outside the local commits.

## Log Reconciliation (2026-11-10T16:04:18Z)
- **[TASK_UPDATE]** Upstream source indexing delivery complete; cross-platform CI passed
  - User switched GitHub login; git push origin main succeeded. Implementation and initial memory commits are upstream through a3e9227c38dd0bc740f0047fc641f1e325e30169. GitHub Actions run https://github.com/corbybender/bigbrain-memory/actions/runs/42850581163 passed all four matrix jobs: Windows and Ubuntu with Python 3.9 and 3.13, covering existing memory tests, source integration tests and retrieval benchmark. Prior authentication blocker is resolved. Recording this result as memory-only follow-up; no runtime changes.

## Log Reconciliation (2026-11-10T16:07:08Z)
- **[TASK_UPDATE]** Clarify fresh setup, upgrades and automatic source indexing
  - Documentation audit found that README covered source tools but needed explicit fresh-install/upgrade steps, lazy initialization, host reconnection and root relocation guidance. Added docs/setup.md with Windows interpreter checks, verification and recovery; updated directory layout, CLI and MCP tool lists and generated agent rules. Installer config template now documents optional source settings without changing defaults or overwriting existing config.

## Log Reconciliation (2026-11-10T16:09:16Z)
- **[TASK_UPDATE]** Setup documentation follow-up delivered and CI verified
  - README, docs/setup.md, installer config comments and generated agent guidance updates pushed in 8ca4ebc. All four Windows/Linux Python 3.9/3.13 jobs passed in https://github.com/corbybender/bigbrain-memory/actions/runs/42851350938. Fresh install, upgrade, lazy automatic indexing, host reconnection, moved roots and recovery are documented. No runtime indexing changes in this follow-up.

## Log Reconciliation (2026-11-10T16:44:04Z)
- **[TASK_UPDATE]** Diagnose silent slow initial indexing on a large repository
  - User source-status process on Q:\valedit2026 remains CPU-active with a growing SQLite cache after several minutes; Git discovers about 47848 paths before exclusions. Identified repeated full FTS path scans, including for brand-new files, in refresh. Implementing indexed chunk rowid mapping with in-place v1 cache migration, skipping deletes for new files, throttled stderr CLI progress and a synthetic multi-thousand-file regression benchmark. Existing user run left undisturbed and no memory files modified by diagnostics.
- **[TASK_UPDATE]** Large-repository indexing completed with progress and memory unchanged
  - Fix installed locally as 1.1.1. Stopped only verified original source-status worker PID 13740 after validating the new implementation; SQLite rolled back the interrupted derived-cache transaction. A user source-files command acquired the lock and completed the updated build: 16665 eligible files, zero read errors, schema v2. Follow-up source-status completed with zero updated/removed files. SHA-256 comparison of all 14 existing memory/log Markdown files found zero changes. Added indexed chunk mapping, no deletes for new files, in-place v1 migration, stderr progress and Ctrl+C rollback handling. All 19 memory and 28 source tests pass; one real Windows symlink test skips. Added 3000-file synthetic cold/warm/edit-delete scale benchmark and 1000-file CI smoke check.
