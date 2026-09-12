"""Core engine for BigBrain: init, index, log, and deterministic compilation.

All functions take an explicit `root` (the target project's working
directory) so the engine can be used as a library from any host process,
not just the CLI. `root` defaults to the current working directory.
"""
from __future__ import annotations

import contextlib
import glob
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

SCHEMA_VERSION = "1.0.0"
LOG_TYPES = ("DECISION", "TASK_UPDATE", "LEARNING", "INVARIANT")
DEFAULT_ARCHIVE_MAX_BYTES = 2_000_000

_TYPE_DOMAIN = {
    "DECISION": "History",
    "TASK_UPDATE": "State",
    "LEARNING": "Context",
    "INVARIANT": "Core",
}

_LOG_ENTRY_RE = re.compile(
    r"^## \[(?P<timestamp>[^\]]+)\] - TYPE: (?P<type>\w+)\n"
    r"- TARGET: (?P<target>[^\n]+)\n"
    r"- SUMMARY: (?P<summary>[^\n]*)\n"
    r"### Details\n(?P<details>.*?)\n---\n?",
    re.MULTILINE | re.DOTALL,
)

LOG_HEADER = "# BigBrain Transaction Log\n\n"


@dataclass
class Paths:
    root: Path
    big_brain_dir: Path
    memory_dir: Path
    index_file: Path
    log_file: Path
    archive_file: Path
    lock_file: Path


def paths(root: Optional[Path] = None) -> Paths:
    root = Path(root) if root is not None else Path.cwd()
    bb = root / ".bigbrain"
    return Paths(
        root=root,
        big_brain_dir=bb,
        memory_dir=bb / "memory",
        index_file=bb / "INDEX.md",
        log_file=bb / "log.md",
        archive_file=bb / "log.archive.md",
        lock_file=bb / ".lock",
    )


def load_config(root: Optional[Path] = None) -> Dict[str, Any]:
    """Reads .bigbrain/config.yml. Missing file/keys just mean defaults."""
    p = paths(root)
    cfg_file = p.big_brain_dir / "config.yml"
    if not cfg_file.exists():
        return {}
    try:
        return yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + f".tmp{uuid.uuid4().hex[:8]}")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


class LockError(RuntimeError):
    pass


@contextlib.contextmanager
def file_lock(p: Paths, timeout: float = 10.0, stale_after: float = 120.0):
    """Simple advisory lock via a lock file. Stale locks are reclaimed."""
    deadline = time.time() + timeout
    while True:
        try:
            fd = os.open(str(p.lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("utf-8"))
            os.close(fd)
            break
        except FileExistsError:
            try:
                age = time.time() - p.lock_file.stat().st_mtime
            except FileNotFoundError:
                continue
            if age > stale_after:
                with contextlib.suppress(FileNotFoundError):
                    p.lock_file.unlink()
                continue
            if time.time() > deadline:
                raise LockError(
                    f"Could not acquire {p.lock_file}: locked by another process."
                )
            time.sleep(0.1)
    try:
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            p.lock_file.unlink()


def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
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


def render_frontmatter(fm: Dict[str, Any]) -> str:
    return yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()


def _default_memory_files() -> Dict[str, str]:
    def doc(id_, title, domain, tags, body):
        fm = render_frontmatter(
            {
                "id": id_,
                "title": title,
                "domain": domain,
                "last_updated": _now(),
                "tags": tags,
                "schema_version": SCHEMA_VERSION,
            }
        )
        return f"---\n{fm}\n---\n\n{body}"

    return {
        "system_invariants.md": doc(
            "system_invariants",
            "System Invariants",
            "Core",
            ["invariants", "rules"],
            "## Core Rules\n- Deterministic execution over probabilistic inference.\n",
        ),
        "architecture.md": doc(
            "architecture",
            "System Architecture & Boundaries",
            "Tech",
            ["arch", "design"],
            "## Component Overview\n",
        ),
        "active_tasks.md": doc(
            "active_tasks",
            "Active Tasks",
            "State",
            ["tasks", "roadmap"],
            "## Current Milestone\n",
        ),
        "decisions.md": doc(
            "decisions",
            "Decisions",
            "History",
            ["adr", "history"],
            "## Decision Register\n",
        ),
        "domain_knowledge.md": doc(
            "domain_knowledge",
            "Domain Knowledge",
            "Context",
            ["domain", "reference"],
            "## Business Rules & External Contracts\n",
        ),
    }


def init_engine(root: Optional[Path] = None) -> Paths:
    """Initializes the BigBrain filesystem structure. Idempotent."""
    p = paths(root)
    p.big_brain_dir.mkdir(exist_ok=True, parents=True)
    p.memory_dir.mkdir(exist_ok=True, parents=True)

    if not p.log_file.exists():
        p.log_file.write_text(LOG_HEADER, encoding="utf-8")

    for filename, content in _default_memory_files().items():
        filepath = p.memory_dir / filename
        if not filepath.exists():
            filepath.write_text(content, encoding="utf-8")

    rebuild_index(root=p.root, p=p)
    return p


def _summarize(body: str) -> str:
    for line in body.splitlines():
        clean = line.strip().lstrip("#").strip()
        if clean:
            return clean[:80] + ("..." if len(clean) > 80 else "")
    return "No description"


def rebuild_index(root: Optional[Path] = None, p: Optional[Paths] = None) -> str:
    """Deterministic, non-LLM index generator based on frontmatter and token estimates."""
    p = p or paths(root)
    memory_files = glob.glob(str(p.memory_dir / "*.md"))
    rows = []

    for f_path in sorted(memory_files):
        path_obj = Path(f_path)
        content = path_obj.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)

        file_id = fm.get("id", path_obj.stem)
        domain = fm.get("domain", "General")
        rel_path = f"memory/{path_obj.name}"
        summary = fm.get("description") or _summarize(body)
        token_est = len(content) // 4
        rows.append(f"| `{file_id}` | `{rel_path}` | {domain} | {summary} | {token_est} |")

    index_content = (
        f"# BigBrain System Index\n"
        f"> Last Compiled: {_now()} | Active Files: {len(rows)} | Schema Version: {SCHEMA_VERSION}\n\n"
        f"| File ID | Path | Domain | Summary | Token Est |\n"
        f"| :--- | :--- | :--- | :--- | :--- |\n"
        + "\n".join(rows)
        + ("\n" if rows else "")
    )

    _atomic_write(p.index_file, index_content)
    return index_content


def read_index(root: Optional[Path] = None) -> str:
    p = paths(root)
    if not p.index_file.exists():
        raise FileNotFoundError(
            "INDEX.md not found. Run `bigbrain init` (or `bigbrain install`) first."
        )
    return p.index_file.read_text(encoding="utf-8")


def append_log(
    root: Optional[Path],
    entry_type: str,
    target: str,
    summary: str,
    details: str,
) -> str:
    """Atomically appends an entry to the transaction log."""
    entry_type = entry_type.upper()
    if entry_type not in LOG_TYPES:
        raise ValueError(f"Invalid log type '{entry_type}'. Must be one of {LOG_TYPES}.")

    p = paths(root)
    if not p.log_file.exists():
        init_engine(root)

    entry = (
        f"\n## [{_now()}] - TYPE: {entry_type}\n"
        f"- TARGET: {target}\n"
        f"- SUMMARY: {summary}\n"
        f"### Details\n{details}\n---\n"
    )
    # Locked so two concurrent writers (two agent sessions, an agent + a git
    # hook, etc.) can't interleave partial writes into the same log file.
    with file_lock(p, timeout=5.0):
        with open(p.log_file, "a", encoding="utf-8") as f:
            f.write(entry)
    return entry


def _find_memory_path(p: Paths, file_id: str) -> Optional[Path]:
    for f_path in glob.glob(str(p.memory_dir / "*.md")):
        path_obj = Path(f_path)
        content = path_obj.read_text(encoding="utf-8")
        fm, _ = parse_frontmatter(content)
        if fm.get("id") == file_id or path_obj.stem == file_id:
            return path_obj
    return None


def read_memory(root: Optional[Path], file_id: str) -> str:
    """Retrieves file contents by file_id matching frontmatter or filename."""
    p = paths(root)
    match = _find_memory_path(p, file_id)
    if match is None:
        raise FileNotFoundError(f"Memory file with ID '{file_id}' not found.")
    return match.read_text(encoding="utf-8")


def grep(root: Optional[Path], term: str, include_log: bool = False) -> List[Dict[str, Any]]:
    """Full-text fallback search across memory files (and optionally the log/
    archive) for when the caller doesn't know the right file_id up front.
    """
    p = paths(root)
    pattern = re.compile(re.escape(term), re.IGNORECASE)
    results: List[Dict[str, Any]] = []

    memory_paths = [Path(f) for f in sorted(glob.glob(str(p.memory_dir / "*.md")))]
    extra_paths = [p.log_file, p.archive_file] if include_log else []

    for path_obj in memory_paths + [x for x in extra_paths if x.exists()]:
        if path_obj in memory_paths:
            fm, _ = parse_frontmatter(path_obj.read_text(encoding="utf-8"))
            file_id = fm.get("id", path_obj.stem)
        else:
            file_id = path_obj.stem

        for i, line in enumerate(path_obj.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                results.append(
                    {
                        "file_id": file_id,
                        "path": str(path_obj.relative_to(p.root)),
                        "line": i,
                        "text": line.strip(),
                    }
                )
    return results


_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> List[str]:
    return _WORD_RE.findall(text.lower())


def search(root: Optional[Path], query: str, top_n: int = 8) -> List[Dict[str, Any]]:
    """Deterministic fuzzy/ranked discovery across memory files.

    Not embeddings-based (BigBrain deliberately has no vector DB/opaque
    embeddings — see plan.md's core principles), just word-overlap scoring
    with a phrase bonus. It exists for the case `grep` doesn't cover: you
    know roughly what you're looking for but not the exact wording or which
    file it lives in. Use `grep` instead when you know the exact substring.
    """
    p = paths(root)
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []
    query_lower = query.lower()

    scored = []
    for f_path in sorted(glob.glob(str(p.memory_dir / "*.md"))):
        path_obj = Path(f_path)
        content = path_obj.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)
        file_id = fm.get("id", path_obj.stem)

        doc_tokens = _tokenize(body) + _tokenize(" ".join(fm.get("tags", []) or [])) + _tokenize(fm.get("title", ""))
        if not doc_tokens:
            continue
        doc_lower = body.lower()

        score = sum(doc_tokens.count(t) for t in query_tokens)
        if query_lower in doc_lower:
            score += 5
        if score <= 0:
            continue

        snippet = _summarize(body)
        for line in body.splitlines():
            if any(t in line.lower() for t in query_tokens):
                snippet = line.strip()
                break

        scored.append(
            {
                "file_id": file_id,
                "path": f"memory/{path_obj.name}",
                "score": score,
                "snippet": snippet[:160],
            }
        )

    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:top_n]


def list_memory_ids(root: Optional[Path] = None) -> List[str]:
    p = paths(root)
    ids = []
    for f_path in sorted(glob.glob(str(p.memory_dir / "*.md"))):
        path_obj = Path(f_path)
        fm, _ = parse_frontmatter(path_obj.read_text(encoding="utf-8"))
        ids.append(fm.get("id", path_obj.stem))
    return ids


def parse_log_entries(log_text: str) -> List[Dict[str, str]]:
    entries = []
    for m in _LOG_ENTRY_RE.finditer(log_text):
        entries.append(
            {
                "timestamp": m.group("timestamp"),
                "type": m.group("type"),
                "target": m.group("target").strip(),
                "summary": m.group("summary").strip(),
                "details": m.group("details").strip(),
            }
        )
    return entries


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    return slug or "note"


def _titleize(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.replace("_", " ").split())


def _valid_memory_content(content: str) -> bool:
    """Sanity-checks LLM-produced file content before trusting it."""
    if not content or not content.startswith("---"):
        return False
    fm, body = parse_frontmatter(content)
    return bool(fm.get("id")) and len(body.strip()) > 0


def _build_reconcile_prompt(path_obj: Path, existing_content: str, group: List[Dict[str, str]]) -> str:
    entries_text = "\n\n".join(
        f"[{e['type']}] target={e['target']}\nsummary: {e['summary']}\ndetails: {e['details']}"
        for e in group
    )
    return (
        "Integrate the following transaction log entries into the existing markdown document.\n"
        "Maintain existing Markdown structure and YAML frontmatter.\n"
        "Remove obsolete statements, resolve contradictions in favor of newer log entries,\n"
        f"and update the `last_updated` frontmatter field to {_now()}.\n"
        "Output ONLY the updated file contents. No commentary, no explanation, no surrounding code fences.\n\n"
        f"=== EXISTING FILE ({path_obj.name}) ===\n{existing_content}\n\n"
        f"=== NEW LOG ENTRIES (newest last) ===\n{entries_text}\n"
    )


def _deterministic_merge(content: str, group: List[Dict[str, str]]) -> str:
    fm, body = parse_frontmatter(content)
    fm["last_updated"] = _now()
    fm.setdefault("schema_version", SCHEMA_VERSION)

    section_lines = [f"\n## Log Reconciliation ({_now()})"]
    for e in group:
        section_lines.append(f"- **[{e['type']}]** {e['summary']}")
        if e["details"]:
            section_lines.append(f"  - {e['details']}")
    new_body = body.rstrip() + "\n" + "\n".join(section_lines) + "\n"
    new_fm_text = render_frontmatter(fm)
    return f"---\n{new_fm_text}\n---\n\n{new_body}"


def _rotate_archive_if_needed(p: Paths, max_bytes: int) -> Optional[str]:
    if p.archive_file.exists() and p.archive_file.stat().st_size > max_bytes:
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        rotated = p.big_brain_dir / f"log.archive.{ts}.md"
        os.replace(p.archive_file, rotated)
        return str(rotated.relative_to(p.root))
    return None


def compile_memory(
    root: Optional[Path] = None,
    reason: str = "manual",
    use_llm: bool = False,
    llm_timeout: int = 120,
) -> Dict[str, Any]:
    """Parses log.md, reconciles memory/*.md files, rebuilds INDEX.md.

    Default mode is deterministic (no LLM call, no API key needed): pending
    entries are grouped by target_file_id and appended under a dated
    "Log Reconciliation" section, creating the target memory file if it's new.

    With use_llm=True, each target file is instead handed to a configured LLM
    CLI (see .bigbrain/config.yml / bigbrain.llm) to properly dedupe and
    resolve contradictions per the original BigBrain spec. Any failure or
    malformed output for a given file falls back to the deterministic merge
    for that file only, so `compile` can never lose data or crash.

    Processed entries are moved from log.md to log.archive.md, which is
    rotated to a timestamped file once it exceeds config `archive_max_bytes`
    (default 2MB) so it doesn't grow forever.
    """
    p = paths(root)
    if not p.log_file.exists():
        init_engine(root)

    with file_lock(p):
        log_text = p.log_file.read_text(encoding="utf-8")
        entries = parse_log_entries(log_text)

        result = {
            "reason": reason,
            "mode": "llm" if use_llm else "deterministic",
            "entries_processed": 0,
            "files_updated": [],
            "warnings": [],
            "timestamp": _now(),
        }

        if not entries:
            rebuild_index(p=p)
            return result

        llm_mod = None
        if use_llm:
            from . import llm as llm_mod  # lazy import: avoids a hard circular import at module load

        by_target: Dict[str, List[Dict[str, str]]] = {}
        for e in entries:
            by_target.setdefault(e["target"], []).append(e)

        for target, group in by_target.items():
            file_id = target.split("/")[-1].removesuffix(".md") if "/" in target or target.endswith(".md") else target
            file_id = _slugify(file_id)
            existing_path = _find_memory_path(p, file_id)

            if existing_path is None:
                domain = _TYPE_DOMAIN.get(group[0]["type"], "General")
                fm = render_frontmatter(
                    {
                        "id": file_id,
                        "title": _titleize(file_id),
                        "domain": domain,
                        "last_updated": _now(),
                        "tags": [],
                        "schema_version": SCHEMA_VERSION,
                    }
                )
                body = "## Log Reconciliation\n"
                existing_path = p.memory_dir / f"{file_id}.md"
                content = f"---\n{fm}\n---\n\n{body}"
            else:
                content = existing_path.read_text(encoding="utf-8")

            new_content = None
            if use_llm:
                try:
                    prompt = _build_reconcile_prompt(existing_path, content, group)
                    llm_output = llm_mod.run_llm(p.root, prompt, timeout=llm_timeout)
                    if _valid_memory_content(llm_output):
                        new_content = llm_output
                    else:
                        result["warnings"].append(
                            f"LLM output for '{file_id}' failed validation; used deterministic merge instead."
                        )
                except llm_mod.LLMError as e:
                    result["warnings"].append(
                        f"LLM compile failed for '{file_id}' ({e}); used deterministic merge instead."
                    )

            if new_content is None:
                new_content = _deterministic_merge(content, group)

            _atomic_write(existing_path, new_content)
            result["files_updated"].append(str(existing_path.relative_to(p.root)))

        result["entries_processed"] = len(entries)

        cfg = load_config(p.root)
        max_bytes = int(cfg.get("archive_max_bytes", DEFAULT_ARCHIVE_MAX_BYTES))
        rotated = _rotate_archive_if_needed(p, max_bytes)
        if rotated:
            result["warnings"].append(f"Rotated oversized archive to {rotated}")

        archived = p.archive_file.read_text(encoding="utf-8") if p.archive_file.exists() else "# BigBrain Log Archive\n\n"
        archived += log_text[len(LOG_HEADER):] if log_text.startswith(LOG_HEADER) else log_text
        _atomic_write(p.archive_file, archived)
        _atomic_write(p.log_file, LOG_HEADER)

        rebuild_index(p=p)
        return result


def status(root: Optional[Path] = None) -> Dict[str, Any]:
    p = paths(root)
    initialized = p.index_file.exists()
    pending = 0
    if p.log_file.exists():
        pending = len(parse_log_entries(p.log_file.read_text(encoding="utf-8")))

    lock_info: Optional[Dict[str, Any]] = None
    if p.lock_file.exists():
        try:
            pid_text = p.lock_file.read_text(encoding="utf-8").strip()
            age = time.time() - p.lock_file.stat().st_mtime
            lock_info = {"pid": pid_text, "age_seconds": round(age, 1)}
        except OSError:
            lock_info = {"pid": None, "age_seconds": None}

    return {
        "initialized": initialized,
        "root": str(p.root),
        "memory_files": list_memory_ids(root) if initialized else [],
        "pending_log_entries": pending,
        "locked": lock_info is not None,
        "lock": lock_info,
        "schema_version": SCHEMA_VERSION,
    }


def doctor(root: Optional[Path] = None, fix: bool = False) -> Dict[str, Any]:
    """Validates .bigbrain/ and optionally repairs common issues.

    This is also BigBrain's migration entrypoint: each memory file carries a
    `schema_version`; a file on an older version gets migrated forward here
    (currently a no-op stamp, since SCHEMA_VERSION has only ever been "1.0.0"
    — this is the hook future format changes register against).
    """
    p = paths(root)
    issues: List[str] = []
    fixed: List[str] = []

    if not p.index_file.exists():
        issues.append(".bigbrain/ is not initialized (run `bigbrain init`)")
        return {"issues": issues, "fixed": fixed}

    # Each check below reports to exactly one of `issues` (still broken) or
    # `fixed` (repaired this call) — never both, so a `--fix` run that
    # resolves everything correctly reports zero remaining issues.

    if p.lock_file.exists():
        try:
            age = time.time() - p.lock_file.stat().st_mtime
        except OSError:
            age = 0.0
        if age > 120:
            if fix:
                with contextlib.suppress(FileNotFoundError):
                    p.lock_file.unlink()
                fixed.append(f"Removed stale .lock ({age:.0f}s old)")
            else:
                issues.append(f".bigbrain/.lock is stale ({age:.0f}s old)")

    seen_ids: Dict[str, Path] = {}
    for f_path in sorted(glob.glob(str(p.memory_dir / "*.md"))):
        path_obj = Path(f_path)
        content = path_obj.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)
        rel = str(path_obj.relative_to(p.root))
        touched = False

        if not fm.get("id"):
            if fix:
                fm["id"] = path_obj.stem
                touched = True
                fixed.append(f"Set id='{path_obj.stem}' in {rel}")
            else:
                issues.append(f"{rel}: missing 'id' in frontmatter")

        if not fm.get("domain"):
            if fix:
                fm["domain"] = "General"
                touched = True
                fixed.append(f"Set domain='General' in {rel}")
            else:
                issues.append(f"{rel}: missing 'domain' in frontmatter")

        if not fm.get("last_updated"):
            if fix:
                fm["last_updated"] = _now()
                touched = True
                fixed.append(f"Set last_updated in {rel}")
            else:
                issues.append(f"{rel}: missing 'last_updated' in frontmatter")

        if fm.get("schema_version") != SCHEMA_VERSION:
            if fix:
                fm["schema_version"] = SCHEMA_VERSION
                touched = True
                fixed.append(f"Migrated {rel} to schema_version {SCHEMA_VERSION}")
            else:
                issues.append(f"{rel}: schema_version is {fm.get('schema_version')!r}, expected {SCHEMA_VERSION!r}")

        file_id = fm.get("id", path_obj.stem)
        if file_id in seen_ids:
            other = seen_ids[file_id]
            if fix:
                new_id = f"{file_id}__{path_obj.stem}"
                fm["id"] = new_id
                touched = True
                fixed.append(f"Renamed duplicate id in {rel} to '{new_id}'")
            else:
                issues.append(f"Duplicate id '{file_id}' in {rel} and {other}")
        else:
            seen_ids[file_id] = rel

        if touched:
            new_fm_text = render_frontmatter(fm)
            _atomic_write(path_obj, f"---\n{new_fm_text}\n---\n\n{body}\n")

    if p.log_file.exists():
        log_text = p.log_file.read_text(encoding="utf-8")
        stripped = _LOG_ENTRY_RE.sub("", log_text)
        leftover = stripped[len(LOG_HEADER):] if stripped.startswith(LOG_HEADER) else stripped
        if leftover.strip():
            # Never auto-fixed at any `fix` value: we can't safely guess what a
            # hand-edited/corrupted log entry meant, so this always surfaces.
            issues.append(
                "log.md contains content that doesn't match the expected entry format "
                "(likely hand-edited) — not auto-fixed, please review manually"
            )

    cfg_path = p.big_brain_dir / "config.yml"
    if cfg_path.exists():
        try:
            yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            if fix:
                backup = cfg_path.with_suffix(".yml.bak")
                os.replace(cfg_path, backup)
                fixed.append(f"Moved invalid config.yml to {backup.name} (defaults will apply)")
            else:
                issues.append(".bigbrain/config.yml is not valid YAML")

    def _index_body(content: str) -> str:
        return "\n".join(line for line in content.splitlines() if not line.startswith("> Last Compiled"))

    current_index = p.index_file.read_text(encoding="utf-8")
    if fix:
        rebuilt = rebuild_index(p=p)
        if _index_body(rebuilt) != _index_body(current_index):
            fixed.append("Rebuilt INDEX.md (contents had drifted from memory/*.md)")
    else:
        actual_count = len(glob.glob(str(p.memory_dir / "*.md")))
        if f"Active Files: {actual_count}" not in current_index:
            issues.append("INDEX.md looks stale relative to memory/*.md (run `bigbrain compile` or `--fix`)")

    return {"issues": issues, "fixed": fixed}
