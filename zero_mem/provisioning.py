"""Operator provisioning: agent profiles, READ/WRITE grants and the operator-approval model (ADR-V170-02).

This is the TRUSTED control plane. Nothing here is reachable from an agent request:

* ``agents add``     -> canonical ``agent_profile`` event + a READ grant on the shared space (no verification needed).
* ``agents grant-write`` -> an explicit OPERATOR action. It first appends a canonical ``operator_approval`` event
  (who approved what, for whom, on which target, and why) and then creates the canonical ``access_grant`` WRITE
  event whose ``verification_ref`` is that approval. ``OperatorApprovalLookup`` is the ``verification_lookup``
  ``GrantAdminService`` / ``authorize_write`` consult, so single-user installs work without M4 verification
  records while AGENTS.md's "cross-profile writes need an explicit, reviewable gate" still holds.
* ``agents revoke``  -> revokes the grant (canonical ``access_grant`` revoke) and the approval (canonical
  ``operator_approval`` revoke), so either one alone is enough to deny the write.

Canonical truth is the append-only memory stream; the derived ``zm_access_grants`` projection is rebuilt from
it by ``zero-mem upgrade`` exactly like every other grant. No LLM, no network.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Optional

from .memory_layout import Layout

SHARED_SPACE = "ks-shared"
#: Resource type a WRITE grant is limited to (corpus sources only, never events/decisions/...).
WRITE_RESOURCE_TYPES = ["corpus_source"]
APPROVAL_PREFIX = "opapp-"
DEFAULT_APPROVAL_BASIS = (
    "operator command; see docs/v1.6.1/decisions/ADR-V170-02-OPERATOR-APPROVED-WRITE-GRANTS.md"
)
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

_APPROVAL_NEEDLE = b'"operator_approval"'
_PROFILE_NEEDLE = b'"agent_profile"'
_CHUNK = 1 << 20
_LOCK_TIMEOUT = 30.0


class ProvisioningError(Exception):
    """Typed, sanitized provisioning failure (``code`` is stable, ``message`` is for humans)."""

    def __init__(self, code: str, message: Optional[str] = None) -> None:
        self.code = code
        self.message = message or code
        super().__init__(f"{code}: {self.message}")


def _now(clock: Optional[Callable[[], datetime]] = None) -> str:
    moment = clock() if clock else datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def valid_id(value: Any) -> bool:
    return isinstance(value, str) and ID_RE.fullmatch(value) is not None


def _check_id(value: Any, code: str, label: str) -> str:
    if not valid_id(value):
        raise ProvisioningError(code, f"{label} must match {ID_RE.pattern}")
    return value


# ---------------------------------------------------------------------------------------------
# Canonical stream append
# ---------------------------------------------------------------------------------------------
def append_canonical_event(stream: Path, event: Mapping[str, Any]) -> None:
    """Append one canonical JSON line (single ``write`` under the stream's process lock, fsync'd).

    Refuses a stream whose last line is not newline-terminated (a torn append) instead of gluing a new
    record onto it, and refuses a record without a string ``event_id`` (``zero-mem upgrade`` requires one).
    """
    if not isinstance(event, Mapping) or not isinstance(event.get("event_id"), str) or not event["event_id"]:
        raise ProvisioningError("invalid_event", "canonical events need a string event_id")
    from src.storage.coordination import locked

    data = (json.dumps(dict(event), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    stream = Path(stream)
    flags = os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        with locked(stream.with_name(stream.name + ".lock"), mode="exclusive", timeout=_LOCK_TIMEOUT):
            fd = os.open(stream, flags, 0o600)
            try:
                size = os.fstat(fd).st_size
                if size and os.pread(fd, 1, size - 1) != b"\n":
                    raise ProvisioningError("stream_not_terminated", "canonical stream ends mid-record; run zero-mem doctor")
                view = memoryview(data)
                while view:
                    written = os.write(fd, view)
                    view = view[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
    except ProvisioningError:
        raise
    except OSError:
        raise ProvisioningError("stream_unwritable", "cannot append to the canonical memory stream") from None
    except Exception as exc:  # lock timeout and friends
        raise ProvisioningError("stream_busy", f"cannot lock the canonical memory stream ({type(exc).__name__})") from None


def _iter_stream_events(stream: Path, needle: bytes) -> Iterator[dict]:
    """Yield parsed JSON objects of complete stream lines containing ``needle`` (cheap byte pre-filter)."""
    try:
        fh = open(stream, "rb")
    except OSError:
        return
    with fh:
        carry = b""
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            buf = carry + chunk
            *lines, carry = buf.split(b"\n")
            for line in lines:
                if needle in line:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(rec, dict):
                        yield rec
        # a trailing unterminated segment is a torn append: never trusted


# ---------------------------------------------------------------------------------------------
# Operator approvals as WRITE-grant verification
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class OperatorApproval:
    """What the verification predicate sees: ``verification_status == "verified"`` is the only passing value."""

    approval_ref: str
    verification_status: str  # "verified" | "revoked"
    subject_profile: str
    operation: str
    target_type: str
    target_id: str
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    basis: Optional[str] = None


class OperatorApprovalLookup:
    """``verification_ref -> OperatorApproval | None`` backed by canonical ``operator_approval`` events.

    Pass an instance as ``verification_lookup`` to ``GrantAdminService`` / ``AuthorizedWriteService``.
    Read-only and incremental: it indexes only bytes appended since the last call, never trusts a torn
    final line, ignores malformed or foreign records, and treats a revoke as terminal for its ref.
    """

    def __init__(self, stream: Path) -> None:
        self._stream = Path(stream)
        self._lock = threading.Lock()
        self._approvals: dict[str, OperatorApproval] = {}
        self._revoked: set[str] = set()
        self._file_id: Optional[tuple[int, int]] = None
        self._offset = 0

    def __call__(self, verification_ref: Any) -> Optional[OperatorApproval]:
        if not isinstance(verification_ref, str) or not verification_ref.startswith(APPROVAL_PREFIX):
            return None
        with self._lock:
            self._refresh()
            approval = self._approvals.get(verification_ref)
            if approval is None:
                return None
            if verification_ref in self._revoked:
                return OperatorApproval(**{**approval.__dict__, "verification_status": "revoked"})
            return approval

    # -- internals -------------------------------------------------------------------------
    def _reset(self) -> None:
        self._approvals.clear()
        self._revoked.clear()
        self._file_id = None
        self._offset = 0

    def _refresh(self) -> None:
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
                    if _APPROVAL_NEEDLE in line:
                        self._apply(line)
            self._offset += consumed  # the torn tail (carry) is left for the next refresh

    def _apply(self, line: bytes) -> None:
        try:
            record = json.loads(line)
        except ValueError:
            return
        if not isinstance(record, dict) or record.get("event_type") != "operator_approval":
            return
        m4 = record.get("m4")
        if not isinstance(m4, dict) or m4.get("domain") != "operator_approval":
            return
        ref = m4.get("approval_ref")
        if not isinstance(ref, str) or not ref.startswith(APPROVAL_PREFIX):
            return
        op = m4.get("op")
        if op == "revoke":
            self._revoked.add(ref)  # terminal, even if the approve line is seen later
        elif op == "approve":
            fields = [m4.get(k) for k in ("subject_profile", "operation", "target_type", "target_id")]
            if ref in self._approvals or not all(isinstance(v, str) and v for v in fields):
                return
            self._approvals[ref] = OperatorApproval(
                approval_ref=ref,
                verification_status="verified",
                subject_profile=fields[0],
                operation=fields[1],
                target_type=fields[2],
                target_id=fields[3],
                approved_by=m4.get("approved_by") if isinstance(m4.get("approved_by"), str) else None,
                approved_at=record.get("created_at") if isinstance(record.get("created_at"), str) else None,
                basis=m4.get("basis") if isinstance(m4.get("basis"), str) else None,
            )


# ---------------------------------------------------------------------------------------------
# Provisioner (operator surface)
# ---------------------------------------------------------------------------------------------
def _operator_name() -> str:
    try:
        import getpass

        return getpass.getuser() or "operator"
    except Exception:
        return "operator"


def _target(space: Optional[str], project: Optional[str]) -> tuple[str, str]:
    if (space is None) == (project is None):
        raise ProvisioningError("invalid_target", "give exactly one of a knowledge space or a project")
    if space is not None:
        return "knowledge_space", _check_id(space, "invalid_target", "space")
    return "project", _check_id(project, "invalid_target", "project")


def _grant_id(profile: str, operation: str, target_type: str, target_id: str) -> str:
    kind = "space" if target_type == "knowledge_space" else target_type
    return f"g-{profile}-{operation.lower()}-{kind}-{target_id}"


class Provisioner:
    """Agent/grant administration for one storage :class:`Layout` (call ``layout.ensure()`` first)."""

    def __init__(
        self,
        layout: Layout,
        *,
        operator: Optional[str] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._layout = layout
        self._operator = operator or _operator_name()
        self._clock = clock
        self._lookup = OperatorApprovalLookup(layout.memory_stream)

    # -- plumbing --------------------------------------------------------------------------
    @contextlib.contextmanager
    def _admin(self) -> Iterator[Any]:
        from src.storage.coordination import locked
        from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig

        lock = self._layout.memory_stream.with_name("provisioning.lock")
        try:
            with locked(lock, mode="exclusive", timeout=_LOCK_TIMEOUT):
                store = SQLiteStore(SQLiteStoreConfig(path=self._layout.derived_db))
                try:
                    store.ensure_schema()
                    yield store._conn
                finally:
                    store.close()
        except ProvisioningError:
            raise
        except OSError:
            raise ProvisioningError("store_unavailable", "cannot open the derived store") from None

    def _append(self, event_type: str, prefix: str, m4: dict) -> dict:
        event = {
            "event_id": f"{prefix}-{uuid.uuid4().hex[:16]}",
            "event_type": event_type,
            "created_at": _now(self._clock),
            "m4": m4,
        }
        append_canonical_event(self._layout.memory_stream, event)
        return event

    def _writer(self, event: dict) -> None:
        append_canonical_event(self._layout.memory_stream, event)

    def _service(self, conn):
        from src.access.admin import GrantAdminService

        return GrantAdminService(conn, self._writer, self._lookup)

    def _registered(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for rec in _iter_stream_events(self._layout.memory_stream, _PROFILE_NEEDLE):
            m4 = rec.get("m4")
            if rec.get("event_type") == "agent_profile" and isinstance(m4, dict) and m4.get("domain") == "agent_profile" \
                    and valid_id(m4.get("profile_id")) and m4.get("op") == "add":
                out.setdefault(m4["profile_id"], {"added_at": rec.get("created_at"), "added_by": m4.get("added_by")})
        return out

    @staticmethod
    def _active_grants(conn, profile: str, *, operation=None, target_type=None, target_id=None) -> list:
        sql = (
            "SELECT grant_id, operation, target_type, target_id, verification_ref FROM zm_access_grants "
            "WHERE subject_profile=? AND lifecycle_status='active' AND (state IS NULL OR state != 'revoked')"
        )
        params: list = [profile]
        for column, value in (("operation", operation), ("target_type", target_type), ("target_id", target_id)):
            if value is not None:
                sql += f" AND {column}=?"
                params.append(value)
        return [tuple(r) for r in conn.execute(sql + " ORDER BY grant_id", params).fetchall()]

    def _create_grant(self, conn, profile, operation, target_type, target_id, *, verification_ref=None) -> str:
        from src.access.admin import GrantAdminRequest

        grant_id = _grant_id(profile, operation, target_type, target_id)
        request = GrantAdminRequest(
            action="create",
            grant_id=grant_id,
            subject_profile=profile,
            operation=operation,
            target_type=target_type,
            target_id=target_id,
            resource_types=list(WRITE_RESOURCE_TYPES) if operation == "WRITE" else None,
            verification_ref=verification_ref,
            created_at=_now(self._clock),
            event_id=f"grant-{grant_id}-create-{uuid.uuid4().hex[:8]}",
        )
        try:
            self._service(conn).create(request)
        except ValueError as exc:
            raise ProvisioningError("grant_rejected", str(exc)) from None
        return grant_id

    # -- operations ------------------------------------------------------------------------
    def add_agent(self, profile: Any) -> dict:
        """Register ``profile`` and grant it READ on the shared space. Idempotent."""
        profile = _check_id(profile, "invalid_profile", "profile")
        with self._admin() as conn:
            known = profile in self._registered()
            if not known:
                self._append("agent_profile", "agent", {
                    "domain": "agent_profile", "op": "add", "profile_id": profile, "added_by": self._operator})
            have = self._active_grants(conn, profile, operation="READ", target_type="knowledge_space",
                                       target_id=SHARED_SPACE)
            granted = []
            if not have:
                granted.append(self._create_grant(conn, profile, "READ", "knowledge_space", SHARED_SPACE))
        return {
            "status": "exists" if known and not granted else "added",
            "profile": profile,
            "granted": granted,
            "defaults": {"read": [SHARED_SPACE], "write": ["private (own profile)"]},
        }

    def grant_read(self, profile: Any, *, space: Optional[str] = None, project: Optional[str] = None) -> dict:
        profile = _check_id(profile, "invalid_profile", "profile")
        target_type, target_id = _target(space, project)
        with self._admin() as conn:
            self._require_registered(profile)
            if self._active_grants(conn, profile, operation="READ", target_type=target_type, target_id=target_id):
                return {"status": "exists", "profile": profile, "target_type": target_type, "target_id": target_id}
            grant_id = self._create_grant(conn, profile, "READ", target_type, target_id)
        return {"status": "granted", "profile": profile, "grant_id": grant_id,
                "target_type": target_type, "target_id": target_id}

    def grant_write(
        self,
        profile: Any,
        *,
        space: Optional[str] = None,
        project: Optional[str] = None,
        basis: Optional[str] = None,
    ) -> dict:
        """EXPLICIT OPERATOR ACTION: approve ``profile`` writing to one space/project (ADR-V170-02)."""
        profile = _check_id(profile, "invalid_profile", "profile")
        target_type, target_id = _target(space, project)
        if basis is not None and (not isinstance(basis, str) or not basis.strip() or len(basis) > 500):
            raise ProvisioningError("invalid_basis", "basis must be a short non-empty string")
        with self._admin() as conn:
            self._require_registered(profile)
            for grant_id, _op, _tt, _tid, ref in self._active_grants(
                    conn, profile, operation="WRITE", target_type=target_type, target_id=target_id):
                approval = self._lookup(ref)
                if approval is not None and approval.verification_status == "verified":
                    return {"status": "exists", "profile": profile, "grant_id": grant_id,
                            "approval_ref": ref, "target_type": target_type, "target_id": target_id}
            ref = APPROVAL_PREFIX + uuid.uuid4().hex[:16]
            # 1) the approval (the grant's verification_ref) is canonical BEFORE the grant exists
            self._append("operator_approval", "approval", {
                "domain": "operator_approval", "op": "approve", "approval_ref": ref,
                "subject_profile": profile, "operation": "WRITE",
                "target_type": target_type, "target_id": target_id,
                "approved_by": self._operator, "basis": (basis or DEFAULT_APPROVAL_BASIS).strip()})
            # 2) the canonical WRITE grant referencing it (GrantAdminService re-verifies through the lookup)
            grant_id = self._create_grant(conn, profile, "WRITE", target_type, target_id, verification_ref=ref)
        return {"status": "granted", "profile": profile, "grant_id": grant_id, "approval_ref": ref,
                "target_type": target_type, "target_id": target_id}

    def revoke(
        self,
        profile: Any,
        *,
        space: Optional[str] = None,
        project: Optional[str] = None,
        operation: Optional[str] = None,
    ) -> dict:
        """Revoke a profile's active grants (all, or filtered by target and/or operation)."""
        from src.access.admin import GrantAdminRequest

        profile = _check_id(profile, "invalid_profile", "profile")
        if space is not None and project is not None:
            raise ProvisioningError("invalid_target", "give at most one of a knowledge space or a project")
        target_type = target_id = None
        if space is not None or project is not None:
            target_type, target_id = _target(space, project)
        op = None
        if operation is not None:
            op = str(operation).upper()
            if op not in ("READ", "WRITE"):
                raise ProvisioningError("invalid_operation", "operation must be READ or WRITE")
        with self._admin() as conn:
            rows = self._active_grants(conn, profile, operation=op, target_type=target_type, target_id=target_id)
            revoked = []
            for grant_id, g_op, g_tt, g_tid, ref in rows:
                if g_op == "WRITE" and isinstance(ref, str) and ref.startswith(APPROVAL_PREFIX):
                    self._append("operator_approval", "approval", {
                        "domain": "operator_approval", "op": "revoke", "approval_ref": ref,
                        "revoked_by": self._operator})
                self._service(conn).revoke(GrantAdminRequest(
                    action="revoke", grant_id=grant_id, subject_profile=profile, operation=g_op,
                    target_type=g_tt, target_id=g_tid, created_at=_now(self._clock),
                    event_id=f"grant-{grant_id}-revoke-{uuid.uuid4().hex[:8]}"))
                revoked.append({"grant_id": grant_id, "operation": g_op, "target_type": g_tt, "target_id": g_tid})
        return {"status": "revoked" if revoked else "not_found", "profile": profile, "revoked": revoked}

    def list_agents(self) -> list[dict]:
        registered = self._registered()
        with self._admin() as conn:
            subjects = {r[0] for r in conn.execute("SELECT DISTINCT subject_profile FROM zm_access_grants").fetchall()}
            out = []
            for profile in sorted(set(registered) | subjects):
                grants = []
                can_read = can_write = False
                for _gid, op, tt, tid, ref in self._active_grants(conn, profile):
                    verified = None
                    if op == "WRITE":
                        approval = self._lookup(ref)
                        verified = approval is not None and approval.verification_status == "verified"
                    grants.append({"operation": op, "target_type": tt, "target_id": tid,
                                   **({"approval_ref": ref, "approval_verified": verified} if op == "WRITE" else {})})
                    if tt == "knowledge_space" and tid == SHARED_SPACE:
                        can_read = can_read or op == "READ"
                        can_write = can_write or (op == "WRITE" and bool(verified))
                out.append({
                    "profile": profile,
                    "registered": profile in registered,
                    "added_at": registered.get(profile, {}).get("added_at"),
                    "can_read_shared": can_read,
                    "can_write_shared": can_write,
                    "grants": grants,
                })
        return out

    def _require_registered(self, profile: str) -> None:
        if profile not in self._registered():
            raise ProvisioningError("unknown_agent", f"agent {profile!r} is not registered; run: zero-mem agents add {profile}")


__all__ = [
    "APPROVAL_PREFIX", "DEFAULT_APPROVAL_BASIS", "OperatorApproval", "OperatorApprovalLookup",
    "Provisioner", "ProvisioningError", "SHARED_SPACE", "WRITE_RESOURCE_TYPES",
    "append_canonical_event", "valid_id",
]
