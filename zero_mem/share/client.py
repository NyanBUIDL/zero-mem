"""Joiner / puller side (ADR-V170-05): ``join`` pairs with an owner's invite, ``pull`` copies what the owner granted.

Every connection is TLS 1.3 with the owner's certificate pinned; nothing is sent before the pin matches; the owner is as
untrusted as any peer (strict parsers, local caps, local scan, quarantine)."""
from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import quote

from ..memory import LEARNED_TYPES, Memory
from . import PROTOCOL_VERSION, SNI_PAIR, SNI_PEER, ShareError, events as ev, httpio, importer, protocol, tls
from .invite import parse_invite
from .util import clean_label, resolve_lan_host

_JSON_CALL_TIMEOUT = 30.0


def _node_data_root(node):
    return node.layout.data_root if node.layout.explicit else None


# ---------------------------------------------------------------------------------------------
# join
# ---------------------------------------------------------------------------------------------
def join(node, code: str, label: Optional[str] = None) -> dict:
    node.require_active()
    invite = parse_invite(code)
    own_label = clean_label(label, default=node.own_label())
    identity = node.identity()
    addr = resolve_lan_host(invite.host, invite.port)
    sock = tls.connect_pinned(addr, invite.port, invite.server_fp, identity=identity, sni=SNI_PAIR, timeout=10.0)
    try:
        body = protocol.dump_json({"v": PROTOCOL_VERSION, "token": invite.token, "label": own_label,
                                   "cert_der_b64": base64.b64encode(identity.cert_der).decode("ascii")})
        status, data = httpio.request(sock, "POST", "/v1/pair", body, max_response=8 * 1024, timeout=_JSON_CALL_TIMEOUT)
    finally:
        try:
            sock.close()
        except OSError:
            pass
    if status == 429:
        raise ShareError("pairing_locked", "the owner's pairing endpoint is locked (too many failed attempts); ask for a new invite")
    if status != 200:
        raise ShareError("pairing_refused", "the owner refused the pairing (the invite may be used, expired or wrong)")
    reply = protocol.parse_pair_response(data)
    if reply["peer_id"] != invite.server_fp[:20]:
        raise ShareError("pairing_failed", "the owner's identity does not match the invite")
    try:
        owner_label = clean_label(reply["label"])
    except ShareError:
        owner_label = invite.label
    node.audit_event("owner_add", peer_id=reply["peer_id"], label=owner_label, fp=invite.server_fp, host=invite.host,
                     port=reply["service_port"], own_label=own_label)
    return {"status": "joined", "owner_peer_id": reply["peer_id"], "owner_label": owner_label, "host": invite.host,
            "port": reply["service_port"], "own_peer_id": identity.peer_id, "own_label": own_label}


# ---------------------------------------------------------------------------------------------
# pull
# ---------------------------------------------------------------------------------------------
@dataclass
class PullReport:
    owner: dict
    plan: dict
    dry_run: bool = False
    aborted: bool = False
    stored: int = 0
    proposed: int = 0
    unchanged: int = 0
    rejected: list = field(default_factory=list)
    tombstoned: int = 0
    tombstones_skipped: int = 0
    withdrawn: int = 0
    revoke_proposed: list = field(default_factory=list)
    bytes: int = 0
    omitted_by_owner: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"owner": {k: self.owner[k] for k in ("peer_id", "label")}, "dry_run": self.dry_run, "aborted": self.aborted,
                "plan": {"summary": self.plan["summary"], "invalid_entries": self.plan["invalid_entries"],
                         "bytes": self.plan["bytes"], "rows": self.plan["rows"]},
                "stored": self.stored, "proposed": self.proposed, "unchanged": self.unchanged,
                "rejected": self.rejected, "tombstoned": self.tombstoned, "tombstones_skipped": self.tombstones_skipped,
                "withdrawn": self.withdrawn, "revoke_proposed": self.revoke_proposed,
                "bytes": self.bytes, "omitted_by_owner": self.omitted_by_owner}


def _call(node, owner: dict, method: str, path: str, body: Optional[bytes], *, max_response: int) -> bytes:
    addr = resolve_lan_host(owner["host"], owner["port"])
    sock = tls.connect_pinned(addr, owner["port"], owner["fp"], identity=node.identity(), sni=SNI_PEER, timeout=10.0)
    try:
        status, data = httpio.request(sock, method, path, body, max_response=max_response, timeout=_JSON_CALL_TIMEOUT)
    finally:
        try:
            sock.close()
        except OSError:
            pass
    if status == 403:
        raise ShareError("access_revoked", "the owner no longer trusts this machine (access revoked)")
    if status == 429:
        raise ShareError("rate_limited", "the owner is rate limiting this machine; try again later")
    if status == 503:
        raise ShareError("owner_sharing_off", "the owner's sharing is switched off")
    if status != 200:
        raise ShareError("owner_error", f"the owner answered with HTTP {status}")
    return data


def pull(node, owner_ref: str, *, dry_run: bool = False, confirm: Optional[Callable[[dict], bool]] = None) -> PullReport:
    node.require_active()
    cfg = node.settings()
    owner = node.resolve_owner(owner_ref)
    log = node.log
    manifest = protocol.parse_manifest(_call(node, owner, "GET", "/v1/manifest", None, max_response=4 << 20))
    pln = importer.plan(manifest["entries"], len(manifest["rejected"]), owner_id=owner["peer_id"], log=log,
                        max_pull_sources=cfg.max_pull_sources, max_source_bytes=cfg.max_source_bytes,
                        max_total_bytes=cfg.max_total_bytes)
    report = PullReport(owner=owner, plan=pln, dry_run=dry_run, omitted_by_owner=manifest["omitted"],
                        unchanged=pln["summary"].get("unchanged", 0))
    if dry_run:
        return report
    todo = [r for r in pln["rows"] if r["action"] in ("new", "changed")]
    if todo and confirm is not None and not confirm(pln):
        report.aborted = True
        return report
    proposer = Memory.open(importer.PEER_IMPORT_PROFILE, data_root=_node_data_root(node), clock=node._clock,
                           settings_path=node._settings_path)
    try:
        _fetch_all(node, owner, todo, report, cfg, proposer)
        _apply_tombstones(node, owner, report, proposer)
    finally:
        proposer.close()
    node.audit_event("pull", owner=owner["peer_id"], new=sum(1 for r in todo if r["action"] == "new"),
                     changed=sum(1 for r in todo if r["action"] == "changed"), stored=report.stored,
                     proposed=report.proposed, rejected=len(report.rejected), bytes=report.bytes,
                     tombstoned=report.tombstoned, tombstones_until=report.plan.get("tombstones_until") or ev.now_iso(node._clock))
    return report


def _reject(node, owner, report, row, code: str) -> None:
    report.rejected.append({"source_id": row["source_id"], "ref": row["ref"], "reason": code})
    try:
        node.audit_event("reject", owner=owner["peer_id"], source_id=row["source_id"], reason=code)
    except Exception:  # noqa: BLE001
        pass


def _fetch_all(node, owner, todo, report, cfg, proposer) -> None:
    by_id = {r["source_id"]: r for r in todo}
    pending = [r["source_id"] for r in todo]
    total, count, rounds = 0, 0, 0
    while pending and rounds < 200:
        rounds += 1
        batch, pending = pending[:20], pending[20:]
        body = protocol.dump_json({"v": PROTOCOL_VERSION, "source_ids": batch})
        reply = protocol.parse_fetch_response(
            _call(node, owner, "POST", "/v1/fetch", body, max_response=(cfg.max_source_bytes * 4 // 3 + 4096) * 20 + 65536),
            max_bytes=(cfg.max_source_bytes * 4 // 3 + 4096) * 20 + 65536)
        got = set()
        for fetched in reply["sources"]:
            sid = fetched["source_id"]
            row = by_id.get(sid)
            if row is None or sid not in batch or sid in got:  # unsolicited or duplicated: never trusted
                continue
            got.add(sid)
            if count >= cfg.max_pull_sources or total + row["size"] > cfg.max_total_bytes:
                _reject(node, owner, report, row, "cap_reached")
                continue
            try:
                content = importer.verify_fetched(fetched, row, max_source_bytes=cfg.max_source_bytes)
                outcome, detail = importer.import_source(node, owner, row, content, proposer=proposer)
            except ShareError as exc:
                _reject(node, owner, report, row, exc.code)
                continue
            count += 1
            total += len(content)
            report.bytes += len(content)
            if outcome == "stored":
                report.stored += 1
            else:
                report.proposed += 1
            node.audit_event("import", owner=owner["peer_id"], source_id=sid, digest=row["digest"], outcome=outcome,
                             ref=importer.local_ref(owner["peer_id"], row["ref"]), size=len(content),
                             proposal_id=detail.get("proposal_id"))
        for sid in reply["missing"]:
            if sid in by_id and sid in batch:
                _reject(node, owner, report, by_id[sid], "not_served")
                got.add(sid)
        deferred = [s for s in reply["deferred"] if s in batch]
        pending = deferred + pending if deferred else pending
        for sid in batch:  # asked for but neither served, missing nor deferred: protocol violation, report once
            if sid not in got and sid not in deferred:
                _reject(node, owner, report, by_id[sid], "not_returned")
        if deferred and not reply["sources"]:
            break  # the owner made no progress: stop rather than loop


def _withdraw_learned(node, owner, tomb, prior, report, proposer) -> None:
    """The owner forgot a rule / decision / gotcha that this memory imported as a PROPOSAL.

    Pending proposal: withdrawn. Already approved by the local owner: never deleted silently; a revoke is only PROPOSED (an audit
    event and ``report.revoke_proposed``; the local owner decides with ``zero-mem review revoke``). Anything else: nothing to do."""
    from ..learning import _log_for

    ref = importer.local_ref(owner["peer_id"], tomb["ref"])
    pid = prior.get("proposal_id")
    proposal = _log_for(node.memory).refresh().get(pid) if pid else None
    if proposal is None:
        report.tombstones_skipped += 1
        return
    if proposal.status == "pending":
        if proposer.withdraw(pid).status != "withdrawn":
            report.tombstones_skipped += 1
            return
        outcome = "withdrawn"
        report.withdrawn += 1
    elif proposal.status == "approved":
        outcome = "revoke_proposed"
        report.revoke_proposed.append({"proposal_id": pid, "ref": proposal.external_ref or ref, "source_id": proposal.source_id,
                                       "owner": owner["peer_id"], "owner_label": owner["label"]})
    else:  # rejected / expired / revoked / superseded: already not active
        outcome = "tombstoned"
    node.audit_event("import", owner=owner["peer_id"], source_id=tomb["source_id"], digest=prior["digest"], outcome=outcome,
                     ref=ref, proposal_id=pid)


def _apply_tombstones(node, owner, report, proposer) -> None:
    since = node.log.tombstone_cursor(owner["peer_id"])
    until = since
    for _round in range(5):
        data = _call(node, owner, "GET", "/v1/tombstones?since=" + quote(since, safe=""), None, max_response=1 << 20)
        reply = protocol.parse_tombstones(data)
        for tomb in reply["tombstones"]:
            prior = node.log.imported_digest(owner["peer_id"], tomb["source_id"])
            if prior is None or prior["outcome"] in ("tombstoned", "withdrawn", "revoke_proposed"):
                continue
            if tomb["memory_type"] in LEARNED_TYPES or prior["outcome"] == "proposed":
                _withdraw_learned(node, owner, tomb, prior, report, proposer)
                continue
            result = node.memory._operator_forget(importer.local_ref(owner["peer_id"], tomb["ref"]))
            if result.status in ("forgotten", "already_forgotten"):
                node.audit_event("import", owner=owner["peer_id"], source_id=tomb["source_id"], digest=prior["digest"],
                                 outcome="tombstoned", ref=importer.local_ref(owner["peer_id"], tomb["ref"]))
                report.tombstoned += 1
        until = reply["until"]
        if not reply["more"]:
            break
        since = until
    report.plan["tombstones_until"] = until
