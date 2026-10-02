"""CLI of peer sharing: ``zero-mem share ...`` (ADR-V170-05, runbook docs/runbooks/peer-sharing.md).

Owner commands (invite, serve, grant, revoke, peers, grants, audit) and joiner commands (join, pull, discover). Thin shells over
:mod:`zero_mem.share`; the optional ``cryptography`` package is only needed (and only imported) by the commands that create or
use a certificate (invite, join, serve, pull). Exit codes: 0 ok, 1 partial (some sources rejected), 2 error / sharing off /
extra not installed, 3 refused by policy (public bind, locked), 4 content rejected, 5 not found.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Optional

from .commands_memory import EXIT_DENIED, EXIT_ERROR, EXIT_NOT_FOUND, EXIT_OK, EXIT_PARTIAL, _emit, _err, _wants_json

_NOT_FOUND = {"unknown_peer", "unknown_owner", "unknown_grant"}
_DENIED = {"public_bind_refused", "pairing_locked", "pairing_refused", "access_revoked", "peer_revoked", "pin_mismatch",
           "not_lan_address"}


def add_share_parser(subparsers) -> None:
    owner = argparse.ArgumentParser(add_help=False)
    owner.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output")
    owner.add_argument("--memory", default=argparse.SUPPRESS, metavar="NAME", help="named memory (needs named-memory support)")

    share = subparsers.add_parser(
        "share", help="share selected knowledge with another machine on your LAN (read-only, pinned TLS 1.3; "
                      "needs: pip install \"zero-mem[share]\")")
    sub = share.add_subparsers(dest="share_command", required=True)

    p = sub.add_parser("status", parents=[owner], help="show whether sharing is on, this machine's peer id, paired peers")
    p.set_defaults(_share_cmd="status")

    p = sub.add_parser("invite", parents=[owner], help="OWNER: create a one-time invite code (zm1:...) for another machine")
    p.add_argument("--expires", default="10m", help="how long the invite is valid (default 10m, max 24h)")
    p.add_argument("--grant", action="append", default=[], metavar="SPEC",
                   help="what the new peer may read, e.g. space=ks-shared,type=fact|file,expires=30d (repeatable; "
                        "none = the peer can read nothing until you run 'share grant')")
    p.add_argument("--host", default=None, help="LAN address to put in the invite (default: detected)")
    p.add_argument("--port", type=int, default=None, help="port `share serve` listens on (default 47890)")
    p.add_argument("--label", default=None, help="name the other machine will show for you (default: host name)")
    p.set_defaults(_share_cmd="invite")

    p = sub.add_parser("join", parents=[owner], help="JOINER: pair with an owner using their invite code")
    p.add_argument("code", help="the zm1:... invite code")
    p.add_argument("--name", default=None, help="the name the owner will show for this machine")
    p.set_defaults(_share_cmd="join")

    p = sub.add_parser("serve", parents=[owner], help="OWNER: serve to paired peers (foreground, time-boxed, LAN only)")
    p.add_argument("--bind", default=None, help="address to listen on (default: detected LAN address)")
    p.add_argument("--port", type=int, default=47890)
    p.add_argument("--announce", action="store_true", help="broadcast a discovery announcement (service name, peer id, port)")
    p.add_argument("--for", dest="duration", default="30m", help="stop after this long (default 30m, max 24h)")
    p.add_argument("--i-know-this-is-public", action="store_true", dest="i_know_public", help=argparse.SUPPRESS)
    p.set_defaults(_share_cmd="serve")

    p = sub.add_parser("discover", parents=[owner], help="JOINER: listen for announcing owners on the LAN (grants nothing)")
    p.add_argument("--timeout", type=float, default=5.0)
    p.set_defaults(_share_cmd="discover")

    p = sub.add_parser("grant", parents=[owner], help="OWNER: let a peer read selected knowledge (default for a peer: nothing)")
    p.add_argument("peer")
    p.add_argument("--space", default=None, help="knowledge space to share (e.g. ks-shared)")
    p.add_argument("--project", action="append", default=[], help="project to share (repeatable)")
    p.add_argument("--type", action="append", default=[], dest="types", help="only this memory type (repeatable)")
    p.add_argument("--ref-prefix", action="append", default=[], dest="ref_prefixes", help="only refs starting with this (repeatable)")
    p.add_argument("--expires", default=None, help="30d (default), 12h, ... or never")
    p.add_argument("--yes", action="store_true", help="confirm without prompting")
    p.set_defaults(_share_cmd="grant")

    p = sub.add_parser("revoke", parents=[owner],
                       help="OWNER: revoke a peer (no argument), one grant (GRANT_ID) or all its grants (--all)")
    p.add_argument("peer")
    p.add_argument("grant_id", nargs="?", default=None)
    p.add_argument("--all", action="store_true", dest="all_grants", help="revoke all grants; the peer stays paired")
    p.set_defaults(_share_cmd="revoke")

    p = sub.add_parser("peers", parents=[owner], help="list paired peers (who may connect) and owners (whom you pulled from)")
    p.set_defaults(_share_cmd="peers")

    p = sub.add_parser("grants", parents=[owner], help="OWNER: show who can read what")
    p.add_argument("peer", nargs="?", default=None)
    p.add_argument("--all", action="store_true", dest="all_states", help="include revoked and expired grants")
    p.set_defaults(_share_cmd="grants")

    p = sub.add_parser("audit", parents=[owner], help="show the sharing audit trail (pairing, grants, serving, pulls, rejections)")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(_share_cmd="audit")

    p = sub.add_parser("pull", parents=[owner], help="JOINER: copy what an owner granted you into a quarantine space")
    p.add_argument("owner", help="owner peer id (prefix) or label")
    p.add_argument("--dry-run", action="store_true", help="show the plan and change nothing")
    p.add_argument("--yes", action="store_true", help="confirm without prompting")
    p.set_defaults(_share_cmd="pull")

    p = sub.add_parser("unpair", parents=[owner], help="JOINER: forget an owner (already pulled copies stay)")
    p.add_argument("owner")
    p.set_defaults(_share_cmd="unpair")


# ---------------------------------------------------------------------------------------------
def _data_root(args):
    name = getattr(args, "memory", None)
    if not name:
        return None
    try:
        from . import memories  # named memories (T18)
        return memories.resolve_data_root(name)
    except (ImportError, AttributeError):
        from .share import ShareError

        raise ShareError("named_memories_unavailable", "named memories are not available in this build") from None


def _node(args):
    from .share.node import ShareNode

    return ShareNode.open(_data_root(args))


def _stdin_tty() -> bool:
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _ask(args, prompt: str, refusal: str) -> bool:
    if getattr(args, "yes", False):
        return True
    if not _stdin_tty():
        _err("this needs confirmation: re-run with --yes (or from a terminal and answer the prompt)")
        return False
    try:
        answer = input(f"{prompt} [y/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() in ("y", "yes"):
        return True
    _err(refusal)
    return False


def _fmt_size(n: int) -> str:
    return f"{n} B" if n < 1024 else (f"{n / 1024:.1f} KiB" if n < 1024 * 1024 else f"{n / 1048576:.1f} MiB")


def _print_table(rows: list, headers: list) -> None:
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) if rows else len(str(h)) for i, h in enumerate(headers)]
    print("  ".join(str(h).ljust(w) for h, w in zip(headers, widths)))
    for r in rows:
        print("  ".join(str(c).ljust(w) for c, w in zip(r, widths)))


# ---------------------------------------------------------------------------------------------
def _cmd_status(args) -> int:
    from .share.identity import load_identity

    with _node(args) as node:
        cfg = node.settings()
        try:
            import cryptography  # noqa: F401
            crypto = True
        except ImportError:
            crypto = False
        ident = load_identity(node.layout)
        doc = {"enabled": cfg.sharing_enabled, "active": cfg.sharing_active, "kill_switch": cfg.kill_switch,
               "settings_valid": cfg.valid, "cryptography_installed": crypto,
               "peer_id": ident.peer_id if ident else None, "fingerprint": ident.fingerprint if ident else None,
               "label": node.own_label(), "peers": len(node.log.active_peers()), "owners": len(node.owners())}
    if _wants_json(args):
        _emit(doc)
    else:
        print(f"sharing: {'ACTIVE' if doc['active'] else 'OFF'}"
              + ("" if doc["active"] else " (enable: zero-mem settings set sharing.enabled true)"))
        print(f"cryptography: {'installed' if crypto else 'MISSING - pip install \"zero-mem[share]\"'}")
        print(f"this machine: {doc['label']}  peer id: {doc['peer_id'] or '(created on first invite/join)'}")
        print(f"paired peers: {doc['peers']}   owners joined: {doc['owners']}")
    return EXIT_OK


def _cmd_invite(args) -> int:
    from .share import DEFAULT_PORT
    from .share.grants import parse_grant_arg
    from .share.invite import MAX_INVITE_SECONDS
    from .share.util import parse_duration

    with _node(args) as node:
        invite = node.create_invite(
            host=args.host, port=args.port or DEFAULT_PORT, label=args.label,
            expires_in=parse_duration(args.expires, maximum=MAX_INVITE_SECONDS),
            grants=[parse_grant_arg(g) for g in args.grant])
        code = invite.encode()
    if _wants_json(args):
        _emit({"code": code, "host": invite.host, "port": invite.port, "expires": invite.expires,
               "grants_offered": len(args.grant)})
    else:
        print(code)
        left = max(0, invite.expires - int(time.time()))
        print(f"\nThis invite is a one-time secret (valid {left // 60} min). Hand it to the other person through a channel you trust.", file=sys.stderr)
        print(f"On the other machine: zero-mem share join <code> --name <label>   (needs: zero-mem share serve running here)",
              file=sys.stderr)
        print("It offers " + (f"{len(args.grant)} grant(s)." if args.grant else "NO access: add one later with 'zero-mem share grant'."),
              file=sys.stderr)
    return EXIT_OK


def _cmd_join(args) -> int:
    from .share import client

    with _node(args) as node:
        result = client.join(node, args.code, args.name)
    if _wants_json(args):
        _emit(result)
    else:
        print(f"Paired with '{result['owner_label']}' (peer id {result['owner_peer_id']}).")
        print(f"Next: zero-mem share pull {result['owner_label']} --dry-run   (the owner must grant you access first)")
    return EXIT_OK


def _cmd_serve(args) -> int:
    from .share.server import MAX_SERVE_SECONDS, ShareServer
    from .share.util import detect_lan_address, parse_duration

    with _node(args) as node:
        node.require_active()
        bind = args.bind or detect_lan_address()
        if bind is None:
            from .share import ShareError

            raise ShareError("no_lan_address", "cannot detect this machine's LAN address; pass --bind")
        server = ShareServer(node, bind=bind, port=args.port, duration=parse_duration(args.duration, maximum=MAX_SERVE_SECONDS),
                             i_know_public=args.i_know_public, announce=args.announce)
        server.start()
        ident = node.identity()
        if _wants_json(args):
            _emit({"listening": f"{server.address}:{server.port}", "peer_id": ident.peer_id, "fingerprint": ident.fingerprint,
                   "for": args.duration})
        else:
            print(f"Serving on {server.address}:{server.port} for {args.duration} (peer id {ident.peer_id}). Press Ctrl+C to stop.")
            print("Only paired, non-revoked peers can connect; they can read only what you granted (zero-mem share grants).")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.stop()
    if not _wants_json(args):
        print("Stopped.")
    return EXIT_OK


def _cmd_discover(args) -> int:
    from .share.discovery import discover

    found = discover(timeout=max(0.5, min(args.timeout, 60.0)))
    if _wants_json(args):
        _emit({"found": found})
    elif not found:
        print("No announcing owners heard. (The owner must run: zero-mem share serve --announce)")
    else:
        _print_table([(f["peer_id"], f["host"], f["port"], f.get("label", "-")) for f in found],
                     ["peer id", "host", "port", "label"])
        print("Discovery only shows where an owner is; it grants nothing. You still need an invite (zero-mem share join).")
    return EXIT_OK


def _cmd_grant(args) -> int:
    from .share.grants import expires_arg, validate_grant_spec

    spec = validate_grant_spec({"space": args.space, "projects": args.project, "types": args.types,
                                "ref_prefixes": args.ref_prefixes, "expires_in": expires_arg(args.expires)})
    with _node(args) as node:
        peer = node.resolve_peer(args.peer)
        what = (f"space '{spec['space']}'" if spec["space"] else "") + \
               ((" and " if spec["space"] else "") + "project(s) " + ", ".join(spec["projects"]) if spec["projects"] else "")
        extra = (f" only types {', '.join(spec['types'])}" if spec["types"] else "") + \
                (f" only refs starting {', '.join(spec['ref_prefixes'])}" if spec["ref_prefixes"] else "")
        life = "never expires" if spec["expires_in"] is None else f"expires in {spec['expires_in'] // 86400}d" \
            if spec["expires_in"] >= 86400 else f"expires in {spec['expires_in'] // 60} min"
        if not _ask(args, f"Let peer '{peer['label']}' ({peer['peer_id'][:8]}) READ {what}{extra}; {life}? (read-only copy, audited)",
                    "not confirmed; nothing was granted"):
            return EXIT_ERROR
        grant = node.grant(peer["peer_id"], spec)
        counts = node.preview(peer["peer_id"])
    if _wants_json(args):
        _emit({"grant": grant, "now_readable": counts})
    else:
        print(f"Granted {grant['grant_id']}. The peer can now read {counts['sources']} source(s), {_fmt_size(counts['bytes'])} "
              "(only active, non-secret items; re-scanned when served).")
    return EXIT_OK


def _cmd_revoke(args) -> int:
    with _node(args) as node:
        if args.grant_id or args.all_grants:
            result = node.revoke_grants(args.peer, args.grant_id)
        else:
            result = node.revoke_peer(args.peer)
    if _wants_json(args):
        _emit(result)
    else:
        print(f"{result['status']}: {result['peer_id']}")
        if result["status"] == "revoked" and "revoked" not in result:
            print("This machine's certificate is no longer trusted. Copies it already pulled cannot be recalled.")
    return EXIT_OK


def _cmd_peers(args) -> int:
    with _node(args) as node:
        peers, owners = node.peers(), node.owners()
    if _wants_json(args):
        _emit({"peers": peers, "owners": [{k: o[k] for k in ("peer_id", "label", "host", "port", "added_at")} for o in owners]})
        return EXIT_OK
    print("Peers that may connect to you:")
    _print_table([(p["peer_id"], p["label"], p["status"], p["active_grants"], p["created_at"]) for p in peers],
                 ["peer id", "label", "status", "grants", "paired"])
    print("\nOwners you pull from:")
    _print_table([(o["peer_id"], o["label"], f"{o['host']}:{o['port']}", o["added_at"]) for o in owners],
                 ["peer id", "label", "address", "joined"])
    return EXIT_OK


def _cmd_grants(args) -> int:
    with _node(args) as node:
        rows = node.grants(args.peer, include_ended=args.all_states)
        peers = {p["peer_id"]: p["label"] for p in node.peers()}
    if _wants_json(args):
        _emit({"grants": rows})
        return EXIT_OK
    _print_table([(g["grant_id"], f"{peers.get(g['peer_id'], '?')} ({g['peer_id'][:8]})",
                   ",".join(([g["space"]] if g["space"] else []) + [f"project:{p}" for p in g["projects"]]),
                   ",".join(g["types"]) or "all types", ",".join(g["ref_prefixes"]) or "-", g["expires_at"] or "never", g["state"])
                  for g in rows], ["grant", "peer", "scope", "types", "ref prefixes", "expires", "state"])
    if not rows:
        print("(no grants: peers can read nothing)")
    return EXIT_OK


def _cmd_audit(args) -> int:
    with _node(args) as node:
        rows = node.audit(max(1, min(args.limit, 1000)))
    if _wants_json(args):
        _emit({"events": rows})
        return EXIT_OK
    for row in rows:
        detail = " ".join(f"{k}={v}" for k, v in sorted(row.items()) if k not in ("at", "op") and v not in (None, "", {}, []))
        print(f"{row['at']}  {row['op']:<13} {detail}")
    if not rows:
        print("(no sharing events yet)")
    return EXIT_OK


def _cmd_pull(args) -> int:
    from .share import client

    def confirm(plan: dict) -> bool:
        _print_plan(plan)
        return _ask(args, f"Import {plan['sources']} source(s) ({_fmt_size(plan['bytes'])}) into the quarantine space?",
                    "not confirmed; nothing was imported")

    with _node(args) as node:
        report = client.pull(node, args.owner, dry_run=args.dry_run, confirm=None if args.dry_run else confirm)
    data = report.as_dict()
    if _wants_json(args):
        _emit(data)
    else:
        if args.dry_run:
            _print_plan(report.plan)
            print("\n(dry run: nothing was imported)")
        elif report.aborted:
            pass
        else:
            print(f"Imported {report.stored} source(s) into quarantine, {report.proposed} learned item(s) as PROPOSALS "
                  f"(review: zero-mem review list), {report.unchanged} unchanged, {report.tombstoned} forgotten by the owner, "
                  f"{len(report.rejected)} rejected.")
            for item in report.rejected[:20]:
                print(f"  rejected {item['ref']}: {item['reason']}")
    if report.aborted:
        return EXIT_ERROR
    return EXIT_PARTIAL if report.rejected else EXIT_OK


def _print_plan(plan: dict) -> None:
    rows = [(r["action"] + (f" ({r['reason']})" if r["reason"] else ""), r["memory_type"], _fmt_size(r["size"]), r["ref"])
            for r in plan["rows"]]
    _print_table(rows, ["action", "type", "size", "ref"])
    summary = ", ".join(f"{k}: {v}" for k, v in sorted(plan["summary"].items())) or "nothing offered"
    print(f"\nPlan: {summary}" + (f"; {plan['invalid_entries']} invalid entries ignored" if plan["invalid_entries"] else ""))
    print("Imported text is stored as UNTRUSTED reference (never as instructions); rules/decisions/gotchas become proposals.")


def _cmd_unpair(args) -> int:
    with _node(args) as node:
        result = node.forget_owner(args.owner)
    if _wants_json(args):
        _emit(result)
    else:
        print(f"removed owner {result['peer_id']} (already pulled copies stay in their quarantine space)")
    return EXIT_OK


_HANDLERS = {"status": _cmd_status, "invite": _cmd_invite, "join": _cmd_join, "serve": _cmd_serve, "discover": _cmd_discover,
             "grant": _cmd_grant, "revoke": _cmd_revoke, "peers": _cmd_peers, "grants": _cmd_grants, "audit": _cmd_audit,
             "pull": _cmd_pull, "unpair": _cmd_unpair}


def dispatch(args) -> Optional[int]:
    name = getattr(args, "_share_cmd", None)
    if name is None:
        return None
    from .memory import MemoryConfigError
    from .memory_layout import LayoutError
    from .provisioning import ProvisioningError
    from .share import ShareError

    try:
        return _HANDLERS[name](args)
    except ShareError as exc:
        _err(exc.message)
        if exc.code in _NOT_FOUND:
            return EXIT_NOT_FOUND
        return EXIT_DENIED if exc.code in _DENIED else EXIT_ERROR
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
    except Exception as exc:  # noqa: BLE001 - never a traceback for the owner
        _err(f"unexpected error ({type(exc).__name__}); run zero-mem doctor")
        return EXIT_ERROR


__all__ = ["add_share_parser", "dispatch"]
