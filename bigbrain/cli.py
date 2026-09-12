"""BigBrain command-line interface.

    bigbrain init                Scaffold .bigbrain/ in the current directory
    bigbrain install             Scaffold + wire into whatever AI tooling is present
    bigbrain index               Print INDEX.md
    bigbrain read <file_id>      Print a memory file
    bigbrain log ...             Append a transaction log entry
    bigbrain compile             Reconcile log.md into memory/*.md and rebuild INDEX.md
    bigbrain status              Print engine state as JSON
    bigbrain serve-mcp           Run the MCP stdio server (for hosts with native tool-calling)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import core


def _cmd_init(args: argparse.Namespace) -> int:
    p = core.init_engine(Path(args.path))
    print(f"[BigBrain] Initialized at {p.big_brain_dir}")
    return 0


def _cmd_install(args: argparse.Namespace) -> int:
    from . import install as install_mod

    report = install_mod.install(Path(args.path), force=args.force)
    for line in report.lines:
        print(line)
    return 0


def _cmd_index(args: argparse.Namespace) -> int:
    print(core.read_index(Path(args.path)), end="")
    return 0


def _cmd_read(args: argparse.Namespace) -> int:
    try:
        print(core.read_memory(Path(args.path), args.file_id), end="")
    except FileNotFoundError as e:
        print(f"[BigBrain] Error: {e}", file=sys.stderr)
        return 1
    return 0


def _cmd_log(args: argparse.Namespace) -> int:
    try:
        core.append_log(Path(args.path), args.type, args.target, args.summary, args.details)
    except ValueError as e:
        print(f"[BigBrain] Error: {e}", file=sys.stderr)
        return 1
    print(f"[BigBrain] Logged {args.type.upper()} targeting '{args.target}'")
    return 0


def _cmd_compile(args: argparse.Namespace) -> int:
    try:
        result = core.compile_memory(
            Path(args.path), reason=args.reason, use_llm=args.llm, llm_timeout=args.llm_timeout
        )
    except core.LockError as e:
        print(f"[BigBrain] Error: {e}", file=sys.stderr)
        return 1
    print(
        f"[BigBrain] Compiled ({result['reason']}, mode={result['mode']}): "
        f"{result['entries_processed']} entries -> {len(result['files_updated'])} file(s) updated."
    )
    for w in result.get("warnings", []):
        print(f"  ! {w}")
    for f in result["files_updated"]:
        print(f"  - {f}")
    return 0


def _cmd_grep(args: argparse.Namespace) -> int:
    hits = core.grep(Path(args.path), args.term, include_log=args.include_log)
    if not hits:
        print("[BigBrain] No matches.")
        return 0
    for h in hits:
        print(f"{h['file_id']} ({h['path']}:{h['line']}): {h['text']}")
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    hits = core.search(Path(args.path), args.query, top_n=args.top)
    if not hits:
        print("[BigBrain] No relevant memory files found.")
        return 0
    for h in hits:
        print(f"{h['file_id']} (score={h['score']}, {h['path']}): {h['snippet']}")
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    result = core.doctor(Path(args.path), fix=args.fix)
    if result["fixed"]:
        print("[BigBrain] Fixed:")
        for f in result["fixed"]:
            print(f"  - {f}")
    if result["issues"]:
        print("[BigBrain] Issues:")
        for i in result["issues"]:
            print(f"  ! {i}")
    if not result["issues"] and not result["fixed"]:
        print("[BigBrain] No issues found.")
    return 1 if result["issues"] else 0


def _cmd_status(args: argparse.Namespace) -> int:
    print(json.dumps(core.status(Path(args.path)), indent=2))
    return 0


def _cmd_rebuild_index(args: argparse.Namespace) -> int:
    core.rebuild_index(Path(args.path))
    return 0


def _cmd_serve_mcp(args: argparse.Namespace) -> int:
    from . import mcp_server

    mcp_server.serve(Path(args.path))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bigbrain", description="Deterministic filesystem-first memory engine.")
    parser.add_argument("--path", default=".", help="Project root (default: current directory)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Scaffold .bigbrain/ in the current directory").set_defaults(func=_cmd_init)

    p_install = sub.add_parser("install", help="Scaffold + wire BigBrain into whatever AI tooling is present")
    p_install.add_argument("--force", action="store_true", help="Re-write wiring blocks even if already present")
    p_install.set_defaults(func=_cmd_install)

    sub.add_parser("index", help="Print INDEX.md").set_defaults(func=_cmd_index)

    p_read = sub.add_parser("read", help="Print a memory file by file_id")
    p_read.add_argument("file_id")
    p_read.set_defaults(func=_cmd_read)

    p_log = sub.add_parser("log", help="Append a transaction log entry")
    p_log.add_argument("--type", required=True, choices=core.LOG_TYPES)
    p_log.add_argument("--target", required=True, help="Target memory file_id")
    p_log.add_argument("--summary", required=True)
    p_log.add_argument("--details", required=True)
    p_log.set_defaults(func=_cmd_log)

    p_compile = sub.add_parser("compile", help="Reconcile log.md into memory/*.md and rebuild INDEX.md")
    p_compile.add_argument("--reason", default="manual", help="Why compilation was triggered")
    p_compile.add_argument(
        "--llm",
        action="store_true",
        help="Use a configured LLM CLI to dedupe/resolve contradictions per file "
        "(see .bigbrain/config.yml); falls back to deterministic merge per-file on failure",
    )
    p_compile.add_argument("--llm-timeout", type=int, default=120, help="Seconds before an --llm call is abandoned")
    p_compile.set_defaults(func=_cmd_compile)

    p_grep = sub.add_parser("grep", help="Exact-substring search across memory files (fallback when file_id is unknown)")
    p_grep.add_argument("term")
    p_grep.add_argument("--include-log", action="store_true", help="Also search log.md and log.archive.md")
    p_grep.set_defaults(func=_cmd_grep)

    p_search = sub.add_parser(
        "search", help="Ranked fuzzy/word-overlap search across memory files (use when exact wording is unknown)"
    )
    p_search.add_argument("query")
    p_search.add_argument("--top", type=int, default=8, help="Max results to return")
    p_search.set_defaults(func=_cmd_search)

    sub.add_parser("status", help="Print engine state as JSON").set_defaults(func=_cmd_status)
    sub.add_parser("rebuild-index", help="Rebuild INDEX.md from memory/*.md").set_defaults(func=_cmd_rebuild_index)

    p_doctor = sub.add_parser("doctor", help="Validate .bigbrain/ and optionally repair common issues")
    p_doctor.add_argument("--fix", action="store_true", help="Apply auto-fixes instead of just reporting")
    p_doctor.set_defaults(func=_cmd_doctor)

    sub.add_parser("serve-mcp", help="Run the MCP stdio server").set_defaults(func=_cmd_serve_mcp)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
