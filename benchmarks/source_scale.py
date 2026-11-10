"""Synthetic scale smoke check; timings are reported, not flaky test thresholds."""
import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bigbrain import source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=int, default=3000)
    args = parser.parse_args()
    if not 2 <= args.files <= 20000:
        parser.error("--files must be between 2 and 20000")
    with tempfile.TemporaryDirectory(prefix="bigbrain scale ") as directory:
        root = Path(directory)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        for n in range(args.files):
            (root / f"module_{n:05}.py").write_text(
                f"def function_{n}():\n" + "    # source indexing fixture with repeated documentation and identifiers\n" * 79,
                encoding="utf-8")
        timings, reports = {}, {}
        for name in ("cold", "warm", "edit_delete"):
            if name == "edit_delete":
                (root / "module_00000.py").write_text("replacementneedle", encoding="utf-8")
                (root / "module_00001.py").unlink()
            start = time.perf_counter()
            reports[name] = source.refresh(root)
            timings[name] = round(time.perf_counter() - start, 3)
        assert reports["cold"]["updated"] == args.files
        assert reports["warm"]["updated"] == 0
        assert reports["edit_delete"]["updated"] == 1
        assert reports["edit_delete"]["removed"] == 1
        assert source.search(root, "replacementneedle")["results"][0]["path"] == "module_00000.py"
        print(json.dumps({"scope": "synthetic 80-line Python files; not a real-repository or agent benchmark",
                          "os": platform.system(), "python": platform.python_version(), "files": args.files,
                          "seconds": timings, "cache_bytes": (root / ".bigbrain/cache/source.sqlite3").stat().st_size,
                          "updated": {name: report["updated"] for name, report in reports.items()}}, indent=2))


if __name__ == "__main__":
    main()
