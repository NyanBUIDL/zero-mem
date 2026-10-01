"""CLI for the MCP integration: ``zero-mem serve`` and ``zero-mem mcp-config``.

``serve`` replaces this process (``os.execv``) with the pinned stdio MCP server
(``python -m src.integration.m6.mcp_server --store-path <db> --profile-id <profile> --enable-memory --tools <set>
[--enable-write] [--allow-root DIR]...``), so an agent client that registers ``serve`` talks to exactly one
agent's identity. The default tool set is ``--tools memory``: ONLY ``memory_recall`` / ``memory_context`` (token cost
is the product goal: the 11 legacy M6 read tools are ~17 KB of ``tools/list``); ``--tools all`` adds the legacy
tools. The write tools (``memory_add`` / ``memory_ingest`` / ``memory_forget``) exist only with ``--enable-write``.

``mcp-config`` prints, without touching any state, the registration for one agent client (Claude Code, Codex,
Hermes, OpenClaw): the absolute interpreter, the ``serve`` arguments and the environment that pins the data root.

Exit codes: 0 ok; 2 invalid usage, input or setup error (same convention as ``zero_mem.commands_memory``).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import textwrap
from typing import Any, Callable, Dict, List, Optional

from . import paths
from .memory_bootstrap import ensure_layout
from .memory_layout import Layout, LayoutError
from .provisioning import SHARED_SPACE, valid_id

EXIT_OK, EXIT_ERROR = 0, 2

MCP_MODULE = "src.integration.m6.mcp_server"
AGENTS = ("claude-code", "codex", "hermes", "openclaw")
DEFAULT_SERVER_NAME = "zero-mem"
_SERVER_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
#: Environment variables that decide where zero-mem keeps its state; pinned into the registration when they matter.
_PINNED_XDG = ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME")

_CLIENT_LABEL = {
    "claude-code": "Claude Code",
    "codex": "Codex",
    "hermes": "Hermes",
    "openclaw": "OpenClaw",
}
#: What was actually exercised with each REAL client CLI on 2026-10-01 (docs/runbooks/agent-integration.md and
#: docs/defects/closures/T6b.md have the transcripts). Only Claude Code could drive a model; the others have no model
#: access in the sandbox, so for them a tool call by the model was NOT exercised.
_VERIFICATION_NOTES = {
    "claude-code": "verified with Claude Code 2.1.286: `claude mcp add` accepted this command, `claude mcp list` reported "
                   "the server Connected, and a scripted `claude -p` session had the model call the tools",
    "codex": "verified with Codex 0.159.3: `codex mcp get` parsed this config.toml block, `codex mcp add` wrote the same "
             "entry and the client completed initialize and tools/list; a model-driven tool call was NOT exercised",
    "hermes": "verified with hermes-agent 0.19.0: `hermes mcp add` saved this entry, `hermes mcp list` shows it enabled "
              "and `hermes mcp test` connected and discovered the tools; a model-driven tool call was NOT exercised",
    "openclaw": "verified with OpenClaw 2026.6.35: `openclaw mcp set` and `openclaw mcp add` accepted this entry, "
                "`openclaw mcp doctor` was ok and `openclaw mcp probe` listed the tools; a model-driven tool call was "
                "NOT exercised",
}
_MODEL_CALLS_VERIFIED = frozenset({"claude-code"})


# ---------------------------------------------------------------------------------------------
# parser wiring
# ---------------------------------------------------------------------------------------------
def _json_parent() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output")
    return common


def _profile_parent() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    # SUPPRESS: a value given before the subcommand survives; one given after it wins (as in commands_memory).
    common.add_argument("--profile", default=argparse.SUPPRESS, help="agent profile to run as")
    return common


TOOLS_CHOICES = ("memory", "all")


def _server_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--enable-write", action="store_true", default=False,
                   help="also expose memory_add, memory_ingest and memory_forget (shared and project writes still "
                        "need an operator-approved grant)")
    p.add_argument("--allow-root", action="append", default=None, metavar="DIR",
                   help="folder memory_ingest may read (repeatable, needs --enable-write; without one memory_ingest "
                        "is disabled)")
    p.add_argument("--tools", choices=TOOLS_CHOICES, default="memory",
                   help="tool set to list: 'memory' (default) = only the memory tools (memory_recall, memory_context "
                        "and with --enable-write memory_add, memory_ingest, memory_forget), the lowest token cost; "
                        "'all' = also the 11 legacy read-only M6 tools (corpus_search, memory_query, project_*, ...)")


def add_mcp_parsers(subparsers) -> None:
    p = subparsers.add_parser("serve", parents=[_json_parent(), _profile_parent()],
                              help="run the MCP server pinned to --profile (replaces this process)")
    _server_options(p)
    p.set_defaults(_mcp_cmd="serve")

    p = subparsers.add_parser("mcp-config", parents=[_json_parent()],
                              help="print the MCP registration snippet for an agent client")
    p.add_argument("--agent", required=True, choices=AGENTS, help="the client to register with")
    p.add_argument("--profile", dest="mcp_profile", default=None, metavar="PROFILE",
                   help="profile the server is pinned to (default: the agent name)")
    p.add_argument("--name", default=DEFAULT_SERVER_NAME, help=f"server name in the client (default {DEFAULT_SERVER_NAME})")
    _server_options(p)
    p.set_defaults(_mcp_cmd="mcp_config")


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------
class UsageError(Exception):
    """A bad option value; the message is shown to the operator (never a traceback)."""


def _err(message: str) -> None:
    print(f"zero-mem: {message}", file=sys.stderr)


def _absolute_roots(values: Optional[List[str]], enable_write: bool) -> List[str]:
    roots: List[str] = []
    for value in values or []:
        path = os.path.abspath(os.path.expanduser(value))
        if not os.path.isdir(path):
            raise UsageError("--allow-root must be an existing directory")
        if path == os.path.abspath(os.sep):
            raise UsageError("--allow-root may not be the file system root")
        if path not in roots:
            roots.append(path)
    if roots and not enable_write:
        raise UsageError("--allow-root only applies with --enable-write")
    return roots


def _server_argv(profile: str, enable_write: bool, roots: List[str], tools: str = "memory") -> List[str]:
    """The ``serve`` arguments a client registers. The memory-only default is implicit (shortest registration)."""
    argv = ["serve", "--profile", profile]
    if enable_write:
        argv.append("--enable-write")
    for root in roots:
        argv += ["--allow-root", root]
    if tools != "memory":
        argv += ["--tools", tools]
    return argv


# ---------------------------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------------------------
def run_serve(args, exec_fn: Optional[Callable] = None) -> int:
    if not valid_id(args.profile):
        _err("invalid profile id (letters, digits, . _ -; at most 64 characters)")
        return EXIT_ERROR
    try:
        roots = _absolute_roots(args.allow_root, args.enable_write)
        layout = Layout.resolve(None)
        ensure_layout(layout)  # race-safe: a client may start every agent's server at once
    except UsageError as exc:
        _err(str(exc))
        return EXIT_ERROR
    except LayoutError as exc:
        _err(str(exc))
        return EXIT_ERROR
    argv = [sys.executable, "-m", MCP_MODULE, "--store-path", str(layout.derived_db),
            "--profile-id", args.profile, "--enable-memory", "--tools", getattr(args, "tools", "memory")]
    if args.enable_write:
        argv.append("--enable-write")
    for root in roots:
        argv += ["--allow-root", root]
    (exec_fn or os.execv)(sys.executable, argv)
    return EXIT_OK  # only reached when exec is stubbed


# ---------------------------------------------------------------------------------------------
# mcp-config
# ---------------------------------------------------------------------------------------------
def _pinned_env() -> Dict[str, str]:
    """The environment that makes the client-launched server use THIS installation's data (never secrets)."""
    env = {"ZERO_MEM_DATA_ROOT": str(paths.data_root())}
    if paths.corpus_root_is_explicit():
        env["ZERO_MEM_CORPUS_ROOT"] = str(paths.corpus_root())
    for name in _PINNED_XDG:
        value = os.environ.get(name)
        if value:
            env[name] = value
    return env


def _toml_str(value: str) -> str:
    """A double-quoted string: valid as a TOML basic string AND as a YAML double-quoted scalar (same escapes)."""
    out = ['"']
    for ch in value:
        code = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif code < 0x20 or code == 0x7F:
            out.append(f"\\u{code:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _toml_array(values: List[str]) -> str:
    return "[" + ", ".join(_toml_str(v) for v in values) + "]"


def _toml_key(name: str) -> str:
    return name if re.fullmatch(r"[A-Za-z0-9_-]+", name) else _toml_str(name)


def _shell(tokens: List[str]) -> str:
    return " ".join(shlex.quote(t) for t in tokens)


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def _hermes_yaml(name: str, command: str, args: List[str], env: Dict[str, str]) -> str:
    """The ``mcp_servers`` block of ``$HERMES_HOME/config.yaml`` (same shape ``hermes mcp add`` writes)."""
    lines = ["mcp_servers:", f"  {_toml_str(name)}:", f"    command: {_toml_str(command)}",
             f"    args: {_toml_array(args)}", "    env:"]
    lines += [f"      {_toml_str(key)}: {_toml_str(value)}" for key, value in env.items()]
    lines.append("    enabled: true")
    return "\n".join(lines) + "\n"


def _snippets(agent: str, name: str, command: str, args: List[str], env: Dict[str, str]) -> Dict[str, str]:
    env_flags_short = [part for key, value in env.items() for part in ("-e", f"{key}={value}")]
    env_flags_long = [part for key, value in env.items() for part in ("--env", f"{key}={value}")]
    entry: Dict[str, Any] = {"command": command, "args": args, "env": env}
    if agent == "claude-code":
        return {
            "claude_mcp_add": _shell(["claude", "mcp", "add", name, "-s", "user", *env_flags_short, "--", command, *args]),
            "mcp_json": _json({"mcpServers": {name: {"type": "stdio", **entry}}}),
        }
    if agent == "codex":
        table = _toml_key(name)
        lines = [f"[mcp_servers.{table}]", f"command = {_toml_str(command)}", f"args = {_toml_array(args)}", "",
                 f"[mcp_servers.{table}.env]"]
        lines += [f"{_toml_key(key)} = {_toml_str(value)}" for key, value in env.items()]
        return {
            "config_toml": "\n".join(lines) + "\n",
            "codex_mcp_add": _shell(["codex", "mcp", "add", name, *env_flags_long, "--", command, *args]),
        }
    generic = {"mcp_json": _json({"mcpServers": {name: entry}})}
    if agent == "hermes":
        # `--args` must be the last option of `hermes mcp add`; `--env` takes KEY=VALUE words up to the next option
        return {
            "hermes_mcp_add": _shell(["hermes", "mcp", "add", name, "--command", command, "--env",
                                      *[f"{k}={v}" for k, v in env.items()], "--args", *args]),
            "config_yaml": _hermes_yaml(name, command, args, env),
            **generic,
        }
    # openclaw: `mcp set` takes the server entry itself (not wrapped in "mcpServers"); `--arg=VALUE` keeps a leading "-"
    return {
        "openclaw_mcp_set": _shell(["openclaw", "mcp", "set", name, json.dumps(entry, ensure_ascii=False)]),
        "openclaw_mcp_add": _shell(["openclaw", "mcp", "add", name, "--command", command,
                                    *[f"--arg={a}" for a in args], *env_flags_long]),
        **generic,
    }


def build_registration(agent: str, profile: str, *, name: str = DEFAULT_SERVER_NAME, enable_write: bool = False,
                       allow_roots: Optional[List[str]] = None, tools: str = "memory") -> Dict[str, Any]:
    """The registration of one agent client: pure data (the CLI prints it)."""
    roots = list(allow_roots or [])
    command = os.path.abspath(sys.executable)  # NOT realpath: a venv interpreter is a symlink that must stay one
    args = ["-m", "zero_mem.cli", *_server_argv(profile, enable_write, roots, tools)]
    env = _pinned_env()
    steps = [f"zero-mem agents add {profile}"]
    if enable_write:
        steps.append(f"zero-mem agents grant-write {profile} --space {SHARED_SPACE}"
                     "   # only if this agent may write shared memory (asks you to confirm)")
    return {
        "agent": agent,
        "profile": profile,
        "server_name": name,
        "command": command,
        "args": args,
        "env": env,
        "write_enabled": bool(enable_write),
        "tools": tools,
        "allow_roots": roots,
        "operator_steps": steps,
        "verified": {
            "server_command": True,         # exercised with the zero-mem stdio test client
            "client_config_format": True,   # accepted by the real client CLI (see verification_note for the version)
            "model_tool_calls": agent in _MODEL_CALLS_VERIFIED,
        },
        "verification_note": _VERIFICATION_NOTES[agent],
        "snippets": _snippets(agent, name, command, args, env),
    }


def _wrap(text: str, width: int = 112) -> List[str]:
    """``text`` as ``# ``-prefixed comment lines (valid in TOML, shell and as a YAML comment)."""
    return ["# " + line for line in textwrap.wrap(text, width, break_on_hyphens=False, break_long_words=False)]


def render_text(reg: Dict[str, Any]) -> str:
    agent, profile = reg["agent"], reg["profile"]
    label = _CLIENT_LABEL[agent]
    lines = [
        f"# zero-mem MCP registration for {label} (profile \"{profile}\", writes {'ENABLED' if reg['write_enabled'] else 'off'}, "
        f"tools: {'memory only' if reg['tools'] == 'memory' else 'memory + 11 legacy read tools'})",
        "#",
        "# 1. Operator, once, in your own terminal (do not give agents a shell that can run these):",
    ]
    lines += [f"#      {step}" for step in reg["operator_steps"]]
    lines += [
        "#",
        f"# 2. Register the server with {label}:",
        "#",
        *_wrap(f"Status: {reg['verification_note']}. See docs/runbooks/agent-integration.md for the verification matrix."),
    ]
    if reg["write_enabled"]:
        if reg["allow_roots"]:
            lines.append("# memory_ingest may read: " + ", ".join(reg["allow_roots"]))
        else:
            lines.append("# memory_ingest is disabled (no --allow-root given).")
    lines.append("")
    snippets = reg["snippets"]
    if agent == "claude-code":
        lines += ["# Claude Code: command line (user scope)", snippets["claude_mcp_add"], "",
                  "# Claude Code: or a .mcp.json (project scope) / `claude mcp add-json`", snippets["mcp_json"]]
    elif agent == "codex":
        lines += ["# Codex: append to ~/.codex/config.toml", snippets["config_toml"].rstrip("\n"), "",
                  "# Codex: or the equivalent command", f"# {snippets['codex_mcp_add']}"]
    elif agent == "hermes":
        lines += ["# Hermes: command line (it connects, lists the tools and asks which to enable)",
                  snippets["hermes_mcp_add"], "",
                  "# Hermes: or the equivalent block in $HERMES_HOME/config.yaml (default ~/.hermes/config.yaml)",
                  snippets["config_yaml"].rstrip("\n"), "",
                  "# Generic stdio entry (command / args / env) for any other MCP client", snippets["mcp_json"]]
    else:
        lines += ["# OpenClaw: command line (stores the entry under mcp.servers)", snippets["openclaw_mcp_set"], "",
                  "# OpenClaw: or add it from flags (probes the server first)", snippets["openclaw_mcp_add"], "",
                  "# Generic stdio entry (command / args / env) for any other MCP client", snippets["mcp_json"]]
    return "\n".join(lines)


def run_mcp_config(args) -> int:
    profile = args.mcp_profile or args.agent
    if not valid_id(profile):
        _err("invalid profile id (letters, digits, . _ -; at most 64 characters)")
        return EXIT_ERROR
    if not _SERVER_NAME_RE.fullmatch(args.name or ""):
        _err("invalid --name (letters, digits, _ and -; at most 40 characters)")
        return EXIT_ERROR
    try:
        roots = _absolute_roots(args.allow_root, args.enable_write)
        reg = build_registration(args.agent, profile, name=args.name, enable_write=args.enable_write, allow_roots=roots,
                                 tools=getattr(args, "tools", "memory"))
    except UsageError as exc:
        _err(str(exc))
        return EXIT_ERROR
    except paths.ConfigurationError as exc:
        _err(str(exc))
        return EXIT_ERROR
    print(_json(reg) if getattr(args, "json", False) else render_text(reg))
    return EXIT_OK


_HANDLERS = {"serve": run_serve, "mcp_config": run_mcp_config}


def dispatch(args) -> Optional[int]:
    """Run the MCP command selected by ``args`` (``None`` when ``args`` names another command)."""
    name = getattr(args, "_mcp_cmd", None)
    if name is None:
        return None
    try:
        return _HANDLERS[name](args)
    except KeyboardInterrupt:
        _err("interrupted")
        return 130
    except BrokenPipeError:
        return EXIT_OK
    except Exception as exc:  # never a traceback for an operator
        _err(f"unexpected error ({type(exc).__name__}); run zero-mem doctor")
        return EXIT_ERROR


__all__ = ["AGENTS", "add_mcp_parsers", "build_registration", "dispatch", "render_text", "run_mcp_config", "run_serve"]
