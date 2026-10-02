"""One memory's sharing node: settings gate, identity, canonical log, invites, owner service and the owner's management
operations (peers, grants, revoke, audit). The server, the client and the CLI are thin shells over this class."""
from __future__ import annotations

import re
import socket
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from .. import learning_settings as ls
from ..memory import Memory
from ..memory_layout import Layout
from . import DEFAULT_PORT, ShareDisabledError, ShareError, events as ev, identity as ident
from .grants import validate_grant_spec
from .invite import DEFAULT_INVITE_SECONDS, Invite, InviteStore
from .util import PEER_ID_RE, clean_label, detect_lan_address

SERVICE_PROFILE = "zm-share"


def default_label() -> str:
    raw = re.sub(r"[^A-Za-z0-9 ._@-]", "-", socket.gethostname() or "")[:40].strip(" .-_@")
    return raw if raw and raw[0].isalnum() else "zero-mem"


class ShareNode:
    def __init__(self, memory: Memory, *, settings_path=None, clock: Optional[Callable[[], datetime]] = None,
                 label: Optional[str] = None) -> None:
        self.memory = memory
        self.layout: Layout = memory.layout
        self._settings_path = settings_path
        self._clock = clock
        self._label = clean_label(label) if label else None
        self.log = ev.ShareLog.for_layout(self.layout)
        self._owner_service = None
        self._identity = None

    @classmethod
    def open(cls, data_root=None, *, settings_path=None, clock=None, label: Optional[str] = None) -> "ShareNode":
        memory = Memory.open(SERVICE_PROFILE, data_root=data_root, clock=clock, settings_path=settings_path)
        return cls(memory, settings_path=settings_path, clock=clock, label=label)

    def close(self) -> None:
        self.memory.close()

    def __enter__(self) -> "ShareNode":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # ---------------------------------------------------------------- gate
    def settings(self):
        return ls.load_settings(self._settings_path)

    def require_active(self) -> None:
        cfg = self.settings()
        if not cfg.valid:
            raise ShareDisabledError("the settings file is unusable, so sharing is off (zero-mem settings validate)")
        if cfg.kill_switch:
            raise ShareDisabledError("the kill switch is on (settings: safety.kill_switch)")
        if not cfg.sharing_enabled:
            raise ShareDisabledError("peer sharing is off; enable it with: zero-mem settings set sharing.enabled true")

    def now(self) -> datetime:
        return (self._clock() if self._clock else datetime.now(timezone.utc)).astimezone(timezone.utc)

    def own_label(self) -> str:
        return self._label or default_label()

    def audit_event(self, op: str, **fields) -> dict:
        return ev.append(self.layout, op, fields, self._clock)

    # ---------------------------------------------------------------- identity / stores
    def identity(self):
        if self._identity is None:
            self._identity = ident.ensure_identity(self.layout, self.own_label())
        return self._identity

    def invites(self) -> InviteStore:
        return InviteStore(ident.share_dir(self.layout))

    def owner_service(self):
        if self._owner_service is None:
            from .owner import OwnerService

            self._owner_service = OwnerService(self.memory, self.log, peer_id=self.identity().peer_id,
                                               settings_path=self._settings_path, clock=self._clock)
        return self._owner_service

    # ---------------------------------------------------------------- owner: invites and pairing
    def create_invite(self, *, host: Optional[str] = None, port: int = DEFAULT_PORT, expires_in: int = DEFAULT_INVITE_SECONDS,
                      label: Optional[str] = None, grants: Optional[list] = None) -> Invite:
        self.require_active()
        specs = [validate_grant_spec(g) for g in (grants or [])]
        if host is None:
            host = detect_lan_address()
            if host is None:
                raise ShareError("no_lan_address", "cannot detect this machine's LAN address; pass --host")
        identity = self.identity()
        invite, invite_id = self.invites().create(
            host=host, port=port, server_fp=identity.fingerprint, label=clean_label(label, default=self.own_label()),
            expires_in=expires_in, grants=specs)
        self.audit_event("invite_create", invite_id=invite_id, expires=invite.expires, grants=len(specs))
        return invite

    def register_peer(self, der: bytes, label: str, record: dict, *, remote: str = "") -> str:
        """Record a successfully paired peer and the grants its invite offered (called by the pairing endpoint)."""
        import base64

        peer_id, fp = ident.peer_id_of_der(der), ident.fingerprint_of_der(der)
        if peer_id not in self.log.active_peers() and len(self.log.active_peers()) >= ev.MAX_PEERS:
            raise ShareError("too_many_peers", "too many paired peers")
        if peer_id == self.identity().peer_id:
            raise ShareError("invalid_certificate", "a peer cannot be this memory itself")
        self.audit_event("peer_add", peer_id=peer_id, label=label, fp=fp, cert_der_b64=base64.b64encode(der).decode("ascii"),
                         invite_id=record.get("invite_id"))
        for spec in record.get("grants") or []:
            self._append_grant(peer_id, validate_grant_spec(spec), source="invite")
        self.audit_event("pair_attempt", ok=True, peer_id=peer_id, invite_id=record.get("invite_id"), remote=remote,
                         grants=len(record.get("grants") or []))
        return peer_id

    # ---------------------------------------------------------------- owner: peers and grants
    def peers(self) -> list:
        self.log.refresh()
        now = ev.now_iso(self._clock)
        out = []
        for peer in sorted(self.log.peers.values(), key=lambda p: (p["created_at"], p["peer_id"])):
            grants = self.log.grants_of(peer["peer_id"], now=now)
            out.append({"peer_id": peer["peer_id"], "label": peer["label"], "fingerprint": peer["fp"],
                        "created_at": peer["created_at"], "status": "revoked" if peer["revoked_at"] else "active",
                        "revoked_at": peer["revoked_at"], "active_grants": len(grants)})
        return out

    def resolve_peer(self, ref: str, *, include_revoked: bool = True) -> dict:
        if not isinstance(ref, str) or not ref.strip() or len(ref) > 64:
            raise ShareError("unknown_peer", "give a peer id (see: zero-mem share peers)")
        ref = ref.strip()
        self.log.refresh()
        peers = [p for p in self.log.peers.values() if include_revoked or p["revoked_at"] is None]
        exact = [p for p in peers if p["peer_id"] == ref]
        pool = exact or [p for p in peers if len(ref) >= 6 and p["peer_id"].startswith(ref.lower())] \
            or [p for p in peers if p["label"] == ref]
        if len(pool) != 1:
            raise ShareError("unknown_peer" if not pool else "ambiguous_peer",
                             "no such peer (see: zero-mem share peers)" if not pool else "several peers match; use the peer id")
        return dict(pool[0])

    def _append_grant(self, peer_id: str, spec: dict, *, source: str) -> dict:
        if len(self.log.grants_of(peer_id, active_only=False)) >= ev.MAX_GRANTS_PER_PEER:
            raise ShareError("too_many_grants", "this peer already has too many grants")
        expires_at = None
        if spec["expires_in"] is not None:
            expires_at = (self.now() + timedelta(seconds=spec["expires_in"])).strftime("%Y-%m-%dT%H:%M:%SZ")
        grant_id = "sg-" + uuid.uuid4().hex[:12]
        self.audit_event("grant_create", grant_id=grant_id, peer_id=peer_id, space=spec["space"], projects=spec["projects"],
                         types=spec["types"], ref_prefixes=spec["ref_prefixes"], expires_at=expires_at, source=source)
        return {"grant_id": grant_id, "peer_id": peer_id, "space": spec["space"], "projects": spec["projects"],
                "types": spec["types"], "ref_prefixes": spec["ref_prefixes"], "expires_at": expires_at}

    def grant(self, peer_ref: str, spec: dict) -> dict:
        self.require_active()
        peer = self.resolve_peer(peer_ref)
        if peer["revoked_at"]:
            raise ShareError("peer_revoked", "this peer is revoked; pair again with a new invite")
        return self._append_grant(peer["peer_id"], validate_grant_spec(spec), source="owner")

    def preview(self, peer_ref: str) -> dict:
        peer = self.resolve_peer(peer_ref)
        return self.owner_service().preview_counts(peer["peer_id"])

    def revoke_peer(self, peer_ref: str) -> dict:
        peer = self.resolve_peer(peer_ref)
        if peer["revoked_at"]:
            return {"status": "already_revoked", "peer_id": peer["peer_id"]}
        for grant in self.log.grants_of(peer["peer_id"], now=ev.now_iso(self._clock)):
            self.audit_event("grant_revoke", grant_id=grant["grant_id"], peer_id=peer["peer_id"])
        self.audit_event("peer_revoke", peer_id=peer["peer_id"])
        return {"status": "revoked", "peer_id": peer["peer_id"]}

    def revoke_grants(self, peer_ref: str, grant_id: Optional[str] = None) -> dict:
        """One grant (``grant_id``) or all of the peer's grants (``None``); the peer stays paired."""
        peer = self.resolve_peer(peer_ref)
        now = ev.now_iso(self._clock)
        active = self.log.grants_of(peer["peer_id"], now=now)
        if grant_id is not None:
            active = [g for g in active if g["grant_id"] == grant_id]
            if not active:
                raise ShareError("unknown_grant", "no such active grant for this peer (see: zero-mem share grants)")
        for grant in active:
            self.audit_event("grant_revoke", grant_id=grant["grant_id"], peer_id=peer["peer_id"])
        return {"status": "revoked" if active else "nothing_to_revoke", "peer_id": peer["peer_id"],
                "revoked": [g["grant_id"] for g in active]}

    def grants(self, peer_ref: Optional[str] = None, *, include_ended: bool = False) -> list:
        peer_id = self.resolve_peer(peer_ref)["peer_id"] if peer_ref else None
        now = ev.now_iso(self._clock)
        out = []
        for g in self.log.grants_of(peer_id, now=now, active_only=not include_ended):
            state = "revoked" if g["revoked_at"] else ("expired" if g["expires_at"] and g["expires_at"] <= now else "active")
            out.append({**g, "state": state})
        return out

    def audit(self, limit: int = 50) -> list:
        return ev.read_events(self.layout, limit=limit)

    # ---------------------------------------------------------------- joiner side registry
    def owners(self) -> list:
        return sorted(self.log.active_owners().values(), key=lambda o: (o["added_at"], o["peer_id"]))

    def resolve_owner(self, ref: str) -> dict:
        ref = (ref or "").strip()
        owners = self.owners()
        pool = [o for o in owners if o["peer_id"] == ref] or \
               [o for o in owners if len(ref) >= 6 and o["peer_id"].startswith(ref.lower())] or \
               [o for o in owners if o["label"] == ref]
        if len(pool) != 1:
            raise ShareError("unknown_owner" if not pool else "ambiguous_owner",
                             "no such owner (see: zero-mem share peers)" if not pool else "several owners match; use the peer id")
        return pool[0]

    def forget_owner(self, ref: str) -> dict:
        owner = self.resolve_owner(ref)
        self.audit_event("owner_remove", peer_id=owner["peer_id"])
        return {"status": "removed", "peer_id": owner["peer_id"]}
