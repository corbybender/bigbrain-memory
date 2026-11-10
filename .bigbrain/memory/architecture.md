---
id: architecture
title: System Architecture & Boundaries
domain: Tech
last_updated: '2026-11-10T15:54:33Z'
tags:
- arch
- design
schema_version: 1.0.0
---

## Component Overview

## Log Reconciliation (2026-11-10T15:54:33Z)
- **[DECISION]** Add a derived source index alongside existing memory
  - Approved first release: Git-aware incremental UTF-8 source indexing, ignored SQLite cache, bounded CLI/MCP source search and reads, freshness reconciliation before retrieval, and end-to-end regression tests. Memory interfaces remain compatible. Watchers and language-aware symbol graphs are deferred; query-time reconciliation provides automatic updates without a daemon.
- **[LEARNING]** Windows lock contention can raise access denied
  - Python 3.13 validation exposed an existing concurrency failure: exclusive lock creation can raise PermissionError while a deleted Windows lock is closing. Updated shared locking to retry bounded contention with a monotonic deadline and close descriptors reliably. Added deterministic transient/permanent permission tests. Also preserve owner-managed config during force install and bind new MCP registrations to explicit roots.
