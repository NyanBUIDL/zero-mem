"""CLI for the shared-memory runtime: add / ingest / search / context / forget / devlog / memory-status / agents /
serve / import-notes. Wired into ``zero_mem.cli``; every command is a thin shell over :class:`zero_mem.memory.Memory`
or :class:`zero_mem.provisioning.Provisioner` (no business logic here).

Exit codes (stable, also in docs/runbooks/shared-memory-quickstart.md):

    0 ok          1 partial (ingest/import finished but something was rejected or skipped for cause)
    2 invalid usage/input or setup/storage error      3 denied by authorization (needs an operator grant)
    4 content rejected (credential detected, unsupported, empty)      5 not found / nothing to do
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional

from .memory import MAX_TEXT_BYTES, MEMORY_TYPES, SCOPES, Memory, MemoryConfigError
from .memory_layout import Layout, LayoutError
from .provisioning import SHARED_SPACE, Provisioner, ProvisioningError

EXIT_OK, EXIT_PARTIAL, EXIT_ERROR, EXIT_DENIED, EXIT_REJECTED, EXIT_NOT_FOUND = 0, 1, 2, 3, 4, 5

_STATUS_EXIT = {
    "created": EXIT_OK, "updated": EXIT_OK, "unchanged": EXIT_OK, "forgotten": EXIT_OK, "already_forgotten": EXIT_OK,
    "ok": EXIT_OK, "empty": EXIT_OK, "partial": EXIT_PARTIAL,
    "denied": EXIT_DENIED, "rejected_secret": EXIT_REJECTED, "rejected_content": EXIT_REJECTED,
    "not_found": EXIT_NOT_FOUND, "invalid": EXIT_ERROR, "ambiguous": EXIT_ERROR, "error": EXIT_ERROR,
}
_REASONS = {
    "invalid_text": "the text is empty or not valid text",
    "text_too_large": f"the text is larger than {MAX_TEXT_BYTES // 1024} KiB (ingest a file instead)",
    "invalid_memory_type": "unknown memory type (use one of: " + ", ".join(MEMORY_TYPES) + ")",
    "invalid_scope": "unknown scope (use shared, private or project)",
    "invalid_name": "the name may use letters, digits and . _ : ~ + @ % - with / between parts (max 128)",
    "invalid_project_id": "the project id may use letters, digits and . _ - (max 64)",
    "project_id_required": "this needs --project",
    "project_id_not_allowed": "--project only applies to project-scoped memories",
    "devlog_requires_project_scope": "a devlog entry belongs to a project (use --scope project --project NAME)",
    "empty_query": "the query has no searchable words",
    "query_too_long": "the query is too long (max 1000 characters)",
    "invalid_limit": "-k must be between 1 and 200",
    "invalid_max_chars": "--max-chars must be between 1 and 200000",
    "invalid_source_id": "that is not a source id (use the id or mem:// reference shown by search)",
    "path_not_found": "path not found",
    "path_outside_allow_roots": "path is outside the allowed roots",
    "unsupported_format": "this file type is not supported",
    "parser_unavailable": "an optional parser for this file type is not installed (for PDFs: pip install pypdf)",
    "corrupt_source": "the file is corrupt or unreadable",
    "empty_source": "the file has no text content",
    "content_too_large": "the file is larger than the 16 MiB limit",
    "adapter_failed": "the file could not be parsed",
    "secret_detected": "a credential-like value was detected",
}


# ---------------------------------------------------------------------------------------------
# parser wiring
# ---------------------------------------------------------------------------------------------
def default_profile() -> str:
    return os.environ.get("ZERO_MEM_PROFILE") or "default"


def add_global_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile", default=default_profile(),
        help="agent profile to act as (default: $ZERO_MEM_PROFILE or 'default')")
    parser.add_argument("--json", action="store_true", default=False,
                        help="machine-readable output (memory commands)")


def _common() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    # SUPPRESS: a value given before the subcommand survives; one given after it wins.
    common.add_argument("--profile", default=argparse.SUPPRESS, help="agent profile to act as")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output")
    return common


def _target_options(p: argparse.ArgumentParser, *, name_option: bool) -> None:
    p.add_argument("--type", dest="memory_type", choices=MEMORY_TYPES, default=None,
                   help="memory type (default: fact; devlog for the devlog command)")
    p.add_argument("--scope", choices=SCOPES, default=None,
                   help="private (default), shared (ks-shared; needs an operator-approved write grant) or project")
    p.add_argument("--project", dest="project_id", default=None, help="project id (project scope / devlog)")
    if name_option:
        p.add_argument("--name", default=None, help="stable name: re-adding under the same name makes a new version")


def add_memory_parsers(subparsers) -> None:
    common = _common()

    p = subparsers.add_parser("add", parents=[common], help="remember a piece of text")
    p.add_argument("text", nargs="+", help="the text ('-' reads standard input)")
    _target_options(p, name_option=True)
    p.set_defaults(_memory_cmd="add")

    p = subparsers.add_parser("ingest", parents=[common], help="ingest a file or folder (md, txt, csv, json, docx, xlsx, pptx, ...)")
    p.add_argument("path")
    _target_options(p, name_option=True)
    p.add_argument("--format", choices=["auto", "text", "chat"], default=None, help=argparse.SUPPRESS)
    p.set_defaults(_memory_cmd="ingest")

    p = subparsers.add_parser("search", parents=[common], help="search the memory you may read")
    p.add_argument("query", nargs="+")
    p.add_argument("-k", "--limit", type=int, default=8, help="maximum hits (default 8)")
    p.add_argument("--type", dest="types", action="append", choices=MEMORY_TYPES, default=None,
                   help="only this memory type (repeatable)")
    p.add_argument("--project", dest="project_id", default=None, help="also search this project's devlog")
    p.add_argument("--no-private", action="store_true", help="only the shared space")
    p.set_defaults(_memory_cmd="search")

    p = subparsers.add_parser("context", parents=[common], help="print the compact session-start bundle")
    p.add_argument("--max-chars", type=int, default=4000)
    p.add_argument("--project", dest="project_id", default=None, help="include this project's devlog (if readable)")
    p.set_defaults(_memory_cmd="context")

    p = subparsers.add_parser("forget", parents=[common], help="forget one source (tombstone; raw bytes are kept)")
    p.add_argument("source_id", help="source id, unique id prefix, or mem:// reference")
    p.set_defaults(_memory_cmd="forget")

    p = subparsers.add_parser("devlog", parents=[common], help="record a development-log entry for a project")
    p.add_argument("text", nargs="+")
    p.add_argument("--project", dest="project_id", required=True, help="project id")
    p.set_defaults(_memory_cmd="devlog")

    # NOT named "status": that command name is pinned as unregistered by the PKG-1/PKG-3 release-layer tests.
    p = subparsers.add_parser("memory-status", parents=[common],
                              help="show memory counts, this profile's grants and projection drift")
    p.set_defaults(_memory_cmd="memory_status")

    p = subparsers.add_parser("import-notes", parents=[common],
                              help="migrate the retired notes store (notes-v1.jsonl) into memory sources (idempotent)")
    p.add_argument("--path", default=None, help="notes file (default: <data root>/data/notes/notes-v1.jsonl)")
    _target_options(p, name_option=False)
    p.set_defaults(_memory_cmd="import_notes")

    p = subparsers.add_parser("serve", parents=[common],
                              help="run the MCP server pinned to --profile (needs an MCP server with --profile-id)")
    p.set_defaults(_memory_cmd="serve")

    agents = subparsers.add_parser("agents", help="operator commands: register agents and approve their access")
    sub = agents.add_subparsers(dest="agents_command", required=True)

    p = sub.add_parser("add", parents=[common], help="register agents (READ on ks-shared; private write only)")
    p.add_argument("profiles", nargs="+")
    p.set_defaults(_memory_cmd="agents_add")

    for name, help_text in (("grant-write", "OPERATOR ACTION: approve an agent writing to a shared space/project"),
                            ("grant-read", "grant an agent READ on a project (or another space)")):
        p = sub.add_parser(name, parents=[common], help=help_text)
        p.add_argument("profile")
        group = p.add_mutually_exclusive_group(required=True)
        group.add_argument("--space", default=None, help=f"knowledge space (normally {SHARED_SPACE})")
        group.add_argument("--project", default=None, help="project id")
        if name == "grant-write":
            p.add_argument("--yes", action="store_true", help="confirm this operator approval without prompting")
            p.add_argument("--basis", default=None, help="why this was approved (recorded in the audit event)")
        p.set_defaults(_memory_cmd=name.replace("-", "_").replace("grant_", "agents_grant_"))

    p = sub.add_parser("revoke", parents=[common], help="revoke an agent's grants (all, or filtered)")
    p.add_argument("profile")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--space", default=None)
    group.add_argument("--project", default=None)
    op = p.add_mutually_exclusive_group()
    op.add_argument("--read", dest="operation", action="store_const", const="READ")
    op.add_argument("--write", dest="operation", action="store_const", const="WRITE")
    p.set_defaults(_memory_cmd="agents_revoke", operation=None)

    p = sub.add_parser("list", parents=[common], help="list agents and what they may do")
    p.set_defaults(_memory_cmd="agents_list")


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------
def _emit(obj: Any) -> None:
    print(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")))


def _err(message: str) -> None:
    print(f"zero-mem: {message}", file=sys.stderr)


def _reason_text(reason: Optional[str]) -> str:
    if not reason:
        return "unspecified"
    return _REASONS.get(reason, reason)


def _hint_for_denied(profile: str, scope: Optional[str], project_id: Optional[str]) -> str:
    if scope == "shared":
        return f"ask the operator to run: zero-mem agents grant-write {profile} --space {SHARED_SPACE}"
    if scope == "project" and project_id:
        return f"ask the operator to run: zero-mem agents grant-write {profile} --project {project_id}"
    return "ask the operator to review this agent's grants: zero-mem agents list"


def _open(args) -> Memory:
    return Memory.open(args.profile, channel="cli")


def _wants_json(args) -> bool:
    return bool(getattr(args, "json", False))


def _explain(result, args, *, scope: Optional[str] = None, project_id: Optional[str] = None) -> None:
    """Human error line(s) for a non-ok write/forget result (stderr)."""
    status = result.status
    if status == "denied":
        _err(f"denied: profile '{args.profile}' may not do this ({result.reason}); "
             + _hint_for_denied(args.profile, scope or getattr(result, "scope", None),
                                project_id or getattr(result, "project_id", None)))
    elif status == "rejected_secret":
        rules = ", ".join(getattr(result, "rule_ids", ()) or ())
        _err("rejected: a credential-like value was detected" + (f" (rule: {rules})" if rules else "")
             + ". Nothing was stored. Remove the secret and try again.")
    elif status == "rejected_content":
        _err(f"rejected: {_reason_text(result.reason)}. Nothing was stored.")
    elif status == "not_found":
        _err("not found: no such source is visible to this profile (use search to list ids)")
    elif status == "ambiguous":
        _err("ambiguous: several sources match; use one of these ids: " + ", ".join(result.candidates))
    elif status == "invalid":
        _err(f"invalid input: {_reason_text(result.reason)}")
    else:
        _err(f"{status}: {_reason_text(result.reason)}")


def _read_text(parts: list[str]) -> str:
    if parts == ["-"]:
        return sys.stdin.read(MAX_TEXT_BYTES + 1)
    return " ".join(parts)


def _stdin_is_tty() -> bool:
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


# ---------------------------------------------------------------------------------------------
# memory commands
# ---------------------------------------------------------------------------------------------
def _cmd_add(args, *, devlog: bool = False) -> int:
    memory = _open(args)
    try:
        text = _read_text(args.text)
        if devlog:
            result = memory.add(text, "devlog", scope="project", project_id=args.project_id)
        else:
            result = memory.add(text, args.memory_type or "fact", name=args.name, scope=args.scope,
                                project_id=args.project_id)
    finally:
        memory.close()
    if _wants_json(args):
        _emit(result.as_dict())
    elif result.ok:
        units = f", {result.units} unit(s)" if result.units is not None else ""
        print(f"{result.status}  {result.external_ref}  ({result.scope}{units})")
    else:
        _explain(result, args, scope=result.scope, project_id=args.project_id)
    return _STATUS_EXIT.get(result.status, EXIT_ERROR)


def _summary_line(report) -> str:
    c = report.counts
    parts = [f"{c.get('created', 0)} created", f"{c.get('updated', 0)} updated", f"{c.get('unchanged', 0)} unchanged"]
    rejected = c.get("rejected_secret", 0) + c.get("rejected_content", 0) + c.get("invalid", 0) + c.get("error", 0)
    if rejected:
        parts.append(f"{rejected} rejected")
    if c.get("skipped"):
        parts.append(f"{c['skipped']} skipped")
    return ", ".join(parts)


def _print_report(report, args, *, label: str) -> int:
    if _wants_json(args):
        _emit(report.as_dict())
        return _STATUS_EXIT.get(report.status, EXIT_ERROR)
    if report.status in ("denied", "invalid", "error"):
        _explain(SimpleNamespace(status=report.status, reason=report.reason, rule_ids=(), candidates=()), args,
                 scope=getattr(args, "scope", None), project_id=getattr(args, "project_id", None))
        return _STATUS_EXIT[report.status]
    print(f"{label} {len(report.files)} item(s): {_summary_line(report)}")
    for res in report.files:
        if res.status in ("rejected_secret", "rejected_content", "invalid", "error", "denied"):
            why = "a credential-like value was detected" if res.status == "rejected_secret" else _reason_text(res.reason)
            print(f"  rejected {res.name or res.external_ref}: {why}")
    for skip in report.skipped:
        print(f"  skipped  {skip['name']}: {skip['reason']}")
    return _STATUS_EXIT.get(report.status, EXIT_ERROR)


def _cmd_ingest(args) -> int:
    if args.format is not None:
        _err("note: --format is ignored (file formats are detected automatically)")
    memory = _open(args)
    try:
        report = memory.ingest(Path(args.path), memory_type=args.memory_type or "fact", scope=args.scope,
                               project_id=args.project_id, name=args.name)
    finally:
        memory.close()
    if report.status == "invalid" and report.reason == "path_not_found" and not _wants_json(args):
        _err(f"not found: {args.path}")
        return EXIT_ERROR
    return _print_report(report, args, label="ingested")


def _clip_line(text: str, width: int = 240) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def _cmd_search(args) -> int:
    memory = _open(args)
    try:
        result = memory.recall(" ".join(args.query), memory_types=args.types, limit=args.limit,
                               include_private=not args.no_private, project_id=args.project_id)
    finally:
        memory.close()
    if _wants_json(args):
        _emit(result.as_dict())
        return _STATUS_EXIT.get(result.status, EXIT_ERROR)
    if result.status == "invalid":
        _err(f"invalid input: {_reason_text(result.reason)}")
        return EXIT_ERROR
    if result.status in ("denied", "error"):
        _err(f"{result.status}: {_reason_text(result.reason)}")
        return _STATUS_EXIT[result.status]
    if not result.hits:
        print("no results")
        return EXIT_OK
    for index, hit in enumerate(result.hits, start=1):
        print(f"{index}. [{hit.memory_type or '-'} · {hit.scope} · {hit.score:.2f}] {hit.external_ref or hit.source_id}")
        print(f"   {_clip_line(hit.text)}")
    return EXIT_OK


def _cmd_context(args) -> int:
    memory = _open(args)
    try:
        bundle = memory.context(max_chars=args.max_chars, project_id=args.project_id)
    finally:
        memory.close()
    if _wants_json(args):
        _emit(bundle.as_dict())
        return _STATUS_EXIT.get(bundle.status, EXIT_ERROR)
    if bundle.status == "invalid":
        _err(f"invalid input: {_reason_text(bundle.reason)}")
        return EXIT_ERROR
    if bundle.status in ("error",):
        _err(f"error: {_reason_text(bundle.reason)}")
        return EXIT_ERROR
    if not bundle.text:
        _err("context is empty (add persona, workflow, skill or devlog entries first)")
        return EXIT_OK
    print(bundle.text)
    return EXIT_OK


def _cmd_forget(args) -> int:
    memory = _open(args)
    try:
        result = memory.forget(args.source_id)
    finally:
        memory.close()
    if _wants_json(args):
        _emit(result.as_dict())
    elif result.ok:
        print(f"{result.status}  {result.external_ref or result.source_id}  (raw bytes are kept; it will not be recalled)")
    else:
        _explain(result, args)
    return _STATUS_EXIT.get(result.status, EXIT_ERROR)


def _cmd_status(args) -> int:
    memory = _open(args)
    try:
        status = memory.status()
    finally:
        memory.close()
    if _wants_json(args):
        _emit(status)
        return EXIT_OK
    s = status["sources"]
    print(f"profile      {status['profile_id']}")
    print(f"data root    {status['data_root']}")
    print(f"sources      {s['total']} ({s['own']} yours, {s['forgotten']} forgotten); units {status['units']}")
    print("by type      " + (", ".join(f"{k} {v}" for k, v in s["by_type"].items()) or "-"))
    print(f"shared space {status['shared_space']}: read={'yes' if status['can_read_shared'] else 'no'}, "
          f"write={'yes' if status['can_write_shared'] else 'no'}")
    if status["needs_rebuild"]:
        print(f"WARNING      {status['drifted_sources']} source(s) are not projected: run zero-mem upgrade")
    return EXIT_OK


def _cmd_import_notes(args) -> int:
    from .notes_import import NotesImportError, import_notes

    memory = _open(args)
    try:
        try:
            report = import_notes(memory, Path(args.path) if args.path else None,
                                  memory_type=args.memory_type or "fact", scope=args.scope,
                                  project_id=args.project_id)
        except NotesImportError as exc:
            _err(f"{exc} (expected {Path('data/notes/notes-v1.jsonl')} under the data root; pass --path to point elsewhere)")
            return EXIT_ERROR
    finally:
        memory.close()
    return _print_report(report, args, label="imported")


# ---------------------------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------------------------
_MCP_MODULE = "src.integration.m6.mcp_server"


def _mcp_supports_profile_pin() -> bool:
    """True when the installed MCP server module can pin identity (``--profile-id``)."""
    import importlib.util

    try:
        spec = importlib.util.find_spec(_MCP_MODULE)
        if spec is None or not spec.origin:
            return False
        return "--profile-id" in Path(spec.origin).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False


def _cmd_serve(args, exec_fn: Callable = None) -> int:
    from .memory import valid_id

    if not valid_id(args.profile):
        _err("invalid profile id")
        return EXIT_ERROR
    if not _mcp_supports_profile_pin():
        _err("this build's MCP server cannot pin an agent identity yet (it has no --profile-id option), and an unpinned "
             "server would trust whatever profile a caller claims. Refusing to start. Track: DEF-062 / task T6.")
        return EXIT_ERROR
    try:
        layout = Layout.resolve(None)
        layout.ensure()
    except LayoutError as exc:
        _err(str(exc))
        return EXIT_ERROR
    argv = [sys.executable, "-m", _MCP_MODULE, "--store-path", str(layout.derived_db), "--profile-id", args.profile]
    (exec_fn or os.execv)(sys.executable, argv)
    return EXIT_OK  # only reached when exec is stubbed


# ---------------------------------------------------------------------------------------------
# agents (operator)
# ---------------------------------------------------------------------------------------------
def _provisioner() -> Provisioner:
    layout = Layout.resolve(None)
    layout.ensure()
    return Provisioner(layout)


def _cmd_agents_add(args) -> int:
    prov = _provisioner()
    rows = [prov.add_agent(profile) for profile in args.profiles]
    if _wants_json(args):
        _emit({"agents": rows})
    else:
        for row in rows:
            print(f"{row['status']}  {row['profile']}  (read {SHARED_SPACE}; private write only)")
    return EXIT_OK


def _confirm(args, prompt: str) -> bool:
    if getattr(args, "yes", False):
        return True
    if not _stdin_is_tty():
        _err("this is an operator approval and needs explicit confirmation: re-run with --yes "
             "(or run it from a terminal and answer the prompt)")
        return False
    try:
        answer = input(f"{prompt} [y/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() in ("y", "yes"):
        return True
    _err("not confirmed; nothing was granted")
    return False


def _cmd_agents_grant_write(args) -> int:
    target = f"space '{args.space}'" if args.space else f"project '{args.project}'"
    prov = _provisioner()
    if not _confirm(args, f"Approve '{args.profile}' writing to {target}? (cross-profile write, audited)"):
        return EXIT_ERROR
    result = prov.grant_write(args.profile, space=args.space, project=args.project, basis=args.basis)
    if _wants_json(args):
        _emit(result)
    else:
        print(f"{result['status']}  {args.profile} may write to {target}  (approval {result['approval_ref']})")
    return EXIT_OK


def _cmd_agents_grant_read(args) -> int:
    prov = _provisioner()
    result = prov.grant_read(args.profile, space=args.space, project=args.project)
    if _wants_json(args):
        _emit(result)
    else:
        print(f"{result['status']}  {args.profile} may read {result['target_type']} '{result['target_id']}'")
    return EXIT_OK


def _cmd_agents_revoke(args) -> int:
    prov = _provisioner()
    result = prov.revoke(args.profile, space=args.space, project=args.project, operation=args.operation)
    if _wants_json(args):
        _emit(result)
    elif result["revoked"]:
        for row in result["revoked"]:
            print(f"revoked  {row['operation']} {row['target_type']} '{row['target_id']}' for {args.profile}")
    else:
        _err(f"nothing to revoke for '{args.profile}' with those filters")
    return EXIT_OK if result["revoked"] else EXIT_NOT_FOUND


def _cmd_agents_list(args) -> int:
    prov = _provisioner()
    rows = prov.list_agents()
    if _wants_json(args):
        _emit({"agents": rows})
        return EXIT_OK
    if not rows:
        print("no agents registered (zero-mem agents add <profile>)")
        return EXIT_OK
    for row in rows:
        flags = f"read={'yes' if row['can_read_shared'] else 'no'} write={'yes' if row['can_write_shared'] else 'no'}"
        extra = [f"{g['operation'].lower()} {g['target_type']}:{g['target_id']}" for g in row["grants"]
                 if not (g["target_type"] == "knowledge_space" and g["target_id"] == SHARED_SPACE)]
        print(f"{row['profile']:<20} {SHARED_SPACE}: {flags}" + (f"  also: {', '.join(extra)}" if extra else ""))
    return EXIT_OK


_HANDLERS = {
    "add": _cmd_add,
    "devlog": lambda args: _cmd_add(args, devlog=True),
    "ingest": _cmd_ingest,
    "search": _cmd_search,
    "context": _cmd_context,
    "forget": _cmd_forget,
    "memory_status": _cmd_status,
    "import_notes": _cmd_import_notes,
    "serve": _cmd_serve,
    "agents_add": _cmd_agents_add,
    "agents_grant_write": _cmd_agents_grant_write,
    "agents_grant_read": _cmd_agents_grant_read,
    "agents_revoke": _cmd_agents_revoke,
    "agents_list": _cmd_agents_list,
}


def dispatch(args) -> Optional[int]:
    """Run the memory command selected by ``args`` (``None`` when ``args`` names another command)."""
    name = getattr(args, "_memory_cmd", None)
    if name is None:
        return None
    try:
        return _HANDLERS[name](args)
    except (MemoryConfigError, LayoutError) as exc:
        _err(str(exc))
        return EXIT_ERROR
    except ProvisioningError as exc:
        _err(exc.message)
        return EXIT_ERROR
    except KeyboardInterrupt:
        _err("interrupted")
        return 130
    except BrokenPipeError:
        return EXIT_OK
    except Exception as exc:  # never a traceback for an operator
        _err(f"unexpected error ({type(exc).__name__}); run zero-mem doctor")
        return EXIT_ERROR


__all__ = [
    "EXIT_DENIED", "EXIT_ERROR", "EXIT_NOT_FOUND", "EXIT_OK", "EXIT_PARTIAL", "EXIT_REJECTED",
    "add_global_options", "add_memory_parsers", "default_profile", "dispatch",
]
