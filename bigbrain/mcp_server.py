"""Minimal MCP (Model Context Protocol) stdio server for BigBrain.

Implements just enough of the MCP spec (JSON-RPC 2.0, newline-delimited
messages over stdio) to expose the four BigBrain tools natively to any
MCP-capable host (Claude Code, Cursor, etc.). No SDK dependency, so it
works anywhere the `bigbrain` package is installed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from . import __version__, core, schemas

SERVER_NAME = "bigbrain"


def _mcp_tools() -> list:
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "inputSchema": t["parameters"],
        }
        for t in schemas.TOOLS
    ]


def _text_result(text: str, is_error: bool = False) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _call_tool(root: Path, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    try:
        if name == "read_index":
            return _text_result(core.read_index(root))
        if name == "read_memory_file":
            return _text_result(core.read_memory(root, arguments["file_id"]))
        if name == "append_transaction_log":
            core.append_log(
                root,
                arguments["type"],
                arguments["target_file_id"],
                arguments["summary"],
                arguments["details"],
            )
            return _text_result(f"Logged {arguments['type']} targeting '{arguments['target_file_id']}'.")
        if name == "compile_memory":
            result = core.compile_memory(
                root,
                reason=arguments.get("reason", "unspecified"),
                use_llm=bool(arguments.get("use_llm", False)),
            )
            return _text_result(json.dumps(result, indent=2))
        if name == "search_memory":
            hits = core.search(root, arguments["query"], top_n=int(arguments.get("top_n", 8)))
            if not hits:
                return _text_result("No relevant memory files found.")
            text = "\n".join(f"{h['file_id']} (score={h['score']}, {h['path']}): {h['snippet']}" for h in hits)
            return _text_result(text)
        if name == "grep_memory":
            hits = core.grep(root, arguments["term"], include_log=bool(arguments.get("include_log", False)))
            if not hits:
                return _text_result("No matches.")
            text = "\n".join(f"{h['file_id']} ({h['path']}:{h['line']}): {h['text']}" for h in hits)
            return _text_result(text)
        return _text_result(f"Unknown tool: {name}", is_error=True)
    except Exception as e:  # noqa: BLE001 - report to the model, don't crash the server
        return _text_result(f"BigBrain error: {e}", is_error=True)


def _handle(root: Path, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = msg.get("method")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": __version__},
            },
        }

    if method in ("notifications/initialized", "notifications/cancelled"):
        return None

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": _mcp_tools()}}

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        result = _call_tool(root, name, arguments)
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    if method in ("shutdown",):
        return {"jsonrpc": "2.0", "id": msg_id, "result": None}

    if msg_id is not None:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    return None


def serve(root: Optional[Path] = None) -> None:
    root = Path(root) if root is not None else Path.cwd()
    core.init_engine(root)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        if method_is_exit(msg):
            break

        response = _handle(root, msg)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


def method_is_exit(msg: Dict[str, Any]) -> bool:
    return msg.get("method") == "exit"


if __name__ == "__main__":
    serve()
