import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bigbrain import core  # noqa: E402


def _tmp_root() -> Path:
    d = Path(tempfile.mkdtemp(prefix="bigbrain_test_"))
    return d


def test_init_creates_structure():
    root = _tmp_root()
    p = core.init_engine(root)
    assert p.big_brain_dir.is_dir()
    assert p.memory_dir.is_dir()
    assert p.index_file.exists()
    assert p.log_file.exists()
    ids = set(core.list_memory_ids(root))
    assert {"system_invariants", "architecture", "active_tasks", "decisions", "domain_knowledge"} <= ids


def test_init_is_idempotent():
    root = _tmp_root()
    core.init_engine(root)
    (core.paths(root).memory_dir / "architecture.md").write_text("---\nid: architecture\n---\n\ncustom", encoding="utf-8")
    core.init_engine(root)
    content = core.read_memory(root, "architecture")
    assert "custom" in content


def test_read_index_and_memory():
    root = _tmp_root()
    core.init_engine(root)
    index = core.read_index(root)
    assert "File ID" in index
    assert "architecture" in index

    body = core.read_memory(root, "architecture")
    assert "id: architecture" in body


def test_read_missing_memory_raises():
    root = _tmp_root()
    core.init_engine(root)
    try:
        core.read_memory(root, "does_not_exist")
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_append_log_and_compile_reconciles():
    root = _tmp_root()
    core.init_engine(root)
    core.append_log(root, "DECISION", "decisions", "Chose SQLite", "Because ACID writes matter.")
    core.append_log(root, "TASK_UPDATE", "active_tasks", "Shipped installer", "Wired into AGENTS.md.")

    status_before = core.status(root)
    assert status_before["pending_log_entries"] == 2

    result = core.compile_memory(root, reason="test")
    assert result["entries_processed"] == 2
    assert len(result["files_updated"]) == 2

    decisions = core.read_memory(root, "decisions")
    assert "Chose SQLite" in decisions
    tasks = core.read_memory(root, "active_tasks")
    assert "Shipped installer" in tasks

    status_after = core.status(root)
    assert status_after["pending_log_entries"] == 0
    assert not core.paths(root).lock_file.exists()


def test_compile_creates_new_memory_file_for_unknown_target():
    root = _tmp_root()
    core.init_engine(root)
    core.append_log(root, "LEARNING", "api_contracts", "Payments API v2", "Uses cursor pagination.")
    core.compile_memory(root, reason="test")
    content = core.read_memory(root, "api_contracts")
    assert "Payments API v2" in content
    index = core.read_index(root)
    assert "api_contracts" in index


def test_invalid_log_type_rejected():
    root = _tmp_root()
    core.init_engine(root)
    try:
        core.append_log(root, "NOT_A_TYPE", "decisions", "x", "y")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_cli_install_wires_agent_files():
    root = _tmp_root()
    pkg_root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [sys.executable, "-m", "bigbrain.cli", "--path", str(root), "install"],
        cwd=pkg_root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert (root / "AGENTS.md").exists()
    assert (root / "CLAUDE.md").exists()
    assert "BEGIN BIGBRAIN" in (root / "AGENTS.md").read_text(encoding="utf-8")
    mcp_config = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp_config["mcpServers"]["bigbrain"]["command"] == "bigbrain"
    assert (root / ".bigbrain" / "tools.json").exists()
    assert (root / ".bigbrain" / "config.yml").exists()


def test_install_wires_git_hook_and_claude_hooks():
    root = _tmp_root()
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True, text=True)
    from bigbrain import install as install_mod

    install_mod.install(root)

    hook_path = root / ".git" / "hooks" / "pre-commit"
    assert hook_path.exists()
    assert "BEGIN BIGBRAIN" in hook_path.read_text(encoding="utf-8")

    claude_settings = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "SessionStart" in claude_settings["hooks"]
    assert "SessionEnd" in claude_settings["hooks"]
    assert "PreCompact" in claude_settings["hooks"]

    # idempotent: re-running shouldn't duplicate hook entries
    install_mod.install(root)
    claude_settings_2 = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert len(claude_settings_2["hooks"]["SessionStart"]) == 1


def test_grep_finds_term_across_memory_files():
    root = _tmp_root()
    core.init_engine(root)
    core.append_log(root, "LEARNING", "domain_knowledge", "Payments API v2", "Uses cursor pagination for listing.")
    core.compile_memory(root, reason="test")
    hits = core.grep(root, "cursor pagination")
    assert any(h["file_id"] == "domain_knowledge" for h in hits)


def test_compile_llm_falls_back_on_missing_cli():
    root = _tmp_root()
    core.init_engine(root)
    (core.paths(root).big_brain_dir / "config.yml").write_text(
        "llm_command: \"definitely_not_a_real_binary_xyz\"\n", encoding="utf-8"
    )
    core.append_log(root, "DECISION", "decisions", "Chose SQLite", "ACID writes matter.")
    result = core.compile_memory(root, reason="test", use_llm=True)
    assert result["mode"] == "llm"
    assert result["warnings"], "expected a fallback warning when the LLM CLI is missing"
    assert "Chose SQLite" in core.read_memory(root, "decisions")


def test_search_ranks_by_word_overlap():
    root = _tmp_root()
    core.init_engine(root)
    core.append_log(root, "LEARNING", "domain_knowledge", "Payments API", "Uses cursor based pagination for listing charges.")
    core.compile_memory(root, reason="test")
    hits = core.search(root, "how does pagination work for charges")
    assert hits, "expected at least one ranked hit"
    assert hits[0]["file_id"] == "domain_knowledge"
    assert hits[0]["score"] > 0


def test_search_no_match_returns_empty():
    root = _tmp_root()
    core.init_engine(root)
    assert core.search(root, "totally_unrelated_zzz_term") == []


def test_doctor_clean_repo_has_no_issues():
    root = _tmp_root()
    core.init_engine(root)
    result = core.doctor(root)
    assert result["issues"] == []


def test_doctor_detects_and_fixes_missing_id_and_stale_lock():
    root = _tmp_root()
    core.init_engine(root)
    p = core.paths(root)

    arch = p.memory_dir / "architecture.md"
    content = arch.read_text(encoding="utf-8")
    broken = content.replace("id: architecture\n", "")
    arch.write_text(broken, encoding="utf-8")

    p.lock_file.write_text("12345", encoding="utf-8")
    old_time = time.time() - 999
    os.utime(p.lock_file, (old_time, old_time))

    result = core.doctor(root)
    assert any("missing 'id'" in i for i in result["issues"])
    assert any("stale" in i.lower() for i in result["issues"])

    fix_result = core.doctor(root, fix=True)
    assert any("Set id=" in f for f in fix_result["fixed"])
    assert any("stale" in f.lower() for f in fix_result["fixed"])
    assert not p.lock_file.exists()

    clean_result = core.doctor(root)
    assert clean_result["issues"] == []


def test_doctor_fix_leaves_no_residual_issues():
    """Regression: --fix used to report a just-fixed problem in `issues` too,
    so `bigbrain doctor --fix` exited 1 even after successfully repairing
    everything. A fix run must report each problem in exactly one bucket.
    """
    root = _tmp_root()
    core.init_engine(root)
    p = core.paths(root)
    arch = p.memory_dir / "architecture.md"
    arch.write_text(arch.read_text(encoding="utf-8").replace("id: architecture\n", ""), encoding="utf-8")

    fix_result = core.doctor(root, fix=True)
    assert fix_result["issues"] == [], f"fix run should leave no residual issues, got {fix_result['issues']}"
    assert any("Set id=" in f for f in fix_result["fixed"])


def test_doctor_detects_duplicate_ids():
    root = _tmp_root()
    core.init_engine(root)
    p = core.paths(root)
    dup = p.memory_dir / "architecture_copy.md"
    dup.write_text(
        "---\nid: architecture\ntitle: Dup\ndomain: Tech\nschema_version: 1.0.0\n---\n\ncopy\n",
        encoding="utf-8",
    )
    result = core.doctor(root)
    assert any("Duplicate id" in i for i in result["issues"])
    fix_result = core.doctor(root, fix=True)
    assert any("Renamed duplicate id" in f for f in fix_result["fixed"])


def test_append_log_is_lock_serialized_under_concurrency():
    root = _tmp_root()
    core.init_engine(root)

    def worker(n):
        core.append_log(root, "LEARNING", "domain_knowledge", f"entry-{n}", f"details-{n}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    log_text = core.paths(root).log_file.read_text(encoding="utf-8")
    entries = core.parse_log_entries(log_text)
    assert len(entries) == 20, f"expected 20 well-formed entries, got {len(entries)} (interleaved writes?)"


def test_archive_rotates_when_oversized():
    root = _tmp_root()
    core.init_engine(root)
    p = core.paths(root)
    (p.big_brain_dir / "config.yml").write_text("archive_max_bytes: 50\n", encoding="utf-8")
    p.archive_file.write_text("# BigBrain Log Archive\n\n" + ("x" * 100), encoding="utf-8")
    core.append_log(root, "LEARNING", "domain_knowledge", "small update", "details")
    result = core.compile_memory(root, reason="test")
    assert any("Rotated" in w for w in result["warnings"])
    rotated = list(p.big_brain_dir.glob("log.archive.*.md"))
    assert rotated, "expected a rotated archive file"


if __name__ == "__main__":
    failures = 0
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"FAIL {t.__name__}: {e}")
    sys.exit(1 if failures else 0)
