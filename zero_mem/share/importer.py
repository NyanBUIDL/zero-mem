"""Receiving side: planning a pull and importing ONE fetched source safely (ADR-V170-05, section 7).

Everything an owner sends is untrusted. A source is accepted only after: it was requested and matches the manifest entry; strict
base64; declared size == real size and <= the local cap; SHA-256 == the manifest digest; the reference grammar (no traversal, no
control characters, scheme/type agreement); the full local secret scan. Then it is stored in the quarantine space
(``ks-peer-<owner>``) or - for ``rule`` / ``decision`` / ``gotcha`` - becomes a local PROPOSAL (never active memory).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional

from ..memory import LEARNED_TYPES, PEER_IMPORT_PROFILE, PEER_SPACE_PREFIX
from . import ShareError
from . import events as ev
from .owner import scan_outgoing
from .protocol import check_ref
from .util import b64_decode_strict

_NAME_PART = 128


def space_of(owner_id: str) -> str:
    return PEER_SPACE_PREFIX + owner_id


def local_ref(owner_id: str, ref: str) -> str:
    scheme, mtype, rest = check_ref(ref)
    path = rest if scheme == "file" else f"{mtype}/{rest}"
    out = f"peer://{owner_id}/{scheme}/{path}"
    if len(out) > 512:
        raise ShareError("unsafe_ref", "a reference from the peer is too long")
    return out


def proposal_name(owner_id: str, ref: str) -> str:
    _scheme, mtype, rest = check_ref(ref)
    return f"peer-{owner_id[:8]}-{rest.replace('/', '-')}"[:_NAME_PART].rstrip("-.")


def plan(entries: list, rejected: int, *, owner_id: str, log: ev.ShareLog, max_pull_sources: int, max_source_bytes: int,
         max_total_bytes: int) -> dict:
    """The pull plan: one row per manifest entry with its action and reason; caps applied in manifest order."""
    rows, count, total = [], 0, 0
    for entry in entries:
        row = {"source_id": entry["source_id"], "ref": entry["ref"], "memory_type": entry["memory_type"],
               "size": entry["size"], "digest": entry["digest"], "kind": entry["kind"], "action": None, "reason": None}
        prior = log.imported_digest(owner_id, entry["source_id"])
        if entry["size"] > max_source_bytes:
            row.update(action="skip", reason="too_large")
        elif prior is not None and prior["digest"] == entry["digest"] and prior["outcome"] in ("stored", "proposed"):
            row.update(action="unchanged")
        elif count >= max_pull_sources:
            row.update(action="defer", reason="max_pull_sources")
        elif total + entry["size"] > max_total_bytes:
            row.update(action="defer", reason="max_total_bytes")
        else:
            kind = "changed" if prior is not None and prior["outcome"] in ("stored", "proposed") else "new"
            row.update(action=kind, reason="proposal" if entry["memory_type"] in LEARNED_TYPES else None)
            count += 1
            total += entry["size"]
        rows.append(row)
    summary: dict = {}
    for row in rows:
        summary[row["action"]] = summary.get(row["action"], 0) + 1
    return {"rows": rows, "summary": summary, "invalid_entries": rejected,
            "bytes": total, "sources": count}


def verify_fetched(fetched: dict, row: dict, *, max_source_bytes: int) -> bytes:
    """The decoded, verified content of one fetched source, or :class:`ShareError` (code = reason)."""
    for key in ("ref", "memory_type", "digest", "size", "kind"):
        if fetched[key] != row[key]:
            raise ShareError("manifest_mismatch", "the fetched source does not match its manifest entry")
    content = b64_decode_strict(fetched["content_b64"], max_bytes=min(row["size"], max_source_bytes))
    if len(content) != row["size"]:
        raise ShareError("size_mismatch", "the fetched content has a different size than announced")
    if hashlib.sha256(content).hexdigest() != row["digest"]:
        raise ShareError("digest_mismatch", "the fetched content does not match its digest")
    if not scan_outgoing(content):
        raise ShareError("secret_detected", "a credential-like value was detected in the fetched content")
    return content


def import_source(node, owner: dict, row: dict, content: bytes, *, proposer) -> tuple:
    """Store / propose one verified source: ``(outcome, detail)`` with outcome ``stored`` / ``proposed``; raises ``ShareError``."""
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ref = local_ref(owner["peer_id"], row["ref"])
    mtype = row["memory_type"]
    if mtype in LEARNED_TYPES:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            raise ShareError("not_text", "a learned-type source must be UTF-8 text") from None
        result = proposer.propose(
            text, mtype, name=proposal_name(owner["peer_id"], row["ref"]), scope="shared",
            evidence=[f"from peer {owner['label']} ({owner['peer_id'][:8]})", f"original ref {row['ref']}"[:200],
                      f"digest {row['digest'][:16]}"],
            source="peer")
        if result.status in ("proposed", "merged"):
            return "proposed", {"proposal_id": result.proposal_id,
                                "superseded": _supersede(node, owner, row, result.proposal_id, proposer)}
        raise ShareError(result.reason or result.status, "the proposal was refused: " + str(result.reason or result.status))
    provenance = {"peer": owner["peer_id"], "peer_label": owner["label"], "original_ref": row["ref"],
                  "digest": row["digest"], "fetched_at": fetched_at, "tool": "peer_pull"}
    result = node.memory._import_peer_source(
        content=content, kind=row["kind"], memory_type=mtype, external_ref=ref, space=space_of(owner["peer_id"]),
        provenance=provenance)
    if result.status in ("created", "updated", "unchanged"):
        return "stored", {"status": result.status, "ref": ref}
    raise ShareError(result.reason or result.status, "the source was rejected: " + str(result.reason or result.status))


def _supersede(node, owner: dict, row: dict, new_pid: Optional[str], proposer) -> list:
    """The owner changed a rule / decision / gotcha: withdraw every EARLIER still-pending proposal of the same remote source so
    only the newest version stays reviewable. An approved earlier version is never touched (a tombstone later proposes its revoke)."""
    from ..learning import _log_for

    prior = node.log.imported_digest(owner["peer_id"], row["source_id"]) or {}
    old = [p for p in (prior.get("proposal_ids") or ([prior["proposal_id"]] if prior.get("proposal_id") else [])) if p != new_pid]
    if not old:
        return []
    log, done = _log_for(node.memory).refresh(), []
    for pid in old:
        proposal = log.get(pid)
        if proposal is not None and proposal.status == "pending" and proposer.withdraw(pid).status == "withdrawn":
            done.append(pid)
    return done
