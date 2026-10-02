"""Owner side: what a paired peer may read, decided by the existing authorization pipeline (ADR-V170-05, section 6).

A peer is the profile ``peer:<peer_id>``. For every active grant target (a knowledge space or a project) the same
``AccessRequest(READ, corpus_unit, include_global=False)`` + READ ``AuthorizedReadGrant`` pair goes through
``AuthorizedReadService.corpus_scope``; a source is eligible only if that scope allows its ``(profile, project, space)``.
The grant's type / prefix filters only narrow the result. Forgotten, secret-sensitivity, expired, peer-imported, oversized
and scan-failing sources are never served; every served manifest / fetch / skip is audited.
"""
from __future__ import annotations

import base64
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .. import learning_settings as ls
from ..memory import MEMORY_TYPES, PEER_IMPORT_PROFILE, PEER_REF_PREFIX, PEER_SPACE_PREFIX
from . import PROTOCOL_VERSION, ShareError
from . import events as ev
from .protocol import KIND_RE, MAX_FETCH_IDS, MAX_MANIFEST_ENTRIES, MAX_TOMBSTONES, TS_RE, check_ref

FETCH_RESPONSE_BYTES = 8 * 1024 * 1024
_SCAN_CACHE_MAX = 4096


def peer_profile(peer_id: str) -> str:
    return f"peer:{peer_id}"


def scan_outgoing(content: bytes) -> bool:
    """Central prescan of bytes that are about to leave the machine (True = safe)."""
    from src.redaction.prescan import looks_like_zip, scan_bytes, scan_zip_members

    if not scan_bytes(content).safe:
        return False
    if looks_like_zip(content) and not scan_zip_members(content).safe:
        return False
    return True


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(text: str) -> datetime:
    if not isinstance(text, str) or not TS_RE.fullmatch(text):
        raise ShareError("invalid_message", "invalid timestamp")
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class OwnerService:
    def __init__(self, memory, log: ev.ShareLog, *, peer_id: str, settings_path=None,
                 clock: Optional[Callable[[], datetime]] = None) -> None:
        self._memory = memory
        self._log = log
        self._peer_id = peer_id
        self._settings_path = settings_path
        self._clock = clock
        self._scan_cache: dict = {}
        self._skip_audited: set = set()
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- plumbing
    def _now(self) -> datetime:
        return (self._clock() if self._clock else datetime.now(timezone.utc)).astimezone(timezone.utc)

    def settings(self):
        return ls.load_settings(self._settings_path)

    def audit(self, op: str, **fields: Any) -> None:
        ev.append(self._memory.layout, op, fields, self._clock)

    def _safe(self, content: bytes, digest: str) -> bool:
        with self._lock:
            hit = self._scan_cache.get(digest)
        if hit is None:
            hit = scan_outgoing(content)
            with self._lock:
                if len(self._scan_cache) >= _SCAN_CACHE_MAX:
                    self._scan_cache.clear()
                self._scan_cache[digest] = hit
        return hit

    def _skip(self, peer_id: str, source_id: str, digest: str, reason: str) -> None:
        key = (peer_id, source_id, digest, reason)
        with self._lock:
            if key in self._skip_audited:
                return
            if len(self._skip_audited) > 4096:
                self._skip_audited.clear()
            self._skip_audited.add(key)
        try:
            self.audit("skip_source", peer_id=peer_id, source_id=source_id, reason=reason)
        except Exception:  # noqa: BLE001 - the skip itself already protects; the audit is best effort here
            pass

    # ---------------------------------------------------------------- authorization
    def _targets(self, peer_id: str, grants: Optional[list] = None) -> list:
        """``[(grant, AuthorizedCorpusScope)]`` - one per active grant target the policy authorizes.

        ``grants`` replaces the peer's logged grants (used only to PREVIEW a grant that does not exist yet)."""
        from src.access import AccessRequest, AuthorizedReadService
        from src.access.grants import AuthorizedReadGrant

        peer = self._log.peer(peer_id)
        if peer is None or peer["revoked_at"] is not None:
            return []
        profile = peer_profile(peer_id)
        service = AuthorizedReadService(None, profile)
        now = _iso(self._now())
        out = []
        for grant in (grants if grants is not None else self._log.grants_of(peer_id, now=now)):
            targets = ([("knowledge_space", grant["space"])] if grant["space"] else []) + \
                      [("project", p) for p in grant["projects"]]
            for target_type, target_id in targets:
                if target_type == "knowledge_space" and str(target_id).startswith(PEER_SPACE_PREFIX):
                    continue  # no transitive re-sharing of quarantined copies
                kwargs = {"knowledge_space_ids": [target_id]} if target_type == "knowledge_space" else {"project_ids": [target_id]}
                request = AccessRequest(operation="READ", requesting_profile_id=profile, resource_type="corpus_unit",
                                        include_global=False, **kwargs)
                read_grant = AuthorizedReadGrant(
                    grant_id=grant["grant_id"], subject_profile=profile, operation="READ",
                    target_type=target_type, target_id=target_id, resource_types=["corpus_unit"])
                scope = service.corpus_scope(request, grants=[read_grant])
                if scope is not None:
                    out.append((grant, scope))
        return out

    def _latest_records(self) -> list:
        with self._memory._lock:
            registry, blobs = self._memory._corpus()
            registry.refresh()
            latest: dict = {}
            for rec in registry.all_records():
                latest[rec.source_id] = rec
            return list(latest.values())

    @staticmethod
    def _grant_allows(grant: dict, record, mtype: str) -> bool:
        if grant["types"] and mtype not in grant["types"]:
            return False
        if grant["ref_prefixes"] and not any(record.external_ref.startswith(p) for p in grant["ref_prefixes"]):
            return False
        return True

    def _candidates(self, peer_id: str, *, deleted: bool, only_ids=None, grants: Optional[list] = None) -> tuple:
        """``([(record, mtype, grant_id)], omitted)`` after scope + grant filters + cheap record checks (no blob reads)."""
        from src.corpus.contracts import is_withheld_sensitivity

        targets = self._targets(peer_id, grants)
        omitted: dict = {}
        if not targets:
            return [], omitted
        expired = self._memory._expired_sources()
        out = []
        for rec in self._latest_records():
            if only_ids is not None and rec.source_id not in only_ids:
                continue
            if (rec.lifecycle_status == "deleted") != deleted:
                continue
            if rec.profile_id == PEER_IMPORT_PROFILE or (rec.knowledge_space_id or "").startswith(PEER_SPACE_PREFIX) \
                    or rec.external_ref.startswith(PEER_REF_PREFIX):
                continue
            mtype = (rec.custom_meta or {}).get("memory_type")
            if mtype not in MEMORY_TYPES:
                continue
            match = None
            for grant, scope in targets:
                if scope.allows(rec.profile_id, rec.project_id, rec.knowledge_space_id) and self._grant_allows(grant, rec, mtype):
                    match = grant["grant_id"]
                    break
            if match is None:
                continue
            if is_withheld_sensitivity(rec.sensitivity):  # also for tombstones: never name a ref the peer could not have had
                omitted["secret"] = omitted.get("secret", 0) + 1
                continue
            if not deleted:
                if rec.source_id in expired:
                    omitted["expired"] = omitted.get("expired", 0) + 1
                    continue
            try:
                check_ref(rec.external_ref)
                if not KIND_RE.fullmatch(rec.kind or ""):
                    raise ShareError("unsafe_ref")
            except ShareError:
                omitted["unsafe_ref"] = omitted.get("unsafe_ref", 0) + 1
                continue
            out.append((rec, mtype, match))
        out.sort(key=lambda item: (item[0].external_ref, item[0].source_id))
        return out, omitted

    def _servable(self, peer_id: str, only_ids=None, grants: Optional[list] = None) -> tuple:
        """``([(entry dict, content bytes)], omitted)``: candidates whose blob is intact, small enough and scan-clean."""
        cfg = self.settings()
        candidates, omitted = self._candidates(peer_id, deleted=False, only_ids=only_ids, grants=grants)
        out = []
        with self._memory._lock:
            _registry, blobs = self._memory._corpus()
        for rec, mtype, _grant_id in candidates:
            if rec.blob_ref is None:
                omitted["no_blob"] = omitted.get("no_blob", 0) + 1
                continue
            try:
                content = blobs.get(rec.blob_ref)
            except Exception:
                omitted["unreadable"] = omitted.get("unreadable", 0) + 1
                continue
            if len(content) > cfg.max_source_bytes:
                omitted["too_large"] = omitted.get("too_large", 0) + 1
                continue
            if not self._safe(content, rec.blob_ref) or not self._safe(rec.external_ref.encode("utf-8"), "ref:" + rec.external_ref):
                omitted["scan_failed"] = omitted.get("scan_failed", 0) + 1
                self._skip(peer_id, rec.source_id, rec.blob_ref, "secret_detected")
                continue
            entry = {"source_id": rec.source_id, "ref": rec.external_ref, "memory_type": mtype, "kind": rec.kind,
                     "version": rec.source_version_id or rec.content_hash[:64], "digest": rec.blob_ref,
                     "size": len(content), "updated_at": rec.created_at}
            out.append((entry, content))
            if len(out) >= MAX_MANIFEST_ENTRIES:
                omitted["manifest_cap"] = omitted.get("manifest_cap", 0) + 1
                break
        return out, omitted

    # ---------------------------------------------------------------- endpoints
    def manifest(self, peer_id: str) -> dict:
        servable, omitted = self._servable(peer_id)
        self.audit("manifest", peer_id=peer_id, count=len(servable), omitted=omitted)
        return {"v": PROTOCOL_VERSION, "peer_id": self._peer_id, "generated_at": _iso(self._now()),
                "sources": [entry for entry, _content in servable], "omitted": omitted}

    def fetch(self, peer_id: str, ids: list) -> dict:
        wanted = list(ids)[:MAX_FETCH_IDS]
        servable, _omitted = self._servable(peer_id, only_ids=set(wanted))
        by_id = {entry["source_id"]: (entry, content) for entry, content in servable}
        sources, missing, deferred, total = [], [], [], 0
        for sid in wanted:
            item = by_id.get(sid)
            if item is None:
                missing.append(sid)
                continue
            entry, content = item
            if total + len(content) > FETCH_RESPONSE_BYTES and sources:
                deferred.append(sid)
                continue
            total += len(content)
            sources.append({**entry, "content_b64": base64.b64encode(content).decode("ascii")})
        self.audit("fetch", peer_id=peer_id, count=len(sources), bytes=total, missing=len(missing), deferred=len(deferred))
        return {"v": PROTOCOL_VERSION, "sources": sources, "missing": missing, "deferred": deferred}

    def tombstones(self, peer_id: str, since: str) -> dict:
        since_dt = parse_ts(since)
        candidates, _omitted = self._candidates(peer_id, deleted=True)
        rows = []
        for rec, mtype, _grant_id in candidates:
            try:
                when = parse_ts(rec.created_at)
            except ShareError:
                continue
            if not self._safe(rec.external_ref.encode("utf-8"), "ref:" + rec.external_ref):
                continue  # same outgoing scan the manifest applies to a ref
            if when > since_dt:
                rows.append((when, rec, mtype))
        rows.sort(key=lambda r: (r[0], r[1].source_id))
        more = len(rows) > MAX_TOMBSTONES
        rows = rows[:MAX_TOMBSTONES]
        until = rows[-1][1].created_at if rows else since
        self.audit("tombstones", peer_id=peer_id, count=len(rows))
        return {"v": PROTOCOL_VERSION, "until": until, "more": more,
                "tombstones": [{"source_id": r.source_id, "ref": r.external_ref, "memory_type": mt, "forgotten_at": r.created_at}
                               for _when, r, mt in rows]}

    # ---------------------------------------------------------------- owner previews
    def preview_counts(self, peer_id: str) -> dict:
        """What this peer could read right now: ``{"sources": n, "bytes": b}`` (no content, for ``share grants``)."""
        servable, omitted = self._servable(peer_id)
        return {"sources": len(servable), "bytes": sum(len(c) for _e, c in servable), "omitted": omitted}

    def preview_spec(self, peer_id: str, spec: dict, *, limit: int = 20) -> dict:
        """Exactly what a grant that does NOT exist yet would let the peer read (same code path as serving; nothing is
        written and no skip is audited): counts by type, the first ``limit`` references, the omitted counters."""
        pseudo = {"grant_id": "sg-preview", "peer_id": peer_id, "space": spec["space"], "projects": list(spec["projects"]),
                  "types": list(spec["types"]), "ref_prefixes": list(spec["ref_prefixes"]), "revoked_at": None,
                  "expires_at": None}
        servable, omitted = self._servable(peer_id, grants=[pseudo])
        by_type: dict = {}
        for entry, _content in servable:
            by_type[entry["memory_type"]] = by_type.get(entry["memory_type"], 0) + 1
        return {"sources": len(servable), "bytes": sum(len(c) for _e, c in servable), "by_type": by_type,
                "refs": [{"ref": e["ref"], "memory_type": e["memory_type"], "size": e["size"]} for e, _c in servable[:limit]],
                "omitted": omitted}
