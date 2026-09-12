"""Wires BigBrain into a target repo so any AI coding tool picks it up.

Strategy (works regardless of which AI/CLI the user runs):

1. Scaffold `.bigbrain/` (via core.init_engine) and drop `.bigbrain/tools.json`
   with the raw tool schemas, for hosts that do custom function-calling.
2. Append a marked "BigBrain" instruction block to every well-known
   agent-instructions file (AGENTS.md, CLAUDE.md, GEMINI.md, .windsurfrules,
   .github/copilot-instructions.md). These files are read natively by most
   coding agents; the block tells the agent to drive BigBrain through the
   `bigbrain` shell command, which needs no protocol support at all.
3. Register the BigBrain MCP server in the two most common project-level MCP
   config locations (.mcp.json for Claude Code, .cursor/mcp.json for Cursor)
   for hosts that support native MCP tool-calling, and add a Cursor rule file.
4. Wire auto-compile hooks so the log gets reconciled without anyone having to
   remember: a git pre-commit hook (any host), plus SessionStart / SessionEnd
   / PreCompact hooks in .claude/settings.json for Claude Code specifically
   (SessionStart also auto-injects INDEX.md into context).
5. Drop a `.bigbrain/config.yml` with commented defaults (LLM CLI override
   for `--llm` compiles, archive rotation size).

Steps 2-4 are idempotent: re-running `bigbrain install` won't duplicate
blocks. Pass force=True to overwrite an existing BigBrain block (e.g. after
upgrading BigBrain itself).
"""
from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from . import core, schemas

BEGIN = "<!-- BEGIN BIGBRAIN -->"
END = "<!-- END BIGBRAIN -->"
SH_BEGIN = "# BEGIN BIGBRAIN"
SH_END = "# END BIGBRAIN"

INSTRUCTION_FILES = [
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".windsurfrules",
    ".github/copilot-instructions.md",
]

CURSOR_RULE = """---
description: BigBrain filesystem memory system
alwaysApply: true
---

{block}
"""

CONFIG_TEMPLATE = """# BigBrain configuration.
#
# Uncomment to pin the LLM CLI used by `bigbrain compile --llm` for
# dedup/contradiction-resolution. Accepts a plain shell command; the
# reconciliation prompt is piped to it on stdin and the full updated file
# content is expected back on stdout. Auto-detected otherwise (tries `claude
# -p`, then `llm`).
# llm_command: "claude -p"

# log.archive.md is rotated to a timestamped file once it exceeds this many
# bytes, so the archive doesn't grow forever.
archive_max_bytes: {archive_max_bytes}
"""

GIT_PRE_COMMIT_HOOK = f"""#!/bin/sh
{SH_BEGIN}
command -v bigbrain >/dev/null 2>&1 && bigbrain compile --reason "pre-commit" >/dev/null 2>&1 || true
{SH_END}
"""

CLAUDE_HOOK_COMMANDS = {
    "SessionStart": 'bigbrain index 2>/dev/null || true',
    "SessionEnd": 'bigbrain compile --reason "session end" >/dev/null 2>&1 || true',
    "PreCompact": 'bigbrain compile --reason "pre-compact" >/dev/null 2>&1 || true',
}


@dataclass
class InstallReport:
    lines: List[str] = field(default_factory=list)

    def add(self, line: str) -> None:
        self.lines.append(line)


def _upsert_block(path: Path, block: str, force: bool, report: InstallReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(block + "\n", encoding="utf-8")
        report.add(f"[+] Created {path} with BigBrain wiring")
        return

    content = path.read_text(encoding="utf-8")
    if BEGIN in content and END in content:
        if not force:
            report.add(f"[=] {path} already wired (use --force to refresh)")
            return
        pre, rest = content.split(BEGIN, 1)
        _, post = rest.split(END, 1)
        new_content = pre + block + post
        path.write_text(new_content, encoding="utf-8")
        report.add(f"[~] Refreshed BigBrain block in {path}")
        return

    sep = "" if content.endswith("\n\n") else ("\n\n" if content.endswith("\n") else "\n\n")
    path.write_text(content + sep + block + "\n", encoding="utf-8")
    report.add(f"[+] Appended BigBrain wiring to {path}")


def _upsert_mcp_json(path: Path, force: bool, report: InstallReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            report.add(f"[!] {path} is not valid JSON; skipping MCP registration there")
            return

    servers = data.setdefault("mcpServers", {})
    if "bigbrain" in servers and not force:
        report.add(f"[=] {path} already has a bigbrain MCP entry")
        return

    servers["bigbrain"] = {
        "command": "bigbrain",
        "args": ["serve-mcp", "--path", "."],
    }
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    report.add(f"[+] Registered bigbrain MCP server in {path}")


def _write_config(root: Path, force: bool, report: InstallReport) -> None:
    path = root / ".bigbrain" / "config.yml"
    if path.exists() and not force:
        report.add(f"[=] {path} already exists")
        return
    path.write_text(
        CONFIG_TEMPLATE.format(archive_max_bytes=core.DEFAULT_ARCHIVE_MAX_BYTES), encoding="utf-8"
    )
    report.add(f"[+] Wrote {path}")


def _wire_git_pre_commit(root: Path, force: bool, report: InstallReport) -> None:
    git_dir = root / ".git"
    if not git_dir.is_dir():
        report.add("[=] Not a git repo (no .git/); skipping pre-commit hook")
        return

    hook_path = git_dir / "hooks" / "pre-commit"
    hook_path.parent.mkdir(parents=True, exist_ok=True)

    if not hook_path.exists():
        hook_path.write_text(GIT_PRE_COMMIT_HOOK, encoding="utf-8")
        report.add(f"[+] Created {hook_path}")
    else:
        content = hook_path.read_text(encoding="utf-8")
        if SH_BEGIN in content:
            if not force:
                report.add(f"[=] {hook_path} already wired (use --force to refresh)")
                return
            pre, rest = content.split(SH_BEGIN, 1)
            _, post = rest.split(SH_END, 1)
            body = (
                f'command -v bigbrain >/dev/null 2>&1 && bigbrain compile --reason "pre-commit" '
                f">/dev/null 2>&1 || true"
            )
            content = f"{pre}{SH_BEGIN}\n{body}\n{SH_END}{post}"
            hook_path.write_text(content, encoding="utf-8")
            report.add(f"[~] Refreshed BigBrain block in {hook_path}")
        else:
            body = (
                f'\n{SH_BEGIN}\ncommand -v bigbrain >/dev/null 2>&1 && '
                f'bigbrain compile --reason "pre-commit" >/dev/null 2>&1 || true\n{SH_END}\n'
            )
            hook_path.write_text(content.rstrip("\n") + "\n" + body, encoding="utf-8")
            report.add(f"[+] Appended BigBrain wiring to existing {hook_path}")

    try:
        mode = hook_path.stat().st_mode
        hook_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass  # best-effort; harmless on filesystems without exec bits (e.g. some Windows setups)


def _wire_claude_hooks(root: Path, force: bool, report: InstallReport) -> None:
    path = root / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            report.add(f"[!] {path} is not valid JSON; skipping Claude Code hook wiring")
            return

    hooks = data.setdefault("hooks", {})
    changed = False
    for event, command in CLAUDE_HOOK_COMMANDS.items():
        entries = hooks.setdefault(event, [])
        already = any(
            h.get("command") == command
            for block in entries
            for h in block.get("hooks", [])
        )
        if already and not force:
            continue
        if already and force:
            continue  # command text is stable; nothing to refresh
        entries.append({"hooks": [{"type": "command", "command": command}]})
        changed = True

    if changed:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        report.add(f"[+] Wired SessionStart/SessionEnd/PreCompact hooks in {path}")
    else:
        report.add(f"[=] {path} already has BigBrain hooks")


def install(root: Path, force: bool = False) -> InstallReport:
    report = InstallReport()
    root = Path(root)

    p = core.init_engine(root)
    report.add(f"[+] Initialized {p.big_brain_dir}")

    tools_path = p.big_brain_dir / "tools.json"
    tools_path.write_text(json.dumps(schemas.TOOLS, indent=2) + "\n", encoding="utf-8")
    report.add(f"[+] Wrote tool schema to {tools_path}")

    block = schemas.shell_wiring_block()
    for rel in INSTRUCTION_FILES:
        _upsert_block(root / rel, block, force, report)

    cursor_rule_path = root / ".cursor" / "rules" / "bigbrain.mdc"
    cursor_rule_path.parent.mkdir(parents=True, exist_ok=True)
    if not cursor_rule_path.exists() or force:
        cursor_rule_path.write_text(CURSOR_RULE.format(block=block), encoding="utf-8")
        report.add(f"[+] Wrote Cursor rule {cursor_rule_path}")
    else:
        report.add(f"[=] {cursor_rule_path} already exists")

    _upsert_mcp_json(root / ".mcp.json", force, report)
    _upsert_mcp_json(root / ".cursor" / "mcp.json", force, report)

    _write_config(root, force, report)
    _wire_git_pre_commit(root, force, report)
    _wire_claude_hooks(root, force, report)

    report.add("")
    report.add("BigBrain is installed. Any AI agent that can run shell commands can now use it via")
    report.add("`bigbrain index`, `bigbrain read <id>`, `bigbrain log ...`, `bigbrain compile`.")
    report.add("Agents with native MCP support will additionally see it as a proper tool.")
    report.add("Auto-compile is wired: git pre-commit (if this is a git repo) and, for Claude Code,")
    report.add("SessionStart/SessionEnd/PreCompact hooks in .claude/settings.json.")
    return report
