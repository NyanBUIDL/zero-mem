"""V141 — `zero-mem config` and `zero-mem grant` CLI commands (DEF-012).

config: user-local configuration (XDG file) — currently corpus-store-path.
grant:  knowledge-space / project grant administration wrapped around the
        EXISTING trusted control-plane surface (GrantAdminService), which
        projects the event AND appends it to the canonical JSONL event log.

Canonical-boundary rule: grants created here are canonical events first; the
derived projection (zm_access_grants) is rebuilt/projected from them. This
CLI never INSERTs into zm_access_grants directly.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# config subcommand
# ---------------------------------------------------------------------------


def _validate_corpus_path(path: str) -> None:
    from src.integration.m6.runtime import (
        CorpusStoreConfigError,
        _validate_corpus_store_path,
    )

    try:
        _validate_corpus_store_path(Path(path))
    except CorpusStoreConfigError as exc:
        raise ConfigCommandError(f"{exc.code}: {exc}") from None
    except sqlite3_error() as exc:  # pragma: no cover - defensive
        raise ConfigCommandError(f"unreadable_corpus_store: {exc}") from None


def sqlite3_error():
    import sqlite3

    return sqlite3.Error


class ConfigCommandError(Exception):
    pass


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
    from zero_mem import userconfig

    return {
        "config_file": str(userconfig.config_file_path()),
        "corpus_store_path": userconfig.get_corpus_store_path(),
        "env_override": __import__("os").environ.get("ZM_M6_CORPUS_STORE_PATH"),
    }


# ---------------------------------------------------------------------------
# grant subcommand (wraps GrantAdminService — trusted control plane)
# ---------------------------------------------------------------------------


class GrantCommandError(Exception):
    pass


def _grant_roots(data_root: Optional[str]):
    """Resolve derived + canonical paths for grant administration."""
    root = Path(data_root) if data_root else _default_data_root()
    derived = root / "grants-derived.sqlite"
    events = root / "grants-events.jsonl"
    return root, derived, events


def _default_data_root() -> Path:
    """Agent-independent default under the XDG data home."""
    base = __import__("os").environ.get("XDG_DATA_HOME")
    if not base or not Path(base).is_absolute():
        base = str(Path.home() / ".local" / "share")
    return Path(base) / "zero-mem"


def _open_admin(data_root: Optional[str]):
    """Open a writable derived-grant DB + canonical JSONL writer.

    The derived DB is a REBUILDABLE projection of grants-events.jsonl. If it is
    missing or empty but the event log exists, it is rebuilt from canonical
    events first (never the other way around).
    """
    import sqlite3

    from src.access.admin import GrantAdminService
    from src.storage.migrations import migrate_8

    _, derived_path, events_path = _grant_roots(data_root)
    derived_path.parent.mkdir(parents=True, exist_ok=True)

    def writer(event_dict: dict) -> None:
        with events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event_dict, ensure_ascii=False, sort_keys=True))
            f.write("\n")

    fresh = not derived_path.exists()
    conn = sqlite3.connect(str(derived_path))
    conn.row_factory = sqlite3.Row
    if fresh or conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' "
        "AND name='zm_access_grants'"
    ).fetchone()[0] == 0:
        migrate_8.up(conn, "cli")
        # Rebuild from canonical events when the log exists (canonical wins).
        if events_path.exists():
            from src.access.grant_events import AccessGrantEvent, rebuild_grants

            events = [AccessGrantEvent.from_canonical_dict(json.loads(l))
                      for l in events_path.read_text(encoding="utf-8").splitlines()
                      if l.strip()]
            rebuild_grants(conn, events)
        conn.commit()

    svc = GrantAdminService(conn, writer, lambda ref: object())
    return svc, conn


def _resolve_space_or_none(space: str, data_root: Optional[str]) -> bool:
    """True when ``space`` exists in the configured corpus projection."""
    from src.integration.m6.runtime import M6Runtime

    from zero_mem import userconfig

    corpus_val = (
        __import__("os").environ.get("ZM_M6_CORPUS_STORE_PATH")
        or userconfig.get_corpus_store_path()
    )
    if not corpus_val:
        raise GrantCommandError(
            "corpus-store-path-not-configured: set it first with "
            "`zero-mem config set corpus-store-path <path>` to enable "
            "knowledge-space validation")
    rt = M6Runtime(corpus_val)
    try:
        conn = rt.open_corpus_conn()
        assert conn is not None
        row = conn.execute(
            "SELECT 1 FROM zm_corpus_units WHERE knowledge_space_id = ? LIMIT 1",
            (space,),
        ).fetchone()
        return row is not None
    finally:
        pass


def run_grant_add(subject: str, *, space: Optional[str], project: Optional[str],
                  operation: str, data_root: Optional[str],
                  verification_ref: Optional[str] = None) -> dict:
    from src.access.admin import GrantAdminRequest

    if bool(space) == bool(project):
        raise GrantCommandError("specify exactly one of --space or --project")
    target_type = "knowledge_space" if space else "project"
    target_id = space or project

    if space:
        if not _resolve_space_or_none(space, data_root):
            raise GrantCommandError(
                f"unknown-knowledge-space: '{space}' not found in the configured "
                "corpus projection — refusing to create an ineffective grant")

    svc, conn = _open_admin(data_root)
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        req = GrantAdminRequest(
            action="create",
            grant_id=f"g-{uuid.uuid4().hex[:12]}",
            subject_profile=subject,
            operation=operation.upper(),
            target_type=target_type,
            target_id=target_id,
            created_at=now,
        )
        result = svc.create(req)
        result["target"] = {"type": target_type, "id": target_id}
        result["subject"] = subject
        return result
    finally:
        conn.close()


def run_grant_list(subject: Optional[str], data_root: Optional[str]) -> list:
    import sqlite3 as _sq

    _, derived_path, _events = _grant_roots(data_root)
    if not derived_path.exists():
        return []
    conn = _sq.connect(str(derived_path))
    conn.row_factory = _sq.Row
    try:
        q = ("SELECT grant_id, subject_profile, operation, target_type, "
             "target_id, state FROM zm_access_grants")
        params: tuple = ()
        if subject:
            q += " WHERE subject_profile = ?"
            params = (subject,)
        rows = conn.execute(q, params).fetchall()
        active_only = [dict(r) for r in rows if (r["state"] or "") != "revoked"]
        # Latest state per grant id (revocations supersede in projection order).
        latest: dict = {}
        for r in rows:
            latest[r["grant_id"]] = dict(r)
        return [g for g in latest.values() if (g.get("state") or "") != "revoked"] \
            if subject else [g for g in latest.values()
                             if (g.get("state") or "") != "revoked"]
    finally:
        conn.close()


def run_grant_revoke(grant_id: str, data_root: Optional[str]) -> dict:
    import sqlite3 as _sq

    _, derived_path, _events = _grant_roots(data_root)
    if not derived_path.exists():
        raise GrantCommandError(f"unknown-grant: no grant store at {derived_path}")
    conn = _sq.connect(str(derived_path))
    conn.row_factory = _sq.Row
    try:
        row = conn.execute(
            "SELECT * FROM zm_access_grants WHERE grant_id = ? "
            "ORDER BY rowid DESC LIMIT 1", (grant_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise GrantCommandError(f"unknown-grant: {grant_id}")
    if (row["state"] or "") == "revoked":
        raise GrantCommandError(f"already-revoked: {grant_id}")

    svc, conn2 = _open_admin(data_root)
    try:
        from src.access.admin import GrantAdminRequest

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        req = GrantAdminRequest(
            action="revoke",
            grant_id=grant_id,
            subject_profile=row["subject_profile"],
            operation=row["operation"],
            target_type=row["target_type"],
            target_id=row["target_id"],
            created_at=now,
        )
        return svc.revoke(req)
    finally:
        conn2.close()


# ---------------------------------------------------------------------------
# argparse wiring for zero_mem.cli
# ---------------------------------------------------------------------------


def add_cli_parsers(subparsers) -> None:
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

    g = subparsers.add_parser("grant", help="manage access grants (canonical admin surface)")
    g_sub = g.add_subparsers(dest="grant_command", required=True)
    p_add = g_sub.add_parser("add", help="grant a profile read access to a space/project")
    p_add.add_argument("subject", type=str, help="subject profile id (e.g. agent name)")
    p_add.add_argument("--space", type=str, help="knowledge space to grant READ on")
    p_add.add_argument("--project", type=str, help="project id to grant READ on")
    p_add.add_argument("--read", action="store_true", dest="_flag_read",
                       default=False, help="grant READ operation (default)")
    p_add.add_argument("--operation", default=None, choices=["read", "write"])
    p_add.add_argument("--verification-ref", type=str, default=None,
                       help="required for WRITE grants")
    p_add.add_argument("--data-root", type=str, default=None)
    p_add.set_defaults(_grant_add=True)
    p_list = g_sub.add_parser("list", help="list grants (optionally by subject)")
    p_list.add_argument("--subject", type=str, default=None)
    p_list.add_argument("--data-root", type=str, default=None)
    p_list.set_defaults(_grant_list=True)
    p_revoke = g_sub.add_parser("revoke", help="revoke a grant by id")
    p_revoke.add_argument("grant_id", type=str)
    p_revoke.add_argument("--data-root", type=str, default=None)
    p_revoke.set_defaults(_grant_revoke=True)


def handle_cli(args) -> int:
    """Dispatch config/grant subcommands; returns process exit code."""
    import json as _json

    try:
        if getattr(args, "_config_set", False):
            result = run_config_set(args.key, args.value)
        elif getattr(args, "_config_unset", False):
            result = run_config_unset(args.key)
        elif getattr(args, "_config_show", False):
            result = run_config_show()
        elif getattr(args, "_grant_add", False):
            # Operation: --read flag wins; --operation explicit otherwise;
            # default READ (least privilege).
            op = "read" if getattr(args, "_flag_read", False) \
                else (getattr(args, "operation", None) or "read")
            if op == "write" and not args.verification_ref:
                print("zero-mem: WRITE grants require --verification-ref",
                      file=sys.stderr)
                return 2
            result = run_grant_add(
                args.subject, space=args.space, project=args.project,
                operation=op, data_root=args.data_root,
                verification_ref=args.verification_ref)
        elif getattr(args, "_grant_list", False):
            result = run_grant_list(args.subject, args.data_root)
        elif getattr(args, "_grant_revoke", False):
            result = run_grant_revoke(args.grant_id, args.data_root)
        else:
            return 1
    except (ConfigCommandError, GrantCommandError) as exc:
        print(f"zero-mem: {exc}", file=sys.stderr)
        return 2
    print(_json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0
