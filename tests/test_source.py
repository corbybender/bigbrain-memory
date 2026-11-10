"""Source retrieval contracts, CLI and actual stdio MCP integration."""
import concurrent.futures
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bigbrain import core, source, install


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bigbrain source ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                              capture_output=True).stdout

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def cli(self, *args, input=None):
        return subprocess.run([sys.executable, "-m", "bigbrain.cli", *args], input=input,
                              text=True, capture_output=True, timeout=30)

    def test_incremental_edits_same_size_and_timestamp(self):
        path = self.put("app.py", "alpha old\n")
        first = source.refresh(self.root)
        stamp = path.stat()
        self.assertEqual(first["updated"], 1)
        self.assertEqual(source.refresh(self.root)["updated"], 0)
        path.write_text("bravo new\n", encoding="utf-8")
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        found = source.search(self.root, "bravo")
        self.assertEqual(found["status"]["updated"], 1)
        self.assertEqual(found["results"][0]["path"], "app.py")
        self.assertEqual(source.search(self.root, "alpha")["results"], [])

    def test_deletions_renames_and_untracked(self):
        path = self.put("old.py", "uniquecontent")
        source.refresh(self.root)
        path.rename(self.root / "new.py")
        result = source.search(self.root, "uniquecontent")
        self.assertEqual(result["status"]["removed"], 1)
        self.assertEqual([r["path"] for r in result["results"]], ["new.py"])
        (self.root / "new.py").unlink()
        self.assertEqual(source.search(self.root, "uniquecontent")["results"], [])

    def test_gitignore_nested_negation_and_tracked_exclusion(self):
        self.put("tracked.py", "secretword")
        self.git("add", "tracked.py")
        self.put(".gitignore", "tracked.py\nignored/\n*.tmp\n!keep.tmp\n")
        self.put("ignored/private.py", "secretword")
        self.put("drop.tmp", "secretword")
        self.put("keep.tmp", "allowedword")
        self.put("nested/.gitignore", "local.py\n")
        self.put("nested/local.py", "secretword")
        self.assertEqual(source.search(self.root, "secretword")["results"], [])
        self.assertEqual(source.search(self.root, "allowedword")["results"][0]["path"], "keep.tmp")

    def test_changed_ignore_and_config_purge_existing_chunks(self):
        self.put("app.py", "findme")
        source.refresh(self.root)
        self.put(".gitignore", "app.py\n")
        with self.assertRaises(source.SourceError):
            source.read(self.root, "app.py")
        self.put(".gitignore", "")
        self.put(".bigbrain/config.yml", "source:\n  exclude: ['*.py']\n")
        self.assertEqual(source.search(self.root, "findme")["results"], [])

    def test_private_binary_large_nonutf8_and_generated(self):
        for name in [".env", ".env.production", "private.key", ".npmrc", "node_modules/a.js", "generated/a.html"]:
            self.put(name, "confidentialneedle")
        (self.root / "binary.dat").write_bytes(b"confidentialneedle\0")
        (self.root / "legacy.txt").write_bytes(b"\xffconfidentialneedle")
        self.put("big.txt", "confidentialneedle" * 40000)
        self.assertEqual(source.search(self.root, "confidentialneedle")["results"], [])
        self.put(".bigbrain/config.yml", "source:\n  exclude: []\n")
        self.assertEqual(source.search(self.root, "confidentialneedle")["results"][0]["path"], "generated/a.html")

    def test_symlink_and_escape(self):
        self.put("ok.py", "hello")
        for path in ["../outside.py", "/outside.py", "C:\\outside.py", "..\\outside.py"]:
            with self.assertRaises(source.SourceError):
                source.read(self.root, path)
        try:
            (self.root / "link.py").symlink_to(self.root / "ok.py")
        except OSError:
            self.skipTest("Symlink privilege unavailable")
        with self.assertRaises(source.SourceError):
            source.read(self.root, "link.py")

    def test_bounded_read_hash_and_unicode_paths(self):
        content = "\n".join(f"line {n}" for n in range(1, 301))
        self.put("nested/naïve file.py", content)
        result = source.read(self.root, "nested\\naïve file.py", 40, 2)
        self.assertEqual(result["text"], "line 40\nline 41")
        self.assertEqual(result["end_line"], 41)
        self.assertEqual(result["content_hash"], hashlib.sha256((self.root / "nested/naïve file.py").read_bytes()).hexdigest())
        self.assertTrue(result["truncated"])
        self.put("huge-line.txt", "z" * 20000)
        self.assertEqual(len(source.read(self.root, "huge-line.txt")["text"]), 16000)

    def test_keyword_ranking_and_identifier_splitting(self):
        self.put("deploy.py", "def deployStaticSite():\n    deploy_token = 'example'\n")
        self.put("other.py", "unrelated arithmetic")
        hits = source.search(self.root, "deploy static site")["results"]
        self.assertEqual(hits[0]["path"], "deploy.py")
        self.assertIn("deployStaticSite", hits[0]["excerpt"])
        self.assertEqual(source.search(self.root, "zzznonexistent")["results"], [])
        # Search syntax is treated as words, never passed through as FTS operators.
        source.search(self.root, 'deploy OR " NEAR * - site')

    def test_invalid_inputs_and_config(self):
        for n in [0, -1, 51, True, "8"]:
            with self.assertRaises(source.SourceError):
                source.search(self.root, "query", n)
        for query in ["", " " , "a" * 2001, None]:
            with self.assertRaises(source.SourceError):
                source.search(self.root, query)
        for text in ["source: [oops]", "source:\n  max_file_bytes: -1", "source:\n  exclude: wrong", "broken: ["]:
            self.put(".bigbrain/config.yml", text)
            with self.assertRaises(source.SourceError):
                source.refresh(self.root)

    def test_cache_corruption_rebuild_preserves_memory(self):
        core.init_engine(self.root)
        before = core.read_memory(self.root, "architecture")
        self.put("app.py", "recoveryneedle")
        source.refresh(self.root)
        (self.root / ".bigbrain/cache/source.sqlite3").write_bytes(b"corrupt cache")
        with self.assertRaises(source.SourceError):
            source.search(self.root, "recoveryneedle")
        source.refresh(self.root, rebuild=True)
        self.assertTrue(source.search(self.root, "recoveryneedle")["results"])
        self.assertEqual(core.read_memory(self.root, "architecture"), before)

    def test_failed_refresh_rolls_back(self):
        self.put("app.py", "oldcontent")
        source.refresh(self.root)
        self.put("app.py", "newcontent")
        with mock.patch.object(source, "_tokens", side_effect=RuntimeError("interrupted")):
            with self.assertRaises(RuntimeError):
                source.refresh(self.root)
        with closing(sqlite3.connect(str(self.root / ".bigbrain/cache/source.sqlite3"))) as conn:
            self.assertEqual(conn.execute("SELECT text FROM files WHERE path='app.py'").fetchone()[0], "oldcontent")
        self.assertTrue(source.search(self.root, "newcontent")["results"])

    def test_concurrent_refresh(self):
        self.put("app.py", "concurrentneedle")
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: source.search(self.root, "concurrentneedle"), range(8)))
        self.assertTrue(all(r["results"][0]["path"] == "app.py" for r in results))
        self.assertFalse((self.root / ".bigbrain/cache/source.lock").exists())

    def test_branch_switch(self):
        self.put("app.py", "branchone")
        self.git("add", "app.py")
        self.git("commit", "-qm", "one")
        self.git("checkout", "-qb", "two")
        self.put("app.py", "branchtwo")
        self.git("commit", "-qam", "two")
        source.refresh(self.root)
        self.git("checkout", "-q", "-")
        self.assertTrue(source.search(self.root, "branchone")["results"])
        self.assertFalse(source.search(self.root, "branchtwo")["results"])

    def test_cache_is_ignored_and_does_not_scaffold_memory(self):
        self.put("app.py", "hello")
        source.refresh(self.root)
        self.assertNotIn(b"source.sqlite3", self.git("ls-files", "--others", "--exclude-standard"))
        self.assertFalse((self.root / ".bigbrain/memory").exists())

    def test_git_failure_is_explicit(self):
        with mock.patch.object(source.subprocess, "run", side_effect=FileNotFoundError()):
            with self.assertRaises(source.SourceError):
                source.refresh(self.root)

    def test_lock_retries_transient_windows_permission_error(self):
        p = core.init_engine(self.root)
        original = core.os.open
        calls = []
        def transient(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise PermissionError("pending Windows deletion")
            return original(*args, **kwargs)
        with mock.patch.object(core.os, "open", transient):
            with core.file_lock(p, timeout=1):
                self.assertTrue(p.lock_file.exists())
        self.assertEqual(len(calls), 2)
        self.assertFalse(p.lock_file.exists())
        with mock.patch.object(core.os, "open", side_effect=PermissionError("denied")):
            with self.assertRaises(core.LockError):
                with core.file_lock(p, timeout=0.01):
                    self.fail("must not acquire a denied lock")

    def test_link_boundary_without_os_privileges(self):
        self.put("nested/app.py", "linkedneedle")
        original = source._is_link
        with mock.patch.object(source, "_is_link", side_effect=lambda p: p.name == "nested" or original(p)):
            self.assertEqual(source.search(self.root, "linkedneedle")["results"], [])
            with self.assertRaises(source.SourceError):
                source.read(self.root, "nested/app.py")
        with mock.patch.object(source, "_is_link", return_value=True):
            with self.assertRaises(source.SourceError):
                source.refresh(self.root)

    def test_unreadable_file_reports_incomplete_coverage(self):
        self.put("app.py", "hiddenneedle")
        source.refresh(self.root)
        original = Path.open
        def fail_app(path, *args, **kwargs):
            if path.name == "app.py":
                raise PermissionError("test permission denied")
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, "open", fail_app):
            result = source.search(self.root, "hiddenneedle")
        self.assertFalse(result["status"]["complete"])
        self.assertEqual(result["status"]["errors"][0]["path"], "app.py")
        self.assertFalse(result["results"])

    def test_empty_non_git_and_nested_project_roots(self):
        self.assertEqual(source.refresh(self.root)["indexed_files"], 0)
        self.put("nested/app.py", "nestedneedle")
        self.put("outside.py", "outsideneedle")
        result = source.search(self.root / "nested", "nestedneedle")
        self.assertEqual(result["results"][0]["path"], "app.py")
        self.assertFalse(source.search(self.root / "nested", "outsideneedle")["results"])
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(source.SourceError):
                source.refresh(Path(empty))

    def test_distinct_results_snippets_and_status(self):
        self.put("long.py", "\n".join(["deployneedle" for _ in range(200)]))
        self.put("short.py", "\n".join(["unrelated"] * 30 + ["deployneedle"]))
        result = source.search(self.root, "deployneedle", 2)
        self.assertEqual({r["path"] for r in result["results"]}, {"short.py", "long.py"})
        self.assertTrue(all("deployneedle" in r["excerpt"] for r in result["results"]))
        self.assertTrue(source.status(self.root)["complete"])

    def test_inventory_pagination_and_exclusions(self):
        self.put("src/a.py", "alpha")
        self.put("src/b.py", "bravo")
        self.put(".env", "secret")
        page = source.list_files(self.root, "src/", 1)
        self.assertEqual(page["total"], 2)
        self.assertTrue(page["has_more"])
        self.assertEqual(page["files"][0]["path"], "src/a.py")
        self.assertEqual(page["files"][0]["bytes"], 5)
        self.assertEqual(page["files"][0]["extension"], ".py")
        self.assertEqual(source.list_files(self.root, "src/", 1, 1)["files"][0]["path"], "src/b.py")
        self.assertFalse(source.list_files(self.root, ".env")["files"])
        for prefix, limit, offset in [("../", 1, 0), ("", 201, 0), ("", 1, -1), (None, 1, 0)]:
            with self.assertRaises(source.SourceError):
                source.list_files(self.root, prefix, limit, offset)

    def test_empty_and_blank_files_are_searchable_by_name(self):
        self.put("emptyfile.py", "")
        self.put("blankfile.py", "\n")
        self.assertEqual(source.search(self.root, "emptyfile")["results"][0]["path"], "emptyfile.py")
        self.assertEqual(source.search(self.root, "blankfile")["results"][0]["excerpt"], "")

    def test_force_install_preserves_project_settings(self):
        self.put(".bigbrain/config.yml", "source:\n  exclude: ['private']\nllm_command: custom-cli\n")
        before = (self.root / ".bigbrain/config.yml").read_bytes()
        install.install(self.root, force=True)
        self.assertEqual((self.root / ".bigbrain/config.yml").read_bytes(), before)

    def test_cli_source_commands(self):
        self.put("app.py", "clineedle")
        for args in [("source-status",), ("source-files", "--limit", "1"),
                     ("source-read", "app.py", "--max-lines", "1"), ("source-refresh", "--rebuild")]:
            proc = self.cli("--path", str(self.root), *args)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIsInstance(json.loads(proc.stdout), dict)

    def test_cli_path_positions_and_errors(self):
        self.put("app.py", "clineedle")
        for args in [("--path", str(self.root), "source-search", "clineedle"),
                     ("source-search", "clineedle", "--path", str(self.root))]:
            proc = self.cli(*args)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["results"][0]["path"], "app.py")
        proc = self.cli("source-read", "../outside", "--path", str(self.root))
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn("Traceback", proc.stderr)

    def test_installed_mcp_launch_and_tools_over_stdio(self):
        self.put("app.py", "mcpneedle")
        install.install(self.root)
        for file in [self.root / ".mcp.json", self.root / ".cursor/mcp.json"]:
            args = json.loads(file.read_text())["mcpServers"]["bigbrain"]["args"]
            messages = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search_source", "arguments": {"query": "mcpneedle"}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "read_source", "arguments": {"path": ".env"}}},
                {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "list_source_files", "arguments": {"prefix": "app"}}},
                {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "read_source", "arguments": {"path": "app.py"}}},
                {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "source_status", "arguments": {}}},
                {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "refresh_source_index", "arguments": {"rebuild": True}}},
                {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "search_source", "arguments": {"query": "mcpneedle", "top_n": 0}}},
                {"jsonrpc": "2.0", "method": "exit"},
            ]
            proc = self.cli(*args, input="\n".join(json.dumps(x) for x in messages) + "\n")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            replies = [json.loads(x) for x in proc.stdout.splitlines()]
            names = {t["name"] for t in replies[1]["result"]["tools"]}
            self.assertTrue({"read_index", "search_memory", "source_status", "search_source", "read_source", "refresh_source_index"} <= names)
            result = json.loads(replies[2]["result"]["content"][0]["text"])
            self.assertEqual(result["results"][0]["path"], "app.py")
            self.assertTrue(replies[3]["result"]["isError"])
            self.assertEqual(json.loads(replies[4]["result"]["content"][0]["text"])["files"][0]["path"], "app.py")
            self.assertEqual(json.loads(replies[5]["result"]["content"][0]["text"])["text"], "mcpneedle")
            self.assertFalse(replies[6]["result"]["isError"])
            self.assertFalse(replies[7]["result"]["isError"])
            self.assertTrue(replies[8]["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
