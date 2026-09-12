"""Optional LLM-assisted reconciliation for `bigbrain compile --llm`.

BigBrain works entirely without this module (the deterministic compiler in
core.py needs no API key and never calls out to a model). This module is an
opt-in upgrade: it pipes the reconciliation prompt to a locally-available LLM
CLI over stdin and reads the rewritten file back from stdout, so the same
dedup/contradiction-resolution behavior the original design called for is
available without BigBrain ever holding an API key itself.

Which CLI to use is either:
- explicit, via `llm_command` in `.bigbrain/config.yml` (a string or list),
- or auto-detected from a short list of CLIs we know the non-interactive
  flag for.

Auto-detection is deliberately conservative: guessing the wrong flag for an
unfamiliar CLI would silently corrupt memory files, so unknown tools require
an explicit `llm_command`.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from . import core

# (binary, args) for CLIs whose non-interactive "read a prompt from stdin,
# print the completion to stdout" invocation is well known.
_KNOWN_CLIS = [
    ("claude", ["-p"]),
    ("llm", []),
]


class LLMError(RuntimeError):
    pass


def resolve_command(root: Optional[Path] = None) -> Optional[List[str]]:
    cfg = core.load_config(root)
    explicit = cfg.get("llm_command")
    if explicit:
        return list(explicit) if isinstance(explicit, list) else str(explicit).split()

    for binary, args in _KNOWN_CLIS:
        if shutil.which(binary):
            return [binary, *args]
    return None


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def run_llm(root: Optional[Path], prompt: str, timeout: int = 120) -> str:
    cmd = resolve_command(root)
    if not cmd:
        raise LLMError(
            "No LLM CLI configured or found on PATH. Set `llm_command` in "
            ".bigbrain/config.yml (e.g. llm_command: \"claude -p\"), or "
            "install one of: " + ", ".join(b for b, _ in _KNOWN_CLIS)
        )
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
        )
    except FileNotFoundError as e:
        raise LLMError(f"LLM command not found: {cmd[0]}") from e
    except subprocess.TimeoutExpired as e:
        raise LLMError(f"LLM command timed out after {timeout}s: {' '.join(cmd)}") from e

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()[:500]
        raise LLMError(f"LLM command '{' '.join(cmd)}' failed (exit {proc.returncode}): {stderr}")

    output = _strip_fences((proc.stdout or "").strip())
    if not output:
        raise LLMError(f"LLM command '{' '.join(cmd)}' returned empty output.")
    return output
