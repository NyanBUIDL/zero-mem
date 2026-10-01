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

Identity (DEF-052): ``--profile-id`` / ``ZM_M6_PROFILE_ID`` pins the requesting
profile for the whole server process (one server per agent). A pinned server
overwrites ``arguments.requesting_profile_id``, rejects a different caller value
and drops the property from ``tools/list``. Without a pin the caller chooses its
own identity (legacy behaviour): the server warns on stderr and reports
``serverInfo.identity = "unpinned"``.

Start: ``python -m src.integration.m6.mcp_server``, the ``zero-mem-mcp`` console
script, or directly ``python src/integration/m6/mcp_server.py`` from any cwd.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# DEF-062: direct script start (``python src/integration/m6/mcp_server.py``) must work
# from any cwd.  The repo root has to be importable BEFORE the first project import
# (``zero_mem`` used to be imported first, so the sys.path fallback never ran).
if __package__ in (None, ""):
    _HERE = Path(__file__).resolve().parent
    _ROOT = _HERE.parents[2]
    # The script directory is sys.path[0] in this mode; its sibling modules
    # (tools.py, errors.py, ...) must not shadow top-level names.
    sys.path[:] = [p for p in sys.path if not p or Path(p).resolve() != _HERE]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from zero_mem.version import __version__ as _zm_version  # noqa: E402

try:
    from . import configure
    from .contracts import M6Response, ResponseStatus
    from .dispatcher import _default_dispatcher
    from .mcp_wrapper import handle_call, tool_schemas
except ImportError:  # direct script execution: absolute imports (root is on sys.path)
    from src.integration.m6 import configure  # noqa: E402
    from src.integration.m6.contracts import M6Response, ResponseStatus  # noqa: E402
    from src.integration.m6.dispatcher import _default_dispatcher  # noqa: E402
    from src.integration.m6.mcp_wrapper import handle_call, tool_schemas  # noqa: E402

# Envelope statuses that are NOT tool errors: a valid query that found something, or
# nothing.  Every other status (POLICY_DENIED, INVALID_REQUEST, UNSUPPORTED_*,
# CAPABILITY_UNAVAILABLE, DOWNSTREAM_ERROR, and any future one) sets ``isError``.
_OK_STATUSES = frozenset({ResponseStatus.SUCCESS.value, ResponseStatus.EMPTY.value})

REASON_IDENTITY_PINNED = "DENY_IDENTITY_PINNED"
MAX_IDENTIFIER_LENGTH = 256

# Text summary limits: the full envelope travels once, in ``structuredContent``.
_SUMMARY_MAX_ITEMS = 5
_SUMMARY_MAX_FIELD_CHARS = 200
_SUMMARY_MAX_CHARS = 2000
_PREVIEW_KEYS = ("external_ref", "memory_type", "normalized_text", "event_id", "event_type",
                 "title", "summary", "text", "decision_id", "requirement_id", "artifact_id",
                 "project_id")


# --------------------------------------------------------------------------
# Server identity (DEF-052)
# --------------------------------------------------------------------------
def _checked_identifier(value: Any, label: str) -> str:
    """A pinned profile id / default space: non-blank, bounded, no control characters."""
    if (not isinstance(value, str) or not value.strip()
            or len(value) > MAX_IDENTIFIER_LENGTH
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)):
        raise ValueError(f"{label} must be a non-blank identifier "
                         f"(<= {MAX_IDENTIFIER_LENGTH} chars, no control characters)")
    return value.strip()


@dataclass(frozen=True)
class ServerIdentity:
    """Per-process identity: the pinned requesting profile and optional default space."""

    profile_id: Optional[str] = None
    default_ks: Optional[str] = None

    @property
    def pinned(self) -> bool:
        return self.profile_id is not None


_IDENTITY = ServerIdentity()


def set_identity(profile_id: Optional[str] = None,
                 default_ks: Optional[str] = None) -> ServerIdentity:
    """Pin (or clear) the server identity; raises ValueError on a malformed value."""
    global _IDENTITY
    _IDENTITY = ServerIdentity(
        profile_id=None if profile_id is None else _checked_identifier(profile_id, "profile-id"),
        default_ks=None if default_ks is None else _checked_identifier(default_ks, "default-ks"),
    )
    return _IDENTITY


def get_identity() -> ServerIdentity:
    return _IDENTITY


def _apply_identity(tool: str, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Bind the pinned identity into ``arguments`` (in place).

    Returns a denial envelope when the caller supplied a DIFFERENT identity, else None.
    """
    ident = _IDENTITY
    if ident.profile_id is not None:
        supplied = arguments.get("requesting_profile_id")
        if supplied is not None and supplied != ident.profile_id:
            return M6Response(
                status=ResponseStatus.POLICY_DENIED,
                reason_code=REASON_IDENTITY_PINNED,
                diagnostics={"bounded": True},
            ).to_dict()
        arguments["requesting_profile_id"] = ident.profile_id
    # The default space is a sharing convenience for corpus search only: event/project
    # tools authorize per-row spaces and would be emptied by it.  An explicit
    # ``knowledge_space_ids`` (even ``[]``) always wins.
    if (ident.default_ks is not None and tool == "corpus_search"
            and arguments.get("knowledge_space_ids") is None):
        arguments["knowledge_space_ids"] = [ident.default_ks]
    return None


# --------------------------------------------------------------------------
# JSON-RPC
# --------------------------------------------------------------------------
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


def _clip(value: Any, limit: int = _SUMMARY_MAX_FIELD_CHARS) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _preview(item: Any) -> str:
    """One bounded line describing a result item (for clients that only read text)."""
    if not isinstance(item, dict):
        return _clip(item)
    scalar = (str, int, float, bool)
    parts: List[str] = []
    for key in _PREVIEW_KEYS:
        value = item.get(key)
        if isinstance(value, scalar) and value != "":
            parts.append(f"{key}={_clip(value)}")
        if len(parts) >= 4:
            break
    if not parts:
        for key, value in item.items():
            if isinstance(value, scalar) and value != "":
                parts.append(f"{key}={_clip(value)}")
            if len(parts) >= 3:
                break
    return "; ".join(parts)


def _summarize(tool: str, envelope: Dict[str, Any]) -> str:
    """Short text for ``content``: status, reason, count, a bounded preview.

    The complete envelope is ``structuredContent``; it is deliberately NOT repeated here.
    """
    status = envelope.get("status", "UNKNOWN")
    head = f"{tool}: {status}"
    reason = envelope.get("reason_code")
    if reason:
        head += f" ({reason})"
    results = envelope.get("results") or []
    if results:
        head += f" - {len(results)} result(s)"
    lines = [head]
    for index, item in enumerate(results[:_SUMMARY_MAX_ITEMS], 1):
        lines.append(f"{index}. {_preview(item)}")
    if len(results) > _SUMMARY_MAX_ITEMS:
        lines.append(f"... {len(results) - _SUMMARY_MAX_ITEMS} more in structuredContent.results")
    if envelope.get("next_cursor"):
        lines.append("More pages available: pass next_cursor as cursor.")
    if results:
        lines.append("Full records are in structuredContent.")
    text = "\n".join(lines)
    return text if len(text) <= _SUMMARY_MAX_CHARS else text[: _SUMMARY_MAX_CHARS - 3] + "..."


def _tool_result(tool: str, envelope: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "content": [{"type": "text", "text": _summarize(tool, envelope)}],
        "structuredContent": envelope,
        "isError": envelope.get("status") not in _OK_STATUSES,
    }


def _handle_rpc(method: str, params: Dict[str, Any], request_id: Optional[Any]) -> Optional[Dict[str, Any]]:
    """Return a response dict, or None for notifications (no reply)."""
    if method == "ping":
        return _respond(request_id, result={})

    if method == "initialize":
        return _respond(request_id, result={
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "zero-mem-m6", "version": _zm_version,
                           "identity": "pinned" if _IDENTITY.pinned else "unpinned"},
        })

    if method == "tools/list":
        return _respond(request_id, result={
            "tools": tool_schemas(include_identity=not _IDENTITY.pinned)})

    if method == "tools/call":
        tool = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(tool, str):
            return _respond(request_id, error={
                "code": -32602, "message": "invalid params: missing tool name"})
        if not isinstance(arguments, dict):
            return _respond(request_id, error={
                "code": -32602, "message": "invalid params: arguments must be object"})
        arguments = dict(arguments)
        envelope = _apply_identity(tool, arguments)
        if envelope is None:
            envelope = handle_call(tool, arguments, dispatcher=_make_dispatcher())
        # MCP tools/call: the complete envelope is structuredContent; ``content`` is a
        # short text summary (the envelope is not sent twice).
        return _respond(request_id, result=_tool_result(tool, envelope))

    # Unknown method: method-not-found (JSON-RPC -32601). Notifications start
    # with "notifications/": do not reply to them.
    if method.startswith("notifications/"):
        return None
    return _respond(request_id, error={
        "code": -32601, "message": f"method not found: {method}"})


def serve(store_path: Path, *, in_stream=None, out_stream=None,
          profile_id: Optional[str] = None, default_ks: Optional[str] = None) -> None:
    """Run the stdio JSON-RPC loop until EOF on stdin."""
    configure(store_path)  # wires M6.2/M6.3 handlers onto default dispatcher
    _make_dispatcher()     # ensure shared dispatcher is returned consistently
    identity = set_identity(profile_id, default_ks)
    if not identity.pinned:
        sys.stderr.write(
            "zero-mem-mcp: WARNING identity unpinned - callers choose requesting_profile_id "
            "and can read any profile's rows they name; pin it with --profile-id or "
            "ZM_M6_PROFILE_ID (one server per agent)\n")
        sys.stderr.flush()
    inn = in_stream or sys.stdin
    out = out_stream or sys.stdout

    try:
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
    finally:
        set_identity(None, None)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Zero-Mem M6 MCP read-only server (stdio)")
    ap.add_argument("--store-path", type=str, default=os.environ.get("ZM_M6_STORE_PATH"),
                    help="Path to the derived Zero-Mem SQLite store (read-only).")
    ap.add_argument("--profile-id", type=str, default=None,
                    help="Pin the requesting profile for this server process "
                         "(env ZM_M6_PROFILE_ID). Callers cannot choose another identity.")
    ap.add_argument("--default-ks", type=str, default=None,
                    help="Knowledge space applied to corpus_search when the caller omits "
                         "knowledge_space_ids (env ZM_M6_DEFAULT_KS).")
    ap.add_argument("--transport", type=str, default="stdio",
                    help="Transport (only 'stdio' supported in V140-03).")
    args = ap.parse_args(argv)
    if not args.store_path:
        sys.stderr.write("ERROR: --store-path (or ZM_M6_STORE_PATH) is required\n")
        return 2
    if args.transport != "stdio":
        sys.stderr.write("ERROR: only stdio transport is supported in V140-03\n")
        return 2
    # An explicit flag is validated strictly; an empty environment value means "unset".
    profile_id = args.profile_id
    if profile_id is None:
        profile_id = os.environ.get("ZM_M6_PROFILE_ID") or None
    default_ks = args.default_ks
    if default_ks is None:
        default_ks = os.environ.get("ZM_M6_DEFAULT_KS") or None
    try:
        set_identity(profile_id, default_ks)
    except ValueError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 2
    serve(Path(args.store_path), profile_id=profile_id, default_ks=default_ks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
