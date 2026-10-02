"""CLI for named memories and agent linking: ``zero-mem memory ...`` and ``zero-mem link ...``.

All logic lives in :mod:`zero_mem.workspaces` (registry, selection) and :mod:`zero_mem.commands_mcp` (registration
generators); this module is argument parsing and printing. Exit codes follow ``zero_mem.commands_memory``:
0 ok, 2 invalid usage or setup error, 5 not found.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional

from . import commands_mcp, paths, workspaces
from .provisioning import ProvisioningError, valid_id
from .workspaces import DEFAULT_NAME, WorkspaceError

EXIT_OK, EXIT_ERROR, EXIT_NOT_FOUND = 0, 2, 5
RUNNING_NOTE = ("agents that are already running keep the memory they were started with; restart them (or re-run "
                "`zero-mem link`) to move them")
#: Clients whose own CLI `link --apply` may run. Only the one whose end-to-end flow was exercised with a real model.
APPLY_CLIENTS = ("claude-code",)


def _err(message: str) -> None:
    print(f"zero-mem: {message}", file=sys.stderr)


def _json(args) -> bool:
    return bool(getattr(args, "json", False))


def _emit(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True))


# ---------------------------------------------------------------------------------------------
# parsers
# ---------------------------------------------------------------------------------------------
def add_memory_option(parser: argparse.ArgumentParser) -> None:
    """The global ``--memory NAME`` option (also accepted after the subcommand where a command shares ``_common``)."""
    parser.add_argument("--memory", dest="memory_name", default=None, metavar="NAME",
                        help="use the named memory (see `zero-mem memory list`); $ZERO_MEM_MEMORY is the fallback. "
                             "Precedence: $ZERO_MEM_DATA_ROOT > --memory > $ZERO_MEM_MEMORY > `memory use` > XDG default")


def _json_parent() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output")
    return common


def add_workspace_parsers(subparsers) -> None:
    jp = _json_parent()
    memory = subparsers.add_parser("memory", help="manage several named memories on this machine")
    sub = memory.add_subparsers(dest="memory_command", required=True)

    p = sub.add_parser("create", parents=[jp], help="create a new named memory (a data root registered under NAME)")
    p.add_argument("name")
    p.add_argument("--path", default=None, metavar="DIR", help="data root (default: <default data root's parent>/zero-mem-memories/NAME)")
    p.add_argument("--description", default="", metavar="TEXT")
    p.set_defaults(_ws_cmd="create")

    p = sub.add_parser("list", parents=[jp], help="list memories: path, sources, agents, last write")
    p.set_defaults(_ws_cmd="list")

    p = sub.add_parser("use", parents=[jp], help="make NAME the default memory for later commands (stored in the registry)")
    p.add_argument("name")
    p.set_defaults(_ws_cmd="use")

    p = sub.add_parser("path", parents=[jp], help="print the data root of NAME")
    p.add_argument("name")
    p.set_defaults(_ws_cmd="path")

    p = sub.add_parser("remove", parents=[jp], help="unregister NAME (its data stays unless --delete-data --yes)")
    p.add_argument("name")
    p.add_argument("--delete-data", action="store_true", help="also delete the memory's files (needs --yes)")
    p.add_argument("--yes", action="store_true", help="confirm --delete-data")
    p.set_defaults(_ws_cmd="remove")

    p = sub.add_parser("rename", parents=[jp], help="rename a memory (its data does not move; agents pinned to its path keep working)")
    p.add_argument("old")
    p.add_argument("new")
    p.set_defaults(_ws_cmd="rename")

    link = subparsers.add_parser(
        "link", parents=[jp], help="register an agent client (claude-code, codex, hermes, openclaw) with a named memory")
    link.add_argument("agent", nargs="?", choices=commands_mcp.AGENTS, default=None)
    link.add_argument("--memory", dest="memory_name", default=argparse.SUPPRESS, metavar="NAME",
                      help="the memory to bind the agent to")
    link.add_argument("--profile", dest="link_profile", default=None, metavar="P", help="agent profile (default: the agent name)")
    link.add_argument("--name", default=None, help="server name in the client (default zero-mem-<memory>)")
    link.add_argument("--enable-write", action="store_true", default=False,
                      help="expose memory_add / memory_ingest / memory_forget (shared writes still need `agents grant-write`)")
    link.add_argument("--enable-propose", action="store_true", default=False, help="expose memory_propose")
    link.add_argument("--allow-root", action="append", default=None, metavar="DIR",
                      help="folder memory_ingest may read (repeatable, needs --enable-write)")
    mode = link.add_mutually_exclusive_group()
    mode.add_argument("--print", dest="link_apply", action="store_false", default=False, help="print the registration (default)")
    mode.add_argument("--apply", dest="link_apply", action="store_true", help="run the client's own CLI (claude-code only; needs --yes)")
    link.add_argument("--yes", action="store_true", help="confirm --apply")
    link.add_argument("--list", dest="link_list", action="store_true", help="show the agent profiles of each memory")
    link.add_argument("--remove", dest="link_remove", default=None, metavar="AGENT",
                      help="revoke this agent profile's grants on --memory (the data stays)")
    link.set_defaults(_ws_cmd="link")


# ---------------------------------------------------------------------------------------------
# memory commands
# ---------------------------------------------------------------------------------------------
def _cmd_create(args) -> int:
    entry = workspaces.create_memory(args.name, args.path, args.description)
    if _json(args):
        _emit({"status": "created", "name": entry.name, "path": entry.path})
    else:
        print(f"created  {entry.name}  {entry.path}")
        print(f"next: zero-mem --memory {entry.name} add \"...\"   |   zero-mem link claude-code --memory {entry.name}")
    return EXIT_OK


def _cmd_list(args) -> int:
    rows = workspaces.list_memories()
    registry_file = workspaces.registry_path()
    if _json(args):
        _emit({"registry": registry_file.as_posix(), "memories": rows})
        return EXIT_OK
    for row in rows:
        mark = "*" if row["current"] else " "
        extra = "" if row["status"] == "ok" else f"  [{row['status']}]"
        print(f"{mark} {row['name']:<20} sources={row['sources'] if row['sources'] is not None else '-'}  "
              f"agents={row['agents'] if row['agents'] is not None else '-'}  last write={row['last_write'] or '-'}{extra}")
        print(f"    {row['path']}" + (f"  - {row['description']}" if row["description"] else ""))
    sel = workspaces.active_selection()
    if sel is not None:
        print(f"current: {sel.name} (from {sel.source}); `*` marks it. registry: {registry_file.as_posix()}")
    return EXIT_OK


def _cmd_use(args) -> int:
    entry = workspaces.use_memory(args.name)
    notes = []
    if os.environ.get(paths.DATA_ROOT_ENV):
        notes.append("ZERO_MEM_DATA_ROOT is set in this shell and still takes precedence")
    if os.environ.get(workspaces.MEMORY_ENV):
        notes.append("ZERO_MEM_MEMORY is set in this shell and takes precedence over this default")
    if _json(args):
        _emit({"status": "default_set", "name": entry.name, "path": entry.path, "notes": notes + [RUNNING_NOTE]})
    else:
        print(f"default memory is now '{entry.name}'  {entry.path}")
        for note in notes:
            print(f"note: {note}")
        print(f"note: {RUNNING_NOTE}.")
    return EXIT_OK


def _cmd_path(args) -> int:
    print(workspaces.get_entry(args.name).path)
    return EXIT_OK


def _cmd_remove(args) -> int:
    result = workspaces.remove_memory(args.name, delete_data=args.delete_data, yes=args.yes)
    if _json(args):
        _emit({"status": "removed", **result})
    elif result["deleted"]:
        print(f"removed  {result['name']}  and DELETED its data at {result['path']}")
    else:
        print(f"unregistered  {result['name']}  (data kept at {result['path']})")
    return EXIT_OK


def _cmd_rename(args) -> int:
    entry = workspaces.rename_memory(args.old, args.new)
    if _json(args):
        _emit({"status": "renamed", "old": args.old, "name": entry.name, "path": entry.path})
    else:
        print(f"renamed  {args.old} -> {entry.name}  ({entry.path}; the data did not move)")
    return EXIT_OK


# ---------------------------------------------------------------------------------------------
# link
# ---------------------------------------------------------------------------------------------
def _link_memory_name(args) -> str:
    given = getattr(args, "memory_name", None)
    if given:
        return given
    if (os.environ.get(workspaces.MEMORY_ENV) or "").strip():
        return os.environ[workspaces.MEMORY_ENV].strip()
    return workspaces.select(None).name


def _claude_argv(reg: Dict[str, Any]) -> List[str]:
    env_flags = [part for key, value in reg["env"].items() for part in ("-e", f"{key}={value}")]
    return ["claude", "mcp", "add", reg["server_name"], "-s", "user", *env_flags, "--", reg["command"], *reg["args"]]


def _agent_rows(entry: workspaces.MemoryEntry) -> List[Dict[str, Any]]:
    if not entry.root.is_dir() or not (entry.root / paths.DERIVED_DB_RELATIVE).is_file():
        return []
    with workspaces.provisioner_for(entry, create=False) as prov:
        return [{"profile": row["profile"], "read_shared": row["can_read_shared"], "write_shared": row["can_write_shared"],
                 "grants": len(row["grants"])} for row in prov.list_agents() if row["registered"]]


def _link_list(args) -> int:
    reg = workspaces.read_registry()
    wanted = getattr(args, 'memory_name', None)
    entries = [workspaces.get_entry(DEFAULT_NAME)] + [reg.memories[n] for n in sorted(reg.memories)]
    if wanted:
        entries = [workspaces.get_entry(wanted, reg)]
    out = [{"memory": e.name, "path": e.path, "profiles": _agent_rows(e)} for e in entries]
    if _json(args):
        _emit({"memories": out})
        return EXIT_OK
    for item in out:
        print(f"{item['memory']}  ({item['path']})")
        if not item["profiles"]:
            print("    no agent profiles")
        for row in item["profiles"]:
            print(f"    {row['profile']:<20} read ks-shared={'yes' if row['read_shared'] else 'no'} "
                  f"write ks-shared={'yes' if row['write_shared'] else 'no'}")
    return EXIT_OK


def _link_remove(args) -> int:
    profile = args.link_remove
    if not valid_id(profile):
        _err("invalid profile id (letters, digits, . _ -; at most 64 characters)")
        return EXIT_ERROR
    if not getattr(args, 'memory_name', None):
        _err("--remove needs --memory NAME")
        return EXIT_ERROR
    entry = workspaces.get_entry(getattr(args, 'memory_name', None))
    if not entry.root.is_dir():
        _err("that memory's data root does not exist")
        return EXIT_NOT_FOUND
    with workspaces.provisioner_for(entry, create=False) as prov:
        result = prov.revoke(profile)
    server = args.name or workspaces.link_server_name(entry.name)
    if _json(args):
        _emit({"memory": entry.name, "profile": profile, "revoked": result["revoked"],
               "data_kept": True})
    elif result["revoked"]:
        print(f"revoked {len(result['revoked'])} grant(s) of '{profile}' on memory '{entry.name}'; the data is kept")
        print(f"also remove the server from the client, e.g. `claude mcp remove {server}` ({RUNNING_NOTE}).")
    else:
        _err(f"nothing to revoke for '{profile}' on memory '{entry.name}'")
    return EXIT_OK if result["revoked"] else EXIT_NOT_FOUND


def _cmd_link(args) -> int:
    if args.link_list:
        return _link_list(args)
    if args.link_remove:
        return _link_remove(args)
    if not args.agent:
        _err("link needs an AGENT (claude-code, codex, hermes, openclaw), or --list, or --remove AGENT")
        return EXIT_ERROR
    entry = workspaces.get_entry(_link_memory_name(args))
    profile = args.link_profile or args.agent
    if not valid_id(profile):
        _err("invalid profile id (letters, digits, . _ -; at most 64 characters)")
        return EXIT_ERROR
    name = args.name or workspaces.link_server_name(entry.name)
    if not commands_mcp._SERVER_NAME_RE.fullmatch(name):
        _err("invalid --name (letters, digits, _ and -; at most 40 characters)")
        return EXIT_ERROR
    try:
        roots = commands_mcp._absolute_roots(args.allow_root, args.enable_write)
    except commands_mcp.UsageError as exc:
        _err(str(exc))
        return EXIT_ERROR
    if args.link_apply:  # refuse BEFORE any state changes
        if args.agent not in APPLY_CLIENTS:
            _err(f"--apply is only available for {', '.join(APPLY_CLIENTS)}; run the printed {args.agent} command yourself "
                 f"(zero-mem never edits a client's config files). Use --print.")
            return EXIT_ERROR
        if not args.yes:
            _err("--apply runs the client's own CLI and changes its configuration: re-run with --apply --yes "
                 "(or use --print and run the command yourself)")
            return EXIT_ERROR
        if shutil.which("claude") is None:
            _err("the 'claude' CLI is not on PATH; use --print and run the command where Claude Code is installed")
            return EXIT_ERROR
    named = entry.name != DEFAULT_NAME
    with workspaces.provisioner_for(entry, create=True) as prov:
        row = prov.add_agent(profile)
        with workspaces.using_memory(entry.root, named):
            env = commands_mcp._pinned_env()
            reg = commands_mcp.build_registration(args.agent, profile, name=name, enable_write=args.enable_write,
                                                  allow_roots=roots, enable_propose=args.enable_propose, env=env)
    reg["memory"] = {"name": entry.name, "path": entry.path, "data_root_env": reg["env"][paths.DATA_ROOT_ENV]}
    reg["profile_status"] = row["status"]
    reg["running_agents_note"] = RUNNING_NOTE
    if args.link_apply:
        argv = _claude_argv(reg)
        print("running: " + commands_mcp._shell(argv))
        try:
            code = subprocess.run(argv, check=False).returncode
        except OSError as exc:
            _err(f"could not run claude ({type(exc).__name__})")
            return EXIT_ERROR
        if code != 0:
            _err(f"`claude mcp add` exited {code} (a server named '{name}' may already be registered: "
                 f"`claude mcp remove {name}`, or pick another --name)")
            return EXIT_ERROR
        print(f"registered '{name}' with Claude Code on memory '{entry.name}'. {RUNNING_NOTE}.")
        return EXIT_OK
    if _json(args):
        _emit(reg)
        return EXIT_OK
    print(f"# memory '{entry.name}' at {entry.path}")
    print(f"# profile '{profile}': {row['status']} on this memory (read ks-shared, private write)")
    print(f"# {RUNNING_NOTE}.")
    print(commands_mcp.render_text(reg))
    if args.agent in APPLY_CLIENTS:
        print(f"\n# or let zero-mem run it for you: zero-mem link {args.agent} --memory {entry.name} --apply --yes")
    return EXIT_OK


_HANDLERS = {"create": _cmd_create, "list": _cmd_list, "use": _cmd_use, "path": _cmd_path, "remove": _cmd_remove,
             "rename": _cmd_rename, "link": _cmd_link}


def dispatch(args) -> Optional[int]:
    name = getattr(args, "_ws_cmd", None)
    if name is None:
        return None
    try:
        return _HANDLERS[name](args)
    except WorkspaceError as exc:
        _err(exc.message)
        return EXIT_NOT_FOUND if exc.kind == "not_found" else EXIT_ERROR
    except ProvisioningError as exc:
        _err(exc.message)
        return EXIT_ERROR
    except paths.ConfigurationError as exc:
        _err(str(exc))
        return EXIT_ERROR
    except KeyboardInterrupt:
        _err("interrupted")
        return 130
    except BrokenPipeError:
        return EXIT_OK
    except Exception as exc:  # never a traceback for an operator
        _err(f"unexpected error ({type(exc).__name__}); run zero-mem doctor")
        return EXIT_ERROR


__all__ = ["add_memory_option", "add_workspace_parsers", "dispatch"]
