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
/ WRITE path is reachable through the 11 M6 tools. 0 LLM + 0 external network.

Optional memory tools (T6b): ``--enable-memory`` mounts memory_recall / memory_context and
``--enable-write`` additionally memory_add / memory_ingest / memory_forget from the separate
package ``src.integration.m6w`` (see ``mount_tool_set``).  They need a pinned identity, run as
that profile only and delegate to ``zero_mem.memory.Memory`` (authorize -> secret pre-scan ->
lock -> register).  Without those switches the server is exactly the read-only M6 surface.

Tool set (T8, token cost): ``--tools memory`` (env ``ZM_M6_TOOLS``) lists and serves ONLY the
mounted memory tools - the 11 M6 tools are ~17 KB of ``tools/list`` per agent session.  The
default here stays ``all`` (the pinned T6a / T6b surface); ``zero-mem serve`` passes ``memory``
unless it is given ``--tools all``.

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
    from .tools import list_tool_names
except ImportError:  # direct script execution: absolute imports (root is on sys.path)
    from src.integration.m6 import configure  # noqa: E402
    from src.integration.m6.contracts import M6Response, ResponseStatus  # noqa: E402
    from src.integration.m6.dispatcher import _default_dispatcher  # noqa: E402
    from src.integration.m6.mcp_wrapper import handle_call, tool_schemas  # noqa: E402
    from src.integration.m6.tools import list_tool_names  # noqa: E402

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


# --------------------------------------------------------------------------
# Extension tool sets (T6b)
# --------------------------------------------------------------------------
# The 11 M6 tools above stay read-only and exactly as pinned.  A separate package
# (``src.integration.m6w``: memory_recall / memory_context and, only with
# ``--enable-write``, memory_add / memory_ingest / memory_forget) is MOUNTED here, never
# registered in M6's own ``TOOL_REGISTRY``.  A tool set provides ``profile_id``, ``names``,
# ``schemas()``, ``handles(name)`` and ``call(name, arguments) -> MCP tool result``; it
# acts as the pinned profile only, so mounting needs a pinned identity that equals its own.
_TOOL_SETS: List[Any] = []

# T8 (token footprint): the 11 legacy M6 tools are ~17 KB of ``tools/list`` that every agent session pays for.
# ``--tools memory`` lists and serves only the mounted memory tools; the default (``all``) is exactly the pinned T6a
# surface, so a plain ``zero-mem-mcp`` is unchanged.  ``zero-mem serve`` passes ``memory`` unless told ``--tools all``.
_LEGACY_TOOLS = True
TOOLS_ALL = "all"
TOOLS_MEMORY = "memory"


def mount_tool_set(tool_set: Any) -> None:
    """Add ``tool_set``'s tools to ``tools/list`` and route their ``tools/call`` to it."""
    if not _IDENTITY.pinned or getattr(tool_set, "profile_id", None) != _IDENTITY.profile_id:
        raise ValueError("a tool set can only be mounted on a server pinned to the same profile")
    taken = set(list_tool_names())
    for mounted in _TOOL_SETS:
        taken.update(mounted.names)
    clash = taken.intersection(tool_set.names)
    if clash:
        raise ValueError("tool name already in use: " + ", ".join(sorted(clash)))
    _TOOL_SETS.append(tool_set)


def unmount_tool_sets() -> None:
    _TOOL_SETS.clear()


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
        info: Dict[str, Any] = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "zero-mem-m6", "version": _zm_version,
                           "identity": "pinned" if _IDENTITY.pinned else "unpinned"},
        }
        notes = [t for t in (getattr(mounted, "instructions", "") for mounted in _TOOL_SETS) if t]
        if notes:  # only when extension tools are mounted: the plain M6 server answers exactly as before
            info["instructions"] = "\n".join(notes)
        return _respond(request_id, result=info)

    if method == "tools/list":
        tools = tool_schemas(include_identity=not _IDENTITY.pinned) if _LEGACY_TOOLS else []
        for mounted in _TOOL_SETS:
            tools = tools + mounted.schemas()
        return _respond(request_id, result={"tools": tools})

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
        for mounted in _TOOL_SETS:  # T6b: mounted tools answer with their own complete MCP result
            if mounted.handles(tool):
                return _respond(request_id, result=mounted.call(tool, arguments))
        if not _LEGACY_TOOLS:  # memory-only server: a legacy tool is not exposed at all (same answer as an unknown tool)
            envelope = M6Response(status=ResponseStatus.UNSUPPORTED_TOOL, reason_code="UNSUPPORTED_TOOL",
                                  diagnostics={"bounded": True}).to_dict()
            return _respond(request_id, result=_tool_result(tool, envelope))
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
          profile_id: Optional[str] = None, default_ks: Optional[str] = None,
          tool_sets: Optional[List[Any]] = None, legacy_tools: bool = True) -> None:
    """Run the stdio JSON-RPC loop until EOF on stdin (``tool_sets`` are mounted for the loop's lifetime).

    ``legacy_tools=False`` serves ONLY the mounted tool sets (``--tools memory``): the 11 M6 tools are neither
    listed nor callable.
    """
    global _LEGACY_TOOLS
    if not legacy_tools and not tool_sets:
        raise ValueError("a server without the legacy tools needs a mounted tool set")
    configure(store_path)  # wires M6.2/M6.3 handlers onto default dispatcher
    _make_dispatcher()     # ensure shared dispatcher is returned consistently
    identity = set_identity(profile_id, default_ks)
    unmount_tool_sets()
    _LEGACY_TOOLS = bool(legacy_tools)
    for tool_set in tool_sets or ():
        mount_tool_set(tool_set)
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
        unmount_tool_sets()
        _LEGACY_TOOLS = True
        set_identity(None, None)


_TRUE_WORDS = frozenset({"1", "true", "yes", "on"})


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in _TRUE_WORDS


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Zero-Mem M6 MCP server (stdio): read-only unless --enable-memory / --enable-write")
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
    ap.add_argument("--enable-memory", action="store_true", default=False,
                    help="Also mount the memory_recall, memory_context and memory_brief tools (env ZM_M6_ENABLE_MEMORY=1). "
                         "Needs --profile-id; the store must be the zero-mem data root's database.")
    ap.add_argument("--enable-write", action="store_true", default=False,
                    help="Also mount memory_add, memory_ingest and memory_forget (env ZM_M6_ENABLE_WRITE=1); "
                         "implies --enable-memory. Off by default: the server is read-only unless asked.")
    ap.add_argument("--enable-propose", action="store_true", default=False,
                    help="Also mount memory_propose (env ZM_M6_ENABLE_PROPOSE=1); implies --enable-memory. An agent may "
                         "SUGGEST a rule / decision / gotcha; it stays inert until the owner approves it.")
    ap.add_argument("--allow-root", action="append", default=None, metavar="DIR",
                    help="Folder memory_ingest may read (repeatable; env ZM_M6_ALLOW_ROOTS, path-separator "
                         "separated). Without any, memory_ingest is disabled.")
    ap.add_argument("--tools", choices=(TOOLS_ALL, TOOLS_MEMORY), default=None,
                    help="'all' (default): the 11 M6 read tools plus any mounted memory tools. 'memory': ONLY the "
                         "memory tools (needs --enable-memory); ~17 KB less in every session's tools/list "
                         "(env ZM_M6_TOOLS).")
    args = ap.parse_args(argv)
    from src.storage.platform import use_utf8_stdio

    use_utf8_stdio(lf_newlines=True)  # DEF-086: JSON-RPC lines are UTF-8 with bare LF on every platform
    tools_mode = args.tools or (os.environ.get("ZM_M6_TOOLS") or "").strip() or TOOLS_ALL
    if tools_mode not in (TOOLS_ALL, TOOLS_MEMORY):
        sys.stderr.write("ERROR: --tools must be 'all' or 'memory'\n")
        return 2
    want_write = bool(args.enable_write) or _env_flag("ZM_M6_ENABLE_WRITE")
    want_propose = bool(args.enable_propose) or _env_flag("ZM_M6_ENABLE_PROPOSE")
    want_memory = want_write or want_propose or bool(args.enable_memory) or _env_flag("ZM_M6_ENABLE_MEMORY")
    if tools_mode == TOOLS_MEMORY and not want_memory:
        sys.stderr.write("ERROR: --tools memory needs --enable-memory (or --enable-write)\n")
        return 2
    if not args.store_path and not want_memory:
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
    allow_roots = list(args.allow_root or []) + [
        p for p in (os.environ.get("ZM_M6_ALLOW_ROOTS") or "").split(os.pathsep) if p.strip()]
    tool_sets: List[Any] = []
    store_path = args.store_path
    if want_memory:
        if profile_id is None:
            sys.stderr.write("ERROR: the memory tools act as one agent: pin it with --profile-id "
                             "(or ZM_M6_PROFILE_ID)\n")
            return 2
        try:
            from src.integration.m6w import ToolSetConfigError, build_tool_set
            memory_tools = build_tool_set(profile_id=profile_id, enable_write=want_write, allow_roots=allow_roots,
                                           enable_propose=want_propose)
        except ToolSetConfigError as exc:
            sys.stderr.write(f"ERROR: {exc}\n")
            return 2
        if store_path and Path(store_path).resolve() != memory_tools.store_path.resolve():
            sys.stderr.write("ERROR: --store-path is not the database of the zero-mem data root "
                             "(ZERO_MEM_DATA_ROOT); the memory tools and the read tools must use one store\n")
            return 2
        store_path = store_path or str(memory_tools.store_path)
        tool_sets.append(memory_tools)
        sys.stderr.write(f"zero-mem-mcp: memory tools mounted (write {'on' if want_write else 'off'}, "
                         f"propose {'on' if want_propose else 'off'}, "
                         f"{len(allow_roots)} allowed folder(s), tools {tools_mode})\n")
        for note in memory_tools.startup_notes():
            sys.stderr.write(f"zero-mem-mcp: {note}\n")
        sys.stderr.flush()
    elif allow_roots:
        sys.stderr.write("zero-mem-mcp: WARNING allow-root ignored: the memory tools are not enabled "
                         "(--enable-memory / --enable-write / --enable-propose)\n")
        sys.stderr.flush()
    serve(Path(store_path), profile_id=profile_id, default_ks=default_ks, tool_sets=tool_sets,
          legacy_tools=tools_mode == TOOLS_ALL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
