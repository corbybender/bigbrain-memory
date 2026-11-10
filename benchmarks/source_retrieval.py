"""Repeatable repository retrieval smoke benchmark, not an agent-success claim.

Copies the current package into a temporary Git repo, leaving real caches alone.
Run: python benchmarks/source_retrieval.py
"""
import json
import platform
from pathlib import Path
import shutil
import statistics
import sqlite3
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bigbrain import source

CASES = [
    ("file lock stale timeout", "bigbrain/core.py"),
    ("MCP initialize protocolVersion", "bigbrain/mcp_server.py"),
    ("source search max lines parser", "bigbrain/cli.py"),
    ("git pre commit hooks install", "bigbrain/install.py"),
    ("source snapshot content hash sqlite", "bigbrain/source.py"),
    ("LLM command timeout prompt", "bigbrain/llm.py"),
]


def main():
    with tempfile.TemporaryDirectory(prefix="bigbrain benchmark ") as directory:
        root = Path(directory)
        shutil.copytree(Path(__file__).resolve().parents[1] / "bigbrain", root / "bigbrain",
                        ignore=shutil.ignore_patterns("__pycache__"))
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        start = time.perf_counter()
        cold = source.refresh(root)
        cold_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        warm = source.refresh(root)
        warm_ms = (time.perf_counter() - start) * 1000
        cases = []
        for query, expected in CASES:
            start = time.perf_counter()
            result = source.search(root, query, 5)
            paths = [hit["path"] for hit in result["results"]]
            cases.append({"query": query, "expected": expected, "top_paths": paths,
                          "found": expected in paths, "ms": round((time.perf_counter() - start) * 1000, 2),
                          "response_bytes": len(json.dumps(result).encode())})
        report = {"scope": "six keyword questions over BigBrain package source; no agent or semantic-search evaluation",
                  "environment": {"os": platform.system(), "python": platform.python_version(),
                                  "sqlite": sqlite3.sqlite_version},
                  "indexed_files": cold["indexed_files"], "cold_index_ms": round(cold_ms, 2),
                  "unchanged_refresh_ms": round(warm_ms, 2), "unchanged_reparsed_files": warm["updated"],
                  "recall_at_5": sum(case["found"] for case in cases) / len(cases),
                  "median_query_ms": statistics.median(case["ms"] for case in cases),
                  "cache_bytes": (root / ".bigbrain/cache/source.sqlite3").stat().st_size, "cases": cases}
        print(json.dumps(report, indent=2))
        return 0 if all(case["found"] for case in cases) else 1


if __name__ == "__main__":
    sys.exit(main())
