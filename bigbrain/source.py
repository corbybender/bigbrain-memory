"""Rebuildable source context. Git owns discovery; SQLite owns derived search data.

Every retrieval reconciles the working tree, including uncommitted/untracked
files. No model calls, daemon, or changes to the memory store are required.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import sqlite3
import stat
import subprocess
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path, PurePosixPath

from . import core

VERSION = 2
DEFAULT_EXCLUDE = ["dist", "build", "generated", "coverage", "vendor"]
PRIVATE_DIRS = {".git", ".bigbrain", "node_modules", ".venv", "venv", "__pycache__"}
PRIVATE_FILES = {".env", ".npmrc", ".pypirc", "credentials", "id_rsa", "id_ed25519"}
PRIVATE_SUFFIXES = {".pem", ".key", ".pfx", ".p12", ".keystore"}


class SourceError(RuntimeError):
    """An actionable source-index failure; memory remains usable."""


class _Progress:
    def __init__(self, callback=None):
        self.callback = callback
        self.last = 0.0

    def emit(self, message, force=False):
        if self.callback is None:
            return
        now = time.monotonic()
        if force or now - self.last >= 1.0:
            self.callback(message)
            self.last = now


def _git(root: Path, *args: str, input_data=None, allow_no_match=False):
    try:
        result = subprocess.run(["git", "-C", str(root), *args], input=input_data,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SourceError("Source indexing requires Git and an accessible working tree.") from exc
    if result.returncode and not (allow_no_match and result.returncode == 1):
        raise SourceError("Git source discovery failed: " + result.stderr.decode("utf-8", "replace")[:500])
    return result.stdout


def _settings(root):
    cfg_path = root / ".bigbrain" / "config.yml"
    try:
        import yaml
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
        cfg = (cfg or {}).get("source", {})
        exclude = cfg.get("exclude", DEFAULT_EXCLUDE)
        size = cfg.get("max_file_bytes", 524288)
        if not isinstance(exclude, list) or not all(isinstance(x, str) for x in exclude):
            raise ValueError("source.exclude must be a list of patterns")
        if type(size) is not int or not 1 <= size <= 10_485_760:
            raise ValueError("source.max_file_bytes must be between 1 and 10485760")
        return {"exclude": exclude, "max_file_bytes": size}
    except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError) as exc:
        raise SourceError("Invalid source configuration: " + str(exc)) from exc


def _excluded(rel, settings):
    p = PurePosixPath(rel)
    parts = [x.lower() for x in p.parts]
    if any(x in PRIVATE_DIRS for x in parts):
        return True
    if p.name.lower() in PRIVATE_FILES or p.name.lower().startswith(".env."):
        return True
    if p.suffix.lower() in PRIVATE_SUFFIXES:
        return True
    return any(fnmatch.fnmatchcase(rel, pattern) or
               any(fnmatch.fnmatchcase(part, pattern) for part in p.parts)
               for pattern in settings["exclude"])


def _is_link(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _safe_path(root, rel):
    # Accept Windows-style relative paths even on non-Windows hosts.
    rel = rel.replace("\\", "/")
    p = PurePosixPath(rel)
    if p.is_absolute() or ".." in p.parts or ":" in rel or not p.parts:
        raise SourceError("Source path must be relative and remain inside the project.")
    target = root.joinpath(*p.parts)
    try:
        target.resolve().relative_to(root)
    except (ValueError, RuntimeError) as exc:
        raise SourceError("Source path escapes the project.") from exc
    current = root
    for part in p.parts:
        current = current / part
        if _is_link(current):
            raise SourceError("Source links and junctions are excluded.")
    return target


def _snapshot(root, progress=None):
    progress = progress or _Progress()
    progress.emit("Discovering source paths with Git...", force=True)
    settings = _settings(root)
    raw = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", ".")
    # --no-index also excludes tracked files matching ignore rules.
    ignored = _git(root, "check-ignore", "--no-index", "-z", "--stdin",
                   input_data=raw, allow_no_match=True) if raw else b""
    ignored_set = set(ignored.split(b"\0"))
    files, skipped, errors = {}, Counter(), []
    names = sorted(set(raw.split(b"\0")) - {b""})
    progress.emit(f"Scanning {len(names):,} discovered paths...", force=True)
    for number, name in enumerate(names, 1):
        progress.emit(f"Scanning source: {number:,}/{len(names):,} paths; {len(files):,} eligible files")
        try:
            rel = name.decode("utf-8")
        except UnicodeDecodeError:
            skipped["non_utf8_path"] += 1
            continue
        if name in ignored_set or _excluded(rel, settings):
            skipped["excluded"] += 1
            continue
        try:
            path = _safe_path(root, rel)
            info = path.stat()
            if not stat.S_ISREG(info.st_mode):
                skipped["not_regular"] += 1
                continue
            if info.st_size > settings["max_file_bytes"]:
                skipped["too_large"] += 1
                continue
            with path.open("rb") as stream:
                data = stream.read(settings["max_file_bytes"] + 1)
            if len(data) > settings["max_file_bytes"]:
                skipped["too_large"] += 1
                continue
            if b"\0" in data:
                skipped["binary"] += 1
                continue
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                skipped["non_utf8"] += 1
                continue
            files[rel] = (hashlib.sha256(data).hexdigest(), text, len(data))
        except FileNotFoundError:
            skipped["missing"] += 1
        except SourceError:
            skipped["unsafe_path"] += 1
        except OSError as exc:
            errors.append({"path": rel, "error": str(exc)[:300]})
    progress.emit(f"Scan complete: {len(files):,} eligible files; {len(errors):,} read errors", force=True)
    return files, {"skipped": dict(skipped), "errors": errors[:50], "error_count": len(errors),
                   "errors_truncated": len(errors) > 50, "settings": settings}


def _tokens(text):
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return re.findall(r"[^\W_]+", text.lower(), flags=re.UNICODE)


def _connect(db):
    conn = sqlite3.connect(str(db), timeout=15)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, hash TEXT, text TEXT, bytes INTEGER)")
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(path, terms, text UNINDEXED, start UNINDEXED, end UNINDEXED)")
        version = conn.execute("SELECT value FROM meta WHERE key='version'").fetchone()
        if version and version[0] not in ("1", str(VERSION)):
            raise SourceError("Unsupported source index version; run source-refresh --rebuild.")
        conn.execute("CREATE TABLE IF NOT EXISTS chunk_paths (chunk_id INTEGER PRIMARY KEY, path TEXT NOT NULL)")
        conn.execute("CREATE INDEX IF NOT EXISTS chunk_paths_by_path ON chunk_paths(path)")
        if version and version[0] == "1":
            # Upgrade derived metadata in place, without rereading/reindexing
            # unchanged files or touching any Markdown memory.
            conn.execute("DELETE FROM chunk_paths")
            conn.execute("INSERT INTO chunk_paths SELECT rowid, path FROM chunks")
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('version', ?)", (str(VERSION),))
        conn.commit()
        return conn
    except Exception:
        conn.close()
        raise


def _root(root):
    root = Path(root).resolve()
    if not root.is_dir():
        raise SourceError("Project root does not exist.")
    return root


def _cache(root):
    cache = root / ".bigbrain" / "cache"
    for p in (cache.parent, cache):
        if _is_link(p):
            raise SourceError("Source cache directory cannot be a link.")
    cache.mkdir(parents=True, exist_ok=True)
    ignore = cache / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n", encoding="utf-8")
    db = cache / "source.sqlite3"
    if _is_link(db):
        raise SourceError("Source cache cannot be a link.")
    return db


def _delete_chunks(conn, rel):
    conn.execute("DELETE FROM chunks WHERE rowid IN (SELECT chunk_id FROM chunk_paths WHERE path=?)", (rel,))
    conn.execute("DELETE FROM chunk_paths WHERE path=?", (rel,))


def refresh(root, rebuild=False, progress=None):
    """Hash current eligible files; transactionally replace changed chunks only."""
    root = _root(root)
    if type(rebuild) is not bool:
        raise SourceError("rebuild must be a boolean.")
    db = _cache(root)
    progress = _Progress(progress)
    progress.emit("Waiting for the source index lock...", force=True)
    lock = replace(core.paths(root), lock_file=db.parent / "source.lock")
    with core.file_lock(lock, timeout=30, stale_after=3600):
        files, report = _snapshot(root, progress)
        if rebuild and db.exists():
            db.unlink()  # Derived data only; memory is never touched.
        conn = None
        try:
            progress.emit("Opening source cache (upgrading derived metadata if needed)...", force=True)
            conn = _connect(db)
            with conn:
                old = dict(conn.execute("SELECT path, hash FROM files"))
                removed = set(old) - set(files)
                for rel in removed:
                    conn.execute("DELETE FROM files WHERE path=?", (rel,))
                    _delete_chunks(conn, rel)
                updated = 0
                progress.emit(f"Updating source index: {len(files):,} eligible files...", force=True)
                for number, (rel, (digest, text, size)) in enumerate(files.items(), 1):
                    progress.emit(f"Updating source index: {number:,}/{len(files):,} files; {updated:,} changed")
                    if old.get(rel) == digest:
                        continue
                    updated += 1
                    conn.execute("INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?)", (rel, digest, text, size))
                    if rel in old:
                        _delete_chunks(conn, rel)
                    lines = text.splitlines()
                    for start in range(0, max(1, len(lines)), 40):
                        chunk = "\n".join(lines[start:start + 40])
                        cursor = conn.execute("INSERT INTO chunks VALUES (?, ?, ?, ?, ?)",
                                              (rel, " ".join(_tokens(rel + " " + chunk)), chunk, start + 1,
                                               min(start + 40, len(lines))))
                        conn.execute("INSERT INTO chunk_paths VALUES (?, ?)", (cursor.lastrowid, rel))
                stamp = core._now()
                report.update({"indexed_files": len(files), "updated": updated, "removed": len(removed),
                               "unchanged": len(files) - updated, "checked_at": stamp,
                               "complete": not report["errors"], "root": str(root),
                               "freshness": "working-tree snapshot; files may change after checked_at"})
                conn.execute("INSERT OR REPLACE INTO meta VALUES ('report', ?)", (json.dumps(report),))
                progress.emit("Committing source index...", force=True)
        except sqlite3.Error as exc:
            raise SourceError("Source cache unavailable; run source-refresh --rebuild. " + str(exc)) from exc
        finally:
            if conn is not None:
                conn.close()
    progress.emit(f"Source index ready: {len(files):,} files; {updated:,} updated; {len(removed):,} removed", force=True)
    return report


def status(root, progress=None):
    # A status check is a real reconciliation, not an unverified timestamp.
    return refresh(root, progress=progress)


def _limit(value, name, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise SourceError(f"{name} must be an integer between 1 and {maximum}.")


def search(root, query, top_n=8, progress=None):
    _limit(top_n, "top_n", 50)
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise SourceError("query must contain 1 to 2000 characters.")
    terms = list(dict.fromkeys(_tokens(query)))[:32]
    report = refresh(root, progress=progress)
    if not terms:
        return {"status": report, "results": []}
    match = " OR ".join('"' + term + '"' for term in terms)
    conn = None
    try:
        conn = sqlite3.connect(str(_cache(_root(root))))
        conn.execute("BEGIN")
        report = json.loads(conn.execute("SELECT value FROM meta WHERE key='report'").fetchone()[0])
        cursor = conn.execute("SELECT path, text, start, end, bm25(chunks) FROM chunks WHERE chunks MATCH ? ORDER BY bm25(chunks), path, CAST(start AS INTEGER)", (match,))
        rows, seen = [], set()
        for row in cursor:
            if row[0] not in seen:
                rows.append(row)
                seen.add(row[0])
            if len(rows) == top_n:
                break
        hashes = dict(conn.execute("SELECT path, hash FROM files"))
    except sqlite3.Error as exc:
        raise SourceError("Source search failed; run source-refresh --rebuild. " + str(exc)) from exc
    finally:
        if conn is not None:
            conn.close()
    results = []
    for p, text, start, end, score in rows:
        lines = text.splitlines() or [""]
        best = max(range(len(lines)), key=lambda i: len(set(_tokens(lines[i])) & set(terms)))
        lo, hi = max(0, best - 2), min(len(lines), best + 4)
        excerpt = "\n".join(lines[lo:hi])
        results.append({"path": p, "start_line": int(start) + lo, "end_line": int(start) + hi - 1,
                        "excerpt": excerpt[:1600], "truncated": len(excerpt) > 1600 or lo > 0 or hi < len(lines),
                        "content_hash": hashes[p], "score": -score})
    return {"status": report, "results": results}


def read(root, path, start_line=1, max_lines=80, progress=None):
    _limit(start_line, "start_line", 10_000_000)
    _limit(max_lines, "max_lines", 200)
    if not isinstance(path, str) or not path:
        raise SourceError("path must be a nonempty project-relative string.")
    root = _root(root)
    rel = path.replace("\\", "/")
    _safe_path(root, rel)
    report = refresh(root, progress=progress)
    conn = sqlite3.connect(str(_cache(root)))
    try:
        conn.execute("BEGIN")
        report = json.loads(conn.execute("SELECT value FROM meta WHERE key='report'").fetchone()[0])
        row = conn.execute("SELECT hash, text FROM files WHERE path=?", (rel,)).fetchone()
    except sqlite3.Error as exc:
        raise SourceError("Source read failed; run source-refresh --rebuild. " + str(exc)) from exc
    finally:
        conn.close()
    if not row:
        raise SourceError("File is absent or excluded from source indexing.")
    digest, text = row
    lines = text.splitlines()
    selected = lines[start_line - 1:start_line - 1 + max_lines]
    excerpt = "\n".join(selected)
    return {"status": report, "path": rel, "content_hash": digest, "start_line": start_line,
            "end_line": start_line + len(selected) - 1, "total_lines": len(lines),
            "text": excerpt[:16000], "truncated": len(excerpt) > 16000 or start_line - 1 + len(selected) < len(lines)}


def list_files(root, prefix="", limit=100, offset=0, progress=None):
    """Bounded, deterministic inventory for agents that need to browse the tree."""
    _limit(limit, "limit", 200)
    if type(offset) is not int or not 0 <= offset <= 1_000_000:
        raise SourceError("offset must be an integer between 0 and 1000000.")
    if not isinstance(prefix, str):
        raise SourceError("prefix must be a project-relative string.")
    root = _root(root)
    prefix = prefix.replace("\\", "/")
    if prefix:
        _safe_path(root, prefix)
    refresh(root, progress=progress)
    conn = sqlite3.connect(str(_cache(root)))
    try:
        conn.execute("BEGIN")
        report = json.loads(conn.execute("SELECT value FROM meta WHERE key='report'").fetchone()[0])
        total = conn.execute("SELECT count(*) FROM files WHERE substr(path, 1, ?) = ?", (len(prefix), prefix)).fetchone()[0]
        rows = conn.execute("SELECT path, hash, bytes FROM files WHERE substr(path, 1, ?) = ? ORDER BY path LIMIT ? OFFSET ?",
                            (len(prefix), prefix, limit, offset)).fetchall()
    except sqlite3.Error as exc:
        raise SourceError("Source inventory failed; run source-refresh --rebuild. " + str(exc)) from exc
    finally:
        conn.close()
    return {"status": report, "total": total, "offset": offset, "has_more": offset + len(rows) < total,
            "files": [{"path": p, "content_hash": digest, "bytes": size, "extension": PurePosixPath(p).suffix}
                      for p, digest, size in rows]}
