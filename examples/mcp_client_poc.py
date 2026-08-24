#!/usr/bin/env python3
"""V140-03 — POC MCP client (NON-Hermes) for the Zero-Mem M6 read surface.

This is the proof-of-concept used by the independent verifier to show a client
that is NOT Hermes can drive the read-only memory knowledge base over MCP
(stdio). It uses only the Python standard library (subprocess + json) so it
runs from a clean machine with just CPython.

It talks the minimal MCP subset implemented by src/integration/m6/mcp_server.py:
  initialize -> tools/list -> tools/call

Usage:
  python3 examples/mcp_client_poc.py --store-path <derived.sqlite> \
      --tool memory_search --arguments '{"search_text":"kelly criterion","...}'

Or run the bundled demo:
  python3 examples/mcp_demo.py --store-path <derived.sqlite>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def _rpc(proc, method: str, params: Optional[Dict[str, Any]] = None,
         request_id: Any = 1) -> Optional[Dict[str, Any]]:
    msg = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        msg["params"] = params
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line:
        return None
    return json.loads(line)


def call_tool(proc, tool: str, arguments: Dict[str, Any], request_id: int = 3) -> Dict[str, Any]:
    resp = _rpc(proc, "tools/call", {"name": tool, "arguments": arguments}, request_id)
    if resp is None:
        raise RuntimeError("MCP server closed connection")
    if "error" in resp:
        raise RuntimeError(f"MCP error: {resp['error']}")
    return resp["result"]


def run_poc(store_path: Path, tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    server = Path(__file__).resolve().parent.parent / "src" / "integration" / "m6" / "mcp_server.py"
    if not server.exists():
        raise RuntimeError(f"MCP server not found at {server}")
    proc = subprocess.Popen(
        [sys.executable, str(server), "--store-path", str(store_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        text=True, bufsize=1,
    )
    try:
        _rpc(proc, "initialize", {}, 1)
        _rpc(proc, "tools/list", {}, 2)
        result = call_tool(proc, tool, arguments, 3)
        return result
    finally:
        try:
            if proc.stdin is not None:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store-path", required=True)
    ap.add_argument("--tool", default="memory_search")
    ap.add_argument("--arguments", default='{"search_text":"kelly criterion","limit":3}',
                    help="JSON object of tool arguments.")
    args = ap.parse_args()

    arguments = json.loads(args.arguments)
    result = run_poc(Path(args.store_path), args.tool, arguments)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
