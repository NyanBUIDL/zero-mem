"""CLI of the learning harness: ``settings`` (owner configuration), ``propose`` (agent/user proposal) and ``review``
(OWNER decisions). Thin shells over :mod:`zero_mem.learning_settings` and :mod:`zero_mem.learning`.

``review`` and ``settings`` are owner commands: agents must not be given a shell that can run them (ADR-V170-03).
``review approve`` and ``review revoke`` need ``--yes`` or an interactive confirmation, like ``agents grant-write``.

Exit codes follow ``zero_mem.commands_memory``: 0 ok, 2 invalid usage / blocked setup, 3 refused by policy (kill switch,
learning off, limits, deny pattern), 4 secret / content rejected, 5 not found.
"""
from __future__ import annotations

import argparse
from typing import Any, Optional

from . import learning_settings as ls
from .commands_memory import (
    EXIT_DENIED, EXIT_ERROR, EXIT_NOT_FOUND, EXIT_OK, EXIT_REJECTED, _clip_line, _common, _confirm, _emit, _err,
    _open, _read_text, _wants_json,
)
from .memory import MEMORY_TYPES, SCOPES
from .memory_layout import Layout

_PROPOSE_TYPES = tuple(t for t in MEMORY_TYPES if t != "file")
_REASONS = {
    "kill_switch": "the owner's kill switch is on (settings: safety.kill_switch)",
    "learning_off": "learning is off (settings: learning.mode)",
    "agent_proposals_disallowed": "agent proposals are disabled (settings: learning.allow_agent_proposals)",
    "daily_limit": "the daily proposal limit for this profile is reached (settings: learning.max_proposals_per_day)",
    "deny_pattern": "the text matches an owner deny pattern (settings: safety.deny_patterns)",
    "settings_invalid": "the settings file is unusable, so learning is off (zero-mem settings validate)",
    "proposal_log_too_large": "the proposal log is too large to process",
    "secret_detected": "a credential-like value was detected",
    "invalid_evidence": "evidence must be up to 5 short strings (200 characters each)",
    "invalid_source": "source must be agent, user or learner",
    "unknown_proposal": "no such proposal",
}


def add_learning_parsers(subparsers) -> None:
    common = _common()
    # owner commands never act "as" a profile: only --json (a --profile on `review list` is a FILTER)
    owner = argparse.ArgumentParser(add_help=False)
    owner.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output")

    # -- settings --------------------------------------------------------------------------
    settings = subparsers.add_parser("settings", help="owner settings of the learning harness (settings.toml)")
    sub = settings.add_subparsers(dest="settings_command", required=True)
    p = sub.add_parser("show", parents=[owner], help="show the effective settings")
    p.set_defaults(_learn_cmd="settings_show")
    p = sub.add_parser("set", parents=[owner], help="set one dotted key (validated), e.g. learning.mode off")
    p.add_argument("key")
    p.add_argument("value")
    p.set_defaults(_learn_cmd="settings_set")
    p = sub.add_parser("unset", parents=[owner], help="remove one key (back to its default)")
    p.add_argument("key")
    p.set_defaults(_learn_cmd="settings_unset")
    p = sub.add_parser("validate", parents=[owner], help="check the settings file (exit 2 when it is unusable)")
    p.set_defaults(_learn_cmd="settings_validate")
    p = sub.add_parser("path", parents=[owner], help="print the settings file location")
    p.set_defaults(_learn_cmd="settings_path")

    # -- propose ---------------------------------------------------------------------------
    p = subparsers.add_parser(
        "propose", parents=[common],
        help="propose a rule / decision / gotcha for the owner to review (inert until approved)")
    p.add_argument("text", nargs="+", help="the proposal ('-' reads standard input)")
    p.add_argument("--type", dest="memory_type", choices=_PROPOSE_TYPES, default="rule", help="default: rule")
    p.add_argument("--scope", choices=SCOPES, default="shared", help="default: shared (needs owner approval anyway)")
    p.add_argument("--project", dest="project_id", default=None, help="project id (project scope)")
    p.add_argument("--name", default=None, help="stable name (approval then versions mem://<type>/<name>)")
    p.add_argument("--evidence", action="append", default=None, metavar="REF",
                   help="short supporting reference (repeatable, max 5, 200 chars each)")
    p.add_argument("--source", choices=("agent", "user", "learner"), default="agent",
                   help="provenance label (default: agent; use 'user' when the owner proposes)")
    p.set_defaults(_learn_cmd="propose")

    # -- review (owner) --------------------------------------------------------------------
    review = subparsers.add_parser("review", help="OWNER commands: review, approve, reject, revoke, expire proposals")
    sub = review.add_subparsers(dest="review_command", required=True)
    p = sub.add_parser("list", parents=[owner], help="list proposals (default: pending)")
    p.add_argument("--status", default="pending",
                   choices=("pending", "approved", "rejected", "expired", "withdrawn", "revoked", "superseded", "all"))
    p.add_argument("--profile", dest="filter_profile", default=None, help="only this proposing profile")
    p.set_defaults(_learn_cmd="review_list")
    p = sub.add_parser("show", parents=[owner], help="show one proposal with evidence and history")
    p.add_argument("proposal_id")
    p.set_defaults(_learn_cmd="review_show")
    p = sub.add_parser("approve", parents=[owner],
                       help="OWNER ACTION: commit a proposal to memory (single-write approval, audited)")
    p.add_argument("proposal_id")
    p.add_argument("--edit", default=None, metavar="TEXT", help="rewrite the text before approving (the original is kept)")
    p.add_argument("--name", default=None, help="stable name for the new memory")
    p.add_argument("--yes", action="store_true", help="confirm without prompting")
    p.set_defaults(_learn_cmd="review_approve")
    p = sub.add_parser("reject", parents=[owner], help="reject a pending proposal")
    p.add_argument("proposal_id")
    p.add_argument("--reason", default=None)
    p.set_defaults(_learn_cmd="review_reject")
    p = sub.add_parser("revoke", parents=[owner],
                       help="OWNER ACTION: revoke an active memory (tombstone; raw bytes are kept)")
    p.add_argument("ref", metavar="SOURCE_OR_REF", help="source id, unique id prefix or mem:// reference")
    p.add_argument("--reason", default=None)
    p.add_argument("--yes", action="store_true", help="confirm without prompting")
    p.set_defaults(_learn_cmd="review_revoke")
    p = sub.add_parser("expire", parents=[owner], help="apply the TTLs (expire old pending proposals; list hidden items)")
    p.set_defaults(_learn_cmd="review_expire")


# ---------------------------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------------------------
def _flat(settings: ls.Settings) -> list:
    doc = settings.as_dict()
    rows = []
    for section in ("learning", "injection", "safety"):
        for key, value in doc[section].items():
            if key in ("profiles", "projects"):
                for name, body in value.items():
                    for field, val in body.items():
                        rows.append((f"injection.{key}.{name}.{field}", val))
                continue
            rows.append((f"{section}.{key}", value))
    return rows


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(str(v) for v in value) + "]"
    return str(value)


def _cmd_settings_show(args) -> int:
    path = ls.settings_path()
    cfg = ls.load_settings(path)
    exists = path.exists()
    if _wants_json(args):
        _emit({"path": path.as_posix(), "exists": exists, "valid": cfg.valid, "error": cfg.error,
               "effective_mode": cfg.effective_mode, "settings": cfg.as_dict()})
        return EXIT_OK
    state = "valid" if cfg.valid else f"UNUSABLE ({cfg.error}); fail-safe: learning off, injection off"
    print(f"settings file  {path.as_posix()}  ({'present' if exists else 'missing: defaults'}; {state})")
    for key, value in _flat(cfg):
        print(f"{key} = {_fmt(value)}")
    if cfg.mode == "auto_low_risk":
        print("note: auto_low_risk is reserved; it currently behaves exactly like suggest (nothing is auto-approved)")
    return EXIT_OK


def _cmd_settings_set(args) -> int:
    try:
        cfg = ls.set_value(args.key, args.value)
    except ls.SettingsError as exc:
        _err(f"invalid setting: {exc}")
        return EXIT_ERROR
    if not cfg.valid:  # cannot happen after write_settings validated; defensive
        _err("settings are unusable after the change")
        return EXIT_ERROR
    if _wants_json(args):
        _emit({"status": "ok", "key": args.key, "settings": cfg.as_dict()})
    else:
        print(f"ok  {args.key.strip()} set")
    return EXIT_OK


def _cmd_settings_unset(args) -> int:
    try:
        _cfg, removed = ls.unset_value(args.key)
    except ls.SettingsError as exc:
        _err(f"invalid setting: {exc}")
        return EXIT_ERROR
    if _wants_json(args):
        _emit({"status": "ok" if removed else "not_set", "key": args.key})
    elif removed:
        print(f"ok  {args.key.strip()} removed (default applies)")
    else:
        _err(f"not set: {args.key.strip()}")
    return EXIT_OK if removed else EXIT_NOT_FOUND


def _cmd_settings_validate(args) -> int:
    path = ls.settings_path()
    cfg = ls.load_settings(path)
    if _wants_json(args):
        _emit({"path": path.as_posix(), "valid": cfg.valid, "error": cfg.error})
    elif cfg.valid:
        print("valid" + ("" if path.exists() else " (no file: defaults)"))
    else:
        _err(f"invalid: {cfg.error}. Fail-safe is active (learning off, injection off).")
    return EXIT_OK if cfg.valid else EXIT_ERROR


def _cmd_settings_path(args) -> int:
    path = ls.settings_path()
    if _wants_json(args):
        _emit({"path": path.as_posix(), "exists": path.exists()})
    else:
        print(path.as_posix())
    return EXIT_OK


# ---------------------------------------------------------------------------------------------
# propose
# ---------------------------------------------------------------------------------------------
def _explain_proposal(result, args) -> None:
    status = result.status
    if status == "rejected_secret":
        rules = ", ".join(result.rule_ids or ())
        _err("rejected: a credential-like value was detected" + (f" (rule: {rules})" if rules else "")
             + ". Nothing was stored. Remove the secret and try again.")
    elif status == "rejected":
        _err(f"rejected: {_REASONS.get(result.reason, result.reason)}. Nothing was stored.")
    elif status == "invalid":
        _err(f"invalid input: {_REASONS.get(result.reason, result.reason)}")
    else:
        _err(f"{status}: {_REASONS.get(result.reason, result.reason)}")


def _cmd_propose(args) -> int:
    memory = _open(args)
    try:
        result = memory.propose(_read_text(args.text), args.memory_type, name=args.name, scope=args.scope,
                                project_id=args.project_id, evidence=args.evidence, source=args.source)
    finally:
        memory.close()
    if _wants_json(args):
        _emit(result.as_dict())
    elif result.ok:
        extra = f" (duplicate: seen {result.seen}x)" if result.status == "merged" else ""
        print(f"{result.status}  {result.proposal_id}  {result.memory_type} ({result.scope}){extra}  "
              "- pending owner review: zero-mem review list")
    else:
        _explain_proposal(result, args)
    if result.ok:
        return EXIT_OK
    return {"rejected": EXIT_DENIED, "rejected_secret": EXIT_REJECTED}.get(result.status, EXIT_ERROR)


# ---------------------------------------------------------------------------------------------
# review
# ---------------------------------------------------------------------------------------------
def _reviewer():
    from .learning import Reviewer

    layout = Layout.resolve(None)
    layout.ensure()
    return Reviewer(layout)


def _row(p: dict) -> str:
    return (f"{p['id']}  {p['status']:<10} {p['proposer']:<14} {p['memory_type']}/{p['scope']}"
            f"{' x' + str(p['seen']) if p.get('seen', 1) > 1 else ''}  {_clip_line(p['text'], 100)}")


def _cmd_review_list(args) -> int:
    rows = _reviewer().list(status=args.status, profile=args.filter_profile)
    if _wants_json(args):
        _emit({"status": args.status, "count": len(rows), "proposals": rows})
        return EXIT_OK
    if not rows:
        print(f"no {args.status if args.status != 'all' else ''} proposals".replace("  ", " "))
        return EXIT_OK
    for p in rows:
        print(_row(p) + ("  [active ttl expired]" if p.get("active_expired") else ""))
    return EXIT_OK


def _cmd_review_show(args) -> int:
    p = _reviewer().show(args.proposal_id)
    if p is None:
        _err("not found: no such proposal")
        return EXIT_NOT_FOUND
    if _wants_json(args):
        _emit(p)
        return EXIT_OK
    for key in ("id", "status", "proposer", "source", "memory_type", "scope", "project_id", "name", "seen", "created_at",
                "decided_at", "decided_by", "reason", "source_id", "external_ref", "version", "superseded_by"):
        if key in p:
            print(f"{key:<12} {p[key]}")
    print("evidence     " + (", ".join(p["evidence"]) if p.get("evidence") else "-"))
    print("text:\n  " + p["text"].replace("\n", "\n  "))
    if "final_text" in p:
        print("approved text (edited):\n  " + p["final_text"].replace("\n", "\n  "))
    if p.get("active_expired"):
        print("note: approval is older than learning.active_ttl_days; it is hidden from recall/context")
    print("history:     " + "; ".join(f"{h['at']} {h['op']}" + (f" by {h['by']}" if h.get("by") else "")
                                      for h in p.get("history", [])))
    return EXIT_OK


_REVIEW_EXIT = {
    "approved": EXIT_OK, "rejected": EXIT_OK, "revoked": EXIT_OK, "expired": EXIT_OK,
    "not_found": EXIT_NOT_FOUND, "not_pending": EXIT_ERROR, "blocked": EXIT_DENIED,
    "rejected_secret": EXIT_REJECTED, "rejected_content": EXIT_REJECTED, "invalid": EXIT_ERROR, "error": EXIT_ERROR,
}
_REVIEW_MESSAGES = {
    "not_found": "not found: no such proposal or source",
    "not_pending": "not pending: this proposal is already {reason}",
    "blocked": "blocked: {text}",
    "rejected_secret": "rejected: a credential-like value was detected in the text. Nothing was stored; "
                       "edit it (--edit) or reject the proposal.",
    "rejected_content": "rejected: {text}. Nothing was stored.",
    "invalid": "invalid: {text}",
    "error": "error: {text}",
}


def _finish(result, args, ok_line: str) -> int:
    if _wants_json(args):
        _emit(result.as_dict())
    elif result.ok:
        print(ok_line)
    else:
        text = _REASONS.get(result.reason, result.reason or result.status)
        _err(_REVIEW_MESSAGES.get(result.status, "{text}").format(reason=result.reason, text=text))
    return _REVIEW_EXIT.get(result.status, EXIT_ERROR)


def _cmd_review_approve(args) -> int:
    reviewer = _reviewer()
    p = reviewer.show(args.proposal_id)
    if p is None:
        _err("not found: no such proposal")
        return EXIT_NOT_FOUND
    final = args.edit if args.edit is not None else p["text"]
    target = f"{p['memory_type']} ({p['scope']}{' ' + p['project_id'] if p.get('project_id') else ''})"
    prompt = (f"Approve {p['id']} from '{p['proposer']}' as {target}? This commits it to memory "
              f"(single-write approval, audited): \"{_clip_line(final, 120)}\"")
    if not _confirm(args, prompt):
        return EXIT_ERROR
    result = reviewer.approve(args.proposal_id, edit=args.edit, name=args.name)
    return _finish(result, args, f"approved  {result.proposal_id}  -> {result.external_ref}  "
                                 f"({result.write_status}{', superseded the previous version' if result.superseded else ''})")


def _cmd_review_reject(args) -> int:
    result = _reviewer().reject(args.proposal_id, args.reason)
    return _finish(result, args, f"rejected  {result.proposal_id}")


def _cmd_review_revoke(args) -> int:
    reviewer = _reviewer()
    if not _confirm(args, f"Revoke {args.ref}? It will stop being recalled for every agent (raw bytes are kept)."):
        return EXIT_ERROR
    result = reviewer.revoke(args.ref, args.reason)
    return _finish(result, args, f"revoked  {result.external_ref or result.source_id}  "
                                 "(raw bytes are kept; it will not be recalled)")


def _cmd_review_expire(args) -> int:
    result = _reviewer().expire()
    detail = result.detail or {}
    if _wants_json(args):
        _emit(result.as_dict())
        return _REVIEW_EXIT.get(result.status, EXIT_ERROR)
    if not result.ok:
        return _finish(result, args, "")
    expired, hidden = detail.get("proposals_expired", []), detail.get("active_hidden", [])
    print(f"expired {len(expired)} pending proposal(s)" + (": " + ", ".join(expired) if expired else ""))
    if hidden:
        print(f"{len(hidden)} approved item(s) are past active_ttl_days and hidden from recall/context:")
        for item in hidden:
            print(f"  {item['external_ref'] or item['source_id']}  (revoke: zero-mem review revoke ...)")
    return EXIT_OK


_HANDLERS = {
    "settings_show": _cmd_settings_show, "settings_set": _cmd_settings_set, "settings_unset": _cmd_settings_unset,
    "settings_validate": _cmd_settings_validate, "settings_path": _cmd_settings_path, "propose": _cmd_propose,
    "review_list": _cmd_review_list, "review_show": _cmd_review_show, "review_approve": _cmd_review_approve,
    "review_reject": _cmd_review_reject, "review_revoke": _cmd_review_revoke, "review_expire": _cmd_review_expire,
}


def dispatch(args) -> Optional[int]:
    name = getattr(args, "_learn_cmd", None)
    if name is None:
        return None
    from .memory import MemoryConfigError
    from .memory_layout import LayoutError
    from .provisioning import ProvisioningError

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
    except Exception as exc:  # noqa: BLE001 - never a traceback for the owner
        _err(f"unexpected error ({type(exc).__name__}); run zero-mem doctor")
        return EXIT_ERROR


__all__ = ["add_learning_parsers", "dispatch"]
