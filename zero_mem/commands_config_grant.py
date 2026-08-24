"""V141 — `zero-mem config` CLI (DEF-012 core-fix support).

config: user-local configuration (XDG file) — currently corpus-store-path.

V141-R2 (DEF-013 remediation, GATE-R1 Option A): the `zero-mem grant`
subcommand was REMOVED. Its store lived outside the production authorization
path (m6/handlers._resolve_grants reads the sidecar's main derived store), so
grants created through it could never take effect and it formed a second
source of truth for authorization data. Grant administration stays with the
trusted control-plane surface; a wired admin CLI is deferred to the v1.5+
enterprise-authorization cluster (see ADR-V141-01).
"""

from __future__ import annotations

import json
import sys


class ConfigCommandError(Exception):
    pass


def _validate_corpus_path(path: str) -> None:
    """Fail LOUD at set time when the path is not a usable corpus store."""
    import sqlite3
    from pathlib import Path

    from src.integration.m6.runtime import (
        CorpusStoreConfigError,
        _validate_corpus_store_path,
    )

    try:
        _validate_corpus_store_path(Path(path))
    except CorpusStoreConfigError as exc:
        raise ConfigCommandError(f"{exc.code}: {exc}") from None
    except sqlite3.Error as exc:
        raise ConfigCommandError(f"unreadable_corpus_store: {exc}") from None


def run_config_set(key: str, value: str) -> dict:
    if key != "corpus-store-path":
        raise ConfigCommandError(
            f"unknown key '{key}' (known: corpus-store-path)")
    from zero_mem import userconfig

    _validate_corpus_path(value)
    userconfig.set_corpus_store_path(value)
    return {"status": "ok", "key": key, "value": value,
            "config_file": str(userconfig.config_file_path())}


def run_config_unset(key: str) -> dict:
    if key != "corpus-store-path":
        raise ConfigCommandError(
            f"unknown key '{key}' (known: corpus-store-path)")
    from zero_mem import userconfig

    removed = userconfig.unset_corpus_store_path()
    return {"status": "ok", "key": key, "removed": removed}


def run_config_show() -> dict:
    import os

    from zero_mem import userconfig

    return {
        "config_file": str(userconfig.config_file_path()),
        "corpus_store_path": userconfig.get_corpus_store_path(),
        "env_override": os.environ.get("ZM_M6_CORPUS_STORE_PATH"),
    }


# ---------------------------------------------------------------------------
# argparse wiring for zero_mem.cli
# ---------------------------------------------------------------------------


def add_config_parsers(subparsers) -> None:
    cfg = subparsers.add_parser("config", help="show or change user-local configuration")
    cfg_sub = cfg.add_subparsers(dest="config_command", required=True)
    p_set = cfg_sub.add_parser("set", help="set a configuration key")
    p_set.add_argument("key", choices=["corpus-store-path"])
    p_set.add_argument("value", type=str)
    p_set.set_defaults(_config_set=True)
    p_unset = cfg_sub.add_parser("unset", help="clear a configuration key")
    p_unset.add_argument("key", choices=["corpus-store-path"])
    p_unset.set_defaults(_config_unset=True)
    p_show = cfg_sub.add_parser("show", help="show current configuration")
    p_show.set_defaults(_config_show=True)


def handle_cli(args) -> int:
    """Dispatch config subcommands; returns process exit code."""
    try:
        if getattr(args, "_config_set", False):
            result = run_config_set(args.key, args.value)
        elif getattr(args, "_config_unset", False):
            result = run_config_unset(args.key)
        elif getattr(args, "_config_show", False):
            result = run_config_show()
        else:
            return 1
    except ConfigCommandError as exc:
        print(f"zero-mem: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0
