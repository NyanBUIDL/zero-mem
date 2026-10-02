"""Canonical ``peer_share`` events and their replay (ADR-V170-05).

Every pairing attempt, peer, grant, served manifest/fetch, pull, import and rejection is ONE append-only line in the
canonical memory stream (``event_type = "peer_share"``, ``m4.domain = "peer_share"``). :class:`ShareLog` replays them
incrementally (byte pre-filter, torn tail never trusted, malformed / foreign / forged-shape lines ignored, the same discipline as
``OperatorApprovalLookup``). No secret, token, key or source content is ever written.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from ..provisioning import append_canonical_event
from .util import FP_RE, PEER_ID_RE

EVENT_TYPE = "peer_share"
_NEEDLE = b'"peer_share"'
_CHUNK = 1 << 20
MAX_PEERS = 50
MAX_GRANTS_PER_PEER = 50


def now_iso(clock: Optional[Callable[[], datetime]] = None) -> str:
    moment = clock() if clock else datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_event(op: str, fields: dict, clock: Optional[Callable[[], datetime]] = None) -> dict:
    return {
        "event_id": f"peer-share-{uuid.uuid4().hex[:16]}",
        "event_type": EVENT_TYPE,
        "created_at": now_iso(clock),
        "m4": {"domain": EVENT_TYPE, "op": op, **fields},
    }


def _s(value: Any, limit: int = 200) -> Optional[str]:
    return value if isinstance(value, str) and 0 < len(value) <= limit else None


def _strs(value: Any, limit: int, each: int = 200) -> Optional[list]:
    if not isinstance(value, list) or len(value) > limit or any(_s(v, each) is None for v in value):
        return None
    return list(value)


class ShareLog:
    """Incremental replay of the ``peer_share`` events of one canonical stream (thread-safe)."""

    _instances: dict = {}
    _instances_lock = threading.Lock()

    @classmethod
    def for_layout(cls, layout) -> "ShareLog":
        key = os.fspath(layout.memory_stream)
        with cls._instances_lock:
            log = cls._instances.get(key)
            if log is None:
                if len(cls._instances) > 32:
                    cls._instances.clear()
                log = cls._instances[key] = cls(Path(layout.memory_stream))
            return log

    def __init__(self, stream: Path) -> None:
        self._stream = Path(stream)
        self._lock = threading.RLock()
        self._reset()

    def _reset(self) -> None:
        self.peers: dict[str, dict] = {}
        self.grants: dict[str, dict] = {}
        self.owners: dict[str, dict] = {}
        self.imported: dict[tuple, dict] = {}
        self.last_tombstone: dict[str, str] = {}
        self._file_id: Optional[tuple] = None
        self._offset = 0

    # ---------------------------------------------------------------- reading
    def refresh(self) -> None:
        with self._lock:
            try:
                info = os.stat(self._stream)
            except OSError:
                self._reset()
                return
            identity = (info.st_dev, info.st_ino)
            if identity != self._file_id or info.st_size < self._offset:
                self._reset()
                self._file_id = identity
            if info.st_size == self._offset:
                return
            try:
                fh = open(self._stream, "rb")
            except OSError:
                return
            with fh:
                fh.seek(self._offset)
                carry = b""
                consumed = 0
                while True:
                    chunk = fh.read(_CHUNK)
                    if not chunk:
                        break
                    buf = carry + chunk
                    *lines, carry = buf.split(b"\n")
                    for line in lines:
                        consumed += len(line) + 1
                        if _NEEDLE in line:
                            self._apply(line)
                self._offset += consumed

    def _apply(self, line: bytes) -> None:
        try:
            rec = json.loads(line)
        except ValueError:
            return
        if not isinstance(rec, dict) or rec.get("event_type") != EVENT_TYPE:
            return
        m4 = rec.get("m4")
        if not isinstance(m4, dict) or m4.get("domain") != EVENT_TYPE:
            return
        at = _s(rec.get("created_at"), 40) or ""
        op = m4.get("op")
        handler = _HANDLERS.get(op)
        if handler is not None:
            handler(self, m4, at)

    # -- handlers (each validates its own closed shape) -----------------------------------
    def _h_peer_add(self, m4: dict, at: str) -> None:
        pid, fp, der = _s(m4.get("peer_id"), 20), _s(m4.get("fp"), 64), _s(m4.get("cert_der_b64"), 4096)
        label = _s(m4.get("label"), 40)
        if not (pid and fp and der and label and PEER_ID_RE.fullmatch(pid) and FP_RE.fullmatch(fp)) or not fp.startswith(pid):
            return
        self.peers[pid] = {"peer_id": pid, "label": label, "fp": fp, "cert_der_b64": der, "created_at": at, "revoked_at": None}

    def _h_peer_revoke(self, m4: dict, at: str) -> None:
        peer = self.peers.get(_s(m4.get("peer_id"), 20) or "")
        if peer is not None and peer["revoked_at"] is None:
            peer["revoked_at"] = at

    def _h_grant_create(self, m4: dict, at: str) -> None:
        gid, pid = _s(m4.get("grant_id"), 40), _s(m4.get("peer_id"), 20)
        space = m4.get("space")
        projects = _strs(m4.get("projects", []), 50, 64)
        types = _strs(m4.get("types", []), 20, 20)
        prefixes = _strs(m4.get("ref_prefixes", []), 20, 200)
        expires = m4.get("expires_at")
        if not gid or not pid or projects is None or types is None or prefixes is None:
            return
        if space is not None and _s(space, 64) is None:
            return
        if space is None and not projects:
            return
        if expires is not None and _s(expires, 40) is None:
            return
        if gid in self.grants:
            return
        self.grants[gid] = {"grant_id": gid, "peer_id": pid, "space": space, "projects": projects, "types": types,
                            "ref_prefixes": prefixes, "expires_at": expires, "created_at": at, "revoked_at": None,
                            "source": _s(m4.get("source"), 20) or "owner"}

    def _h_grant_revoke(self, m4: dict, at: str) -> None:
        grant = self.grants.get(_s(m4.get("grant_id"), 40) or "")
        if grant is not None and grant["revoked_at"] is None:
            grant["revoked_at"] = at

    def _h_owner_add(self, m4: dict, at: str) -> None:
        pid, fp, label, host = _s(m4.get("peer_id"), 20), _s(m4.get("fp"), 64), _s(m4.get("label"), 40), _s(m4.get("host"), 253)
        port = m4.get("port")
        if not (pid and fp and label and host and PEER_ID_RE.fullmatch(pid) and FP_RE.fullmatch(fp)) or not fp.startswith(pid):
            return
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            return
        self.owners[pid] = {"peer_id": pid, "label": label, "fp": fp, "host": host, "port": port, "added_at": at, "removed_at": None,
                            "own_label": _s(m4.get("own_label"), 40)}

    def _h_owner_remove(self, m4: dict, at: str) -> None:
        owner = self.owners.get(_s(m4.get("peer_id"), 20) or "")
        if owner is not None:
            owner["removed_at"] = at

    def _h_import(self, m4: dict, at: str) -> None:
        owner, sid, digest = _s(m4.get("owner"), 20), _s(m4.get("source_id"), 128), _s(m4.get("digest"), 64)
        outcome = m4.get("outcome")
        if owner and sid and digest and outcome in ("stored", "proposed", "tombstoned", "withdrawn", "revoke_proposed"):
            self.imported[(owner, sid)] = {"digest": digest, "outcome": outcome, "ref": _s(m4.get("ref"), 512), "at": at,
                                           "proposal_id": _s(m4.get("proposal_id"), 64)}

    def _h_pull(self, m4: dict, at: str) -> None:
        owner, ts = _s(m4.get("owner"), 20), _s(m4.get("tombstones_until"), 40)
        if owner and ts:
            self.last_tombstone[owner] = ts

    # ---------------------------------------------------------------- queries
    def peer(self, peer_id: str) -> Optional[dict]:
        self.refresh()
        with self._lock:
            peer = self.peers.get(peer_id)
            return dict(peer) if peer else None

    def active_peers(self) -> dict:
        self.refresh()
        with self._lock:
            return {k: dict(v) for k, v in self.peers.items() if v["revoked_at"] is None}

    def grants_of(self, peer_id: Optional[str] = None, *, now: Optional[str] = None, active_only: bool = True) -> list:
        self.refresh()
        with self._lock:
            out = []
            for g in self.grants.values():
                if peer_id is not None and g["peer_id"] != peer_id:
                    continue
                if active_only and (g["revoked_at"] is not None or (g["expires_at"] and now and g["expires_at"] <= now)):
                    continue
                out.append(dict(g))
            return sorted(out, key=lambda g: (g["created_at"], g["grant_id"]))

    def owner(self, peer_id: str) -> Optional[dict]:
        self.refresh()
        with self._lock:
            rec = self.owners.get(peer_id)
            return dict(rec) if rec and rec["removed_at"] is None else None

    def active_owners(self) -> dict:
        self.refresh()
        with self._lock:
            return {k: dict(v) for k, v in self.owners.items() if v["removed_at"] is None}

    def imported_digest(self, owner: str, source_id: str) -> Optional[dict]:
        self.refresh()
        with self._lock:
            rec = self.imported.get((owner, source_id))
            return dict(rec) if rec else None

    def tombstone_cursor(self, owner: str) -> str:
        self.refresh()
        with self._lock:
            return self.last_tombstone.get(owner, "1970-01-01T00:00:00Z")


_HANDLERS = {
    "peer_add": ShareLog._h_peer_add, "peer_revoke": ShareLog._h_peer_revoke,
    "grant_create": ShareLog._h_grant_create, "grant_revoke": ShareLog._h_grant_revoke,
    "owner_add": ShareLog._h_owner_add, "owner_remove": ShareLog._h_owner_remove,
    "import": ShareLog._h_import, "pull": ShareLog._h_pull,
}


def append(layout, op: str, fields: dict, clock: Optional[Callable[[], datetime]] = None) -> dict:
    event = make_event(op, fields, clock)
    append_canonical_event(layout.memory_stream, event)
    return event


def read_events(layout, *, limit: int = 100, ops: Optional[set] = None) -> list:
    """The newest ``limit`` ``peer_share`` events (oldest first) for ``share audit``."""
    from ..provisioning import _iter_stream_events

    rows = []
    for rec in _iter_stream_events(layout.memory_stream, _NEEDLE):
        m4 = rec.get("m4")
        if rec.get("event_type") == EVENT_TYPE and isinstance(m4, dict) and m4.get("domain") == EVENT_TYPE:
            if ops is None or m4.get("op") in ops:
                rows.append({"at": rec.get("created_at"), "op": m4.get("op"),
                             **{k: v for k, v in m4.items() if k not in ("domain", "op", "cert_der_b64")}})
    return rows[-limit:]
