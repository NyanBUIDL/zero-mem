"""V140-03 — MCP server wrapper (stdio JSON-RPC) for the Zero-Mem M6 read surface.

This is a THIN transport adapter. It does NOT fork or re-implement any core
logic: it reuses the existing M6 dispatcher, contracts, runtime, and wired
handlers (M6.2/M6.3). The only thing added here is the stdio JSON-RPC framing
required by the Model Context Protocol so a NON-Hermes client can drive the
read-only memory surface.

Protocol handled (minimal MCP subset sufficient for read tools):
  - initialize             -> returns serverInfo + capabilities (tools)
  - tools/list             -> tool_schemas() from mcp_wrapper
  - tools/call             -> maps to mcp_wrapper.handle_call(tool, arguments)
  - ping / notifications/* -> acked (notifications return nothing)

All reads are funneled through the dispatcher, so the READ-only / authorization
contracts in src/integration/m6 are fully preserved. No SQLite/JSONL/grant-admin
/ WRITE path is reachable from this server. 0 LLM + 0 external network.

Server is configured with a derived-store path supplied at startup (argv or
env ZM_M6_STORE_PATH). No hard-coded repository or user paths.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from zero_mem.version import __version__ as _zm_version

try:
    from . import configure
    from .dispatcher import _default_dispatcher
    from .mcp_wrapper import handle_call, tool_schemas
    from .runtime import get_runtime
except ImportError:  # direct script execution: add repo root and use absolute imports
    from pathlib import Path as _P
    import sys as _sys
    _sys.path.insert(0, str(_P(__file__).resolve().parent.parent.parent.parent))
    from src.integration.m6 import configure  # noqa: E402
    from src.integration.m6.dispatcher import _default_dispatcher  # noqa: E402
    from src.integration.m6.mcp_wrapper import handle_call, tool_schemas  # noqa: E402
    from src.integration.m6.runtime import get_runtime  # noqa: E402


def _make_dispatcher() -> Any:
    """Return the shared default dispatcher with wired handlers (no fork)."""
    # configure() registers handlers on _default_dispatcher already, but calling
    # it again is idempotent and keeps this module usable standalone.
    return _default_dispatcher


def _respond(request_id: Optional[Any], result: Optional[Dict[str, Any]] = None,
             error: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    msg: Dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    return msg


def _handle_rpc(method: str, params: Dict[str, Any], request_id: Optional[Any]) -> Optional[Dict[str, Any]]:
    """Return a response dict, or None for notifications (no reply)."""
    if method == "ping":
        return _respond(request_id, result={})

    if method == "initialize":
        return _respond(request_id, result={
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "zero-mem-m6", "version": _zm_version},
        })

    if method == "tools/list":
        return _respond(request_id, result={"tools": tool_schemas()})

    if method == "tools/call":
        tool = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(tool, str):
            return _respond(request_id, error={
                "code": -32602, "message": "invalid params: missing tool name"})
        if not isinstance(arguments, dict):
            return _respond(request_id, error={
                "code": -32602, "message": "invalid params: arguments must be object"})
        envelope = handle_call(tool, arguments, dispatcher=_make_dispatcher())
        # MCP tools/call wraps the tool result under content; surface our envelope
        # as structuredContent and a short text echo.
        return _respond(request_id, result={
            "content": [
                {"type": "text", "text": json.dumps(envelope, ensure_ascii=False)},
            ],
            "structuredContent": envelope,
            "isError": envelope.get("status") in ("DENIED", "INVALID_REQUEST",
                                                  "UNSUPPORTED_TOOL", "UNSUPPORTED_OPERATION",
                                                  "CAPABILITY_UNAVAILABLE", "DOWNSTREAM_ERROR"),
        })

    # Unknown method: method-not-found (JSON-RPC -32601). Notifications start
    # with "notifications/": do not reply to them.
    if method.startswith("notifications/"):
        return None
    return _respond(request_id, error={
        "code": -32601, "message": f"method not found: {method}"})


def serve(store_path: Path, *, in_stream=None, out_stream=None) -> None:
    """Run the stdio JSON-RPC loop until EOF on stdin."""
    configure(store_path)  # wires M6.2/M6.3 handlers onto default dispatcher
    _make_dispatcher()     # ensure shared dispatcher is returned consistently
    inn = in_stream or sys.stdin
    out = out_stream or sys.stdout

    for line in inn:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            out.write(json.dumps(_respond(None, error={
                "code": -32700, "message": "parse error"})))
            out.write("\n")
            out.flush()
            continue
        method = req.get("method")
        params = req.get("params") or {}
        request_id = req.get("id")  # None for notifications
        if not isinstance(params, dict):
            params = {}
        resp = _handle_rpc(method, params, request_id)
        if resp is not None:
            out.write(json.dumps(resp, ensure_ascii=False))
            out.write("\n")
            out.flush()


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Zero-Mem M6 MCP read-only server (stdio)")
    ap.add_argument("--store-path", type=str, default=os.environ.get("ZM_M6_STORE_PATH"),
                    help="Path to the derived Zero-Mem SQLite store (read-only).")
    ap.add_argument("--transport", type=str, default="stdio",
                    help="Transport (only 'stdio' supported in V140-03).")
    args = ap.parse_args(argv)
    if not args.store_path:
        sys.stderr.write("ERROR: --store-path (or ZM_M6_STORE_PATH) is required\n")
        return 2
    if args.transport != "stdio":
        sys.stderr.write("ERROR: only stdio transport is supported in V140-03\n")
        return 2
    serve(Path(args.store_path))
    return 0


if __name__ == "__main__":
    # Support both `python -m src.integration.m6.mcp_server` and direct script
    # execution. In direct-script mode, fix the package import path.
    if __package__ in (None, ""):
        import os as _os
        _here = Path(__file__).resolve().parent
        sys.path.insert(0, str(_here.parent.parent.parent))  # repo root
        from src.integration.m6 import mcp_server as _mod
        raise SystemExit(_mod.main())
    raise SystemExit(main())
