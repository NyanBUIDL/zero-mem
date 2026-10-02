"""Learning harness core: inert proposals, owner review, revocation and expiry (ADR-V170-03).

An agent that learns something (a project rule, a decision, a gotcha) may only PROPOSE it. A proposal is an
append-only canonical event (``event_type="learning_proposal"``) in the same stream as grants and operator approvals
(ADR-V170-02); it is not a corpus source, so ``recall`` / ``context`` / ``search`` / MCP can never return it. Only the
OWNER (``zero-mem review ...`` / :class:`Reviewer`, a trusted control plane an agent must not be given a shell for)
turns a proposal into memory: approval commits the text through the normal write path as the PROPOSER profile, and the
owner's approval is itself the grant for that single write (recorded with proposer, approver, proposal id and resulting
source id). The agent-facing API (:meth:`zero_mem.memory.Memory.propose` / ``proposals`` / ``withdraw``) can only see and
withdraw the caller's own proposals; there is no approve method on :class:`~zero_mem.memory.Memory`.

Current proposal state is DERIVED by replaying the stream (:class:`ProposalLog`: incremental, byte-prefiltered, torn
tail never trusted, bounded); nothing here mutates a source to change a status. Lifecycle::

    proposed -> approved | rejected | expired | withdrawn          approved -> revoked | superseded

* ``expired``: a pending proposal older than ``learning.proposal_ttl_days`` is expired at read time
  (``review expire`` additionally records it).
* ``revoked``: ``review revoke`` tombstones the source (the existing forget path) and records the event.
* ``superseded``: approving a new version of the same named source supersedes the previous approval.
* active TTL: with ``learning.active_ttl_days`` > 0 an approved item stops being returned by recall/context once its
  latest approval is older than that (derived at read time; the source is not changed or deleted).

Zero dependencies, no network, no LLM.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import threading
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional, Sequence

from . import learning_settings as ls
from .memory import MEMORY_TYPES, SCOPES, Memory, _Invalid
from .memory_layout import Layout
from .memory_results import ForgetResult, WriteResult
from .provisioning import ProvisioningError, append_canonical_event, valid_id

EVENT_TYPE = "learning_proposal"
DOMAIN = "learning_proposal"
APPROVAL_BASIS = "owner review; see docs/v1.6.1/decisions/ADR-V170-03-LEARNING-HARNESS-GATES.md"

PROPOSAL_ID_RE = re.compile(r"^p-[0-9a-f]{12}$")
#: ``peer``: imported from a paired LAN peer (ADR-V170-05); never auto-approved, subject to ``allow_agent_proposals``.
PROPOSAL_SOURCES = ("agent", "user", "learner", "peer")
#: ``file`` is excluded: documents are ingested by the owner, not proposed.
PROPOSABLE_TYPES = tuple(t for t in MEMORY_TYPES if t != "file")
STATUSES = ("pending", "approved", "rejected", "expired", "withdrawn", "revoked", "superseded")

MAX_PROPOSAL_BYTES = 8 * 1024
MAX_PROPOSE_EVIDENCE = 5
MAX_EVIDENCE_ITEMS = 10
MAX_EVIDENCE_CHARS = 200
MAX_SEEN = 1000
MAX_REASON_CHARS = 200
MAX_HISTORY = 20
MAX_REPLAY_EVENTS = 200_000
_LOCK_TIMEOUT = 30.0
_CHUNK = 1 << 20
_NEEDLE = b'"learning_proposal"'

_UTC = timezone.utc


# ---------------------------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------------------------
def _ts(moment: datetime) -> str:
    return moment.astimezone(_UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_UTC)
    except ValueError:
        return None


def normalize_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def dedupe_key(text: str, memory_type: str, scope: str, project_id: Optional[str], name: Optional[str]) -> str:
    material = "\x1f".join([normalize_text(text), memory_type, scope, project_id or "", name or ""])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _operator_name() -> str:
    try:
        import getpass

        return getpass.getuser() or "operator"
    except Exception:  # noqa: BLE001
        return "operator"


def _short(value: Any, limit: int) -> Optional[str]:
    return value if isinstance(value, str) and 0 < len(value) <= limit else None


# ---------------------------------------------------------------------------------------------
# results and records
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ProposalResult:
    """Outcome of :meth:`Memory.propose` / ``withdraw``. Nothing raises; branch on ``status``."""

    status: str  # proposed | merged | withdrawn | rejected | rejected_secret | invalid | not_found | not_pending | error
    reason: Optional[str] = None
    proposal_id: Optional[str] = None
    seen: Optional[int] = None
    memory_type: Optional[str] = None
    scope: Optional[str] = None
    project_id: Optional[str] = None
    name: Optional[str] = None
    rule_ids: tuple = ()

    @property
    def ok(self) -> bool:
        return self.status in ("proposed", "merged", "withdrawn")

    def as_dict(self) -> dict:
        out = {k: v for k, v in self.__dict__.items() if v not in (None, ())}
        out["ok"] = self.ok
        if self.rule_ids:
            out["rule_ids"] = list(self.rule_ids)
        return out


@dataclass(frozen=True)
class ReviewResult:
    """Outcome of an owner action (:class:`Reviewer`)."""

    status: str  # approved | rejected | revoked | expired | not_found | not_pending | blocked | rejected_secret |
    #              rejected_content | invalid | error
    reason: Optional[str] = None
    proposal_id: Optional[str] = None
    source_id: Optional[str] = None
    external_ref: Optional[str] = None
    version: Optional[str] = None
    write_status: Optional[str] = None
    superseded: bool = False
    detail: Optional[dict] = None

    @property
    def ok(self) -> bool:
        return self.status in ("approved", "rejected", "revoked", "expired")

    def as_dict(self) -> dict:
        out = {k: v for k, v in self.__dict__.items() if v not in (None, False)}
        out["ok"] = self.ok
        return out


@dataclass
class Proposal:
    proposal_id: str
    proposer: str
    source: str
    memory_type: str
    scope: str
    project_id: Optional[str]
    name: Optional[str]
    text: str
    evidence: list
    created_at: str
    key: str
    seen: int = 1
    status: str = "pending"
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None
    reason: Optional[str] = None
    final_text: Optional[str] = None
    final_name: Optional[str] = None
    source_id: Optional[str] = None
    external_ref: Optional[str] = None
    version: Optional[str] = None
    superseded_by: Optional[str] = None
    history: list = field(default_factory=list)

    @property
    def edited(self) -> bool:
        return self.final_text is not None and self.final_text != self.text

    def effective_status(self, ttl_days: int, now: datetime) -> str:
        """Stored status, except that a pending proposal past ``ttl_days`` reads as ``expired``."""
        if self.status == "pending":
            created = _parse_ts(self.created_at)
            if created is not None and now - created > timedelta(days=ttl_days):
                return "expired"
        return self.status

    def as_dict(self, *, ttl_days: Optional[int] = None, now: Optional[datetime] = None,
                active_ttl_days: int = 0, history: bool = False) -> dict:
        status = self.status
        if ttl_days is not None and now is not None:
            status = self.effective_status(ttl_days, now)
        out: dict[str, Any] = {
            "id": self.proposal_id, "status": status, "proposer": self.proposer, "source": self.source,
            "memory_type": self.memory_type, "scope": self.scope, "project_id": self.project_id, "name": self.name,
            "text": self.text, "evidence": list(self.evidence), "seen": self.seen, "created_at": self.created_at,
        }
        if self.decided_at:
            out.update(decided_at=self.decided_at, decided_by=self.decided_by)
        if self.reason:
            out["reason"] = self.reason
        if self.edited:
            out["final_text"] = self.final_text
        if self.source_id:
            out.update(source_id=self.source_id, external_ref=self.external_ref, version=self.version)
        if self.superseded_by:
            out["superseded_by"] = self.superseded_by
        if status == "approved" and active_ttl_days > 0 and now is not None:
            decided = _parse_ts(self.decided_at)
            if decided is not None and now - decided > timedelta(days=active_ttl_days):
                out["active_expired"] = True
        if history:
            out["history"] = list(self.history)
        return {k: v for k, v in out.items() if v is not None}


@dataclass(frozen=True)
class ApprovedWrite:
    """Capability passed to ``Memory._apply_approved_write``: only :class:`Reviewer` constructs it."""

    proposal_id: str
    proposer: str
    approver: str


# ---------------------------------------------------------------------------------------------
# replay: the proposal state machine
# ---------------------------------------------------------------------------------------------
class ProposalLog:
    """Proposal state derived from the canonical stream (incremental and bounded).

    Reads only the bytes appended since the last :meth:`refresh`, pre-filters lines by a byte needle, ignores
    malformed / foreign / out-of-order records and never trusts a torn final line. At most
    :data:`MAX_REPLAY_EVENTS` learning events are applied; beyond that ``overflow`` is set and new proposals are refused.
    """

    def __init__(self, stream) -> None:
        self._stream = stream
        self._lock = threading.RLock()
        self._reset()

    def _reset(self) -> None:
        self.proposals: dict[str, Proposal] = {}
        self._pending_by_key: dict[tuple, str] = {}
        self._day_counts: dict[tuple, int] = {}
        self.revoked_sources: dict[str, str] = {}
        self.events_applied = 0
        self.overflow = False
        self._file_id: Optional[tuple] = None
        self._offset = 0

    # -- reading --------------------------------------------------------------------------
    def refresh(self) -> "ProposalLog":
        with self._lock:
            try:
                info = os.stat(self._stream)
            except OSError:
                self._reset()
                return self
            identity = (info.st_dev, info.st_ino)
            if identity != self._file_id or info.st_size < self._offset:
                self._reset()
                self._file_id = identity
            if info.st_size == self._offset:
                return self
            try:
                fh = open(self._stream, "rb")
            except OSError:
                return self
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
                            self._apply_line(line)
                self._offset += consumed  # the torn tail (carry) is re-read next time
            return self

    def _apply_line(self, line: bytes) -> None:
        import json

        try:
            record = json.loads(line)
        except ValueError:
            return
        if not isinstance(record, dict) or record.get("event_type") != EVENT_TYPE:
            return
        m4 = record.get("m4")
        if not isinstance(m4, dict) or m4.get("domain") != DOMAIN:
            return
        if self.events_applied >= MAX_REPLAY_EVENTS:
            self.overflow = True
            return
        self.events_applied += 1
        at = record.get("created_at")
        if _parse_ts(at) is None:
            return
        op = m4.get("op")
        handler = {"propose": self._on_propose, "seen": self._on_seen, "approve": self._on_approve,
                   "reject": self._on_decision, "expire": self._on_decision, "withdraw": self._on_decision,
                   "revoke": self._on_revoke}.get(op)
        if handler is not None:
            try:
                handler(op, m4, at)
            except (KeyError, TypeError, ValueError):
                return

    # -- transitions ------------------------------------------------------------------------
    @staticmethod
    def _evidence(value: Any, cap: int) -> list:
        if not isinstance(value, list):
            return []
        out: list = []
        for item in value:
            text = _short(item, MAX_EVIDENCE_CHARS)
            if text is not None and text not in out and len(out) < cap:
                out.append(text)
        return out

    def _note(self, p: Proposal, op: str, at: str, by: Optional[str]) -> None:
        if len(p.history) < MAX_HISTORY:
            p.history.append({"at": at, "op": op, **({"by": by} if by else {})})

    def _on_propose(self, _op: str, m4: dict, at: str) -> None:
        pid = m4.get("proposal_id")
        proposer = m4.get("proposer")
        text = m4.get("text")
        mtype, scope, project, name = m4.get("memory_type"), m4.get("scope"), m4.get("project_id"), m4.get("name")
        if not (isinstance(pid, str) and PROPOSAL_ID_RE.fullmatch(pid)) or pid in self.proposals:
            return
        if not valid_id(proposer) or m4.get("source") not in PROPOSAL_SOURCES:
            return
        if mtype not in PROPOSABLE_TYPES or scope not in SCOPES:
            return
        if project is not None and not valid_id(project):
            return
        if name is not None and _short(name, 128) is None:
            return
        if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > MAX_PROPOSAL_BYTES:
            return
        key = dedupe_key(text, mtype, scope, project, name)
        p = Proposal(proposal_id=pid, proposer=proposer, source=m4["source"], memory_type=mtype, scope=scope,
                     project_id=project, name=name, text=text, evidence=self._evidence(m4.get("evidence"), MAX_EVIDENCE_ITEMS),
                     created_at=at, key=key)
        self.proposals[pid] = p
        self._pending_by_key[(proposer, key)] = pid
        day = (proposer, at[:10])
        self._day_counts[day] = self._day_counts.get(day, 0) + 1
        self._note(p, "propose", at, proposer)

    def _on_seen(self, _op: str, m4: dict, at: str) -> None:
        p = self.proposals.get(m4.get("proposal_id"))
        if p is None or p.status != "pending" or m4.get("by") != p.proposer:
            return
        p.seen = min(MAX_SEEN, p.seen + 1)
        for item in self._evidence(m4.get("evidence"), MAX_EVIDENCE_ITEMS):
            if item not in p.evidence and len(p.evidence) < MAX_EVIDENCE_ITEMS:
                p.evidence.append(item)
        self._note(p, "seen", at, p.proposer)

    def _close(self, p: Proposal, status: str, at: str, by: Optional[str], reason: Optional[str]) -> None:
        p.status, p.decided_at, p.decided_by = status, at, by
        p.reason = _short(reason, MAX_REASON_CHARS) if reason else None
        if self._pending_by_key.get((p.proposer, p.key)) == p.proposal_id:
            del self._pending_by_key[(p.proposer, p.key)]
        self._note(p, status, at, by)

    def _on_decision(self, op: str, m4: dict, at: str) -> None:
        p = self.proposals.get(m4.get("proposal_id"))
        if p is None or p.status != "pending":
            return
        by = _short(m4.get("by"), 64)
        if op == "withdraw":
            if by != p.proposer:
                return
            self._close(p, "withdrawn", at, by, None)
        elif op == "reject":
            self._close(p, "rejected", at, by, m4.get("reason"))
        else:
            self._close(p, "expired", at, by or "system", m4.get("reason"))

    def _on_approve(self, _op: str, m4: dict, at: str) -> None:
        p = self.proposals.get(m4.get("proposal_id"))
        source_id = _short(m4.get("source_id"), 128)
        if p is None or p.status != "pending" or source_id is None:
            return
        by = _short(m4.get("approved_by"), 64)
        self._close(p, "approved", at, by, None)
        p.source_id = source_id
        p.external_ref = _short(m4.get("external_ref"), 600)
        p.version = _short(m4.get("version"), 128)
        final = m4.get("final_text")
        p.final_text = final if isinstance(final, str) and final.strip() else None
        p.final_name = _short(m4.get("final_name"), 128)
        self.revoked_sources.pop(source_id, None)  # a re-approval after a revoke makes the source active again
        for other in self.proposals.values():  # a new approved version of the same source supersedes the old one
            if other is not p and other.status == "approved" and other.source_id == source_id:
                other.status, other.superseded_by = "superseded", p.proposal_id
                self._note(other, "superseded", at, by)

    def _on_revoke(self, _op: str, m4: dict, at: str) -> None:
        source_id = _short(m4.get("source_id"), 128)
        if source_id is None:
            return
        by = _short(m4.get("by"), 64)
        self.revoked_sources[source_id] = at
        for p in self.proposals.values():
            if p.status == "approved" and p.source_id == source_id:
                p.status, p.decided_at, p.decided_by = "revoked", at, by
                p.reason = _short(m4.get("reason"), MAX_REASON_CHARS)
                self._note(p, "revoked", at, by)

    # -- queries ----------------------------------------------------------------------------
    def get(self, proposal_id: Any) -> Optional[Proposal]:
        with self._lock:
            return self.proposals.get(proposal_id) if isinstance(proposal_id, str) else None

    def find_pending(self, proposer: str, key: str) -> Optional[Proposal]:
        with self._lock:
            pid = self._pending_by_key.get((proposer, key))
            return self.proposals.get(pid) if pid else None

    def count_on(self, proposer: str, day: str) -> int:
        with self._lock:
            return self._day_counts.get((proposer, day), 0)

    def select(self, *, status: Optional[str] = None, proposer: Optional[str] = None, ttl_days: int,
               now: datetime) -> list:
        with self._lock:
            out = []
            for p in self.proposals.values():
                if proposer is not None and p.proposer != proposer:
                    continue
                if status not in (None, "all") and p.effective_status(ttl_days, now) != status:
                    continue
                out.append(p)
            return out

    def expired_active_sources(self, active_ttl_days: int, now: datetime,
                               is_approved_version: Optional[Callable[[str], bool]] = None) -> frozenset:
        """Source ids whose latest approval is older than ``active_ttl_days`` (0 disables expiry). With
        ``is_approved_version`` only a source whose CURRENT version came from an approval counts: a newer owner-written
        version of the same ref is exempt (owner-written memories never expire)."""
        if active_ttl_days <= 0:
            return frozenset()
        limit = timedelta(days=active_ttl_days)
        with self._lock:
            out = set()
            for p in self.proposals.values():
                if p.status == "approved" and p.source_id:
                    decided = _parse_ts(p.decided_at)
                    if decided is not None and now - decided > limit:
                        out.add(p.source_id)
        if is_approved_version is not None:
            out = {sid for sid in out if is_approved_version(sid)}
        return frozenset(out)


def _log_for(memory: Memory) -> ProposalLog:
    log = getattr(memory, "_proposal_log", None)
    if log is None:
        log = ProposalLog(memory.layout.memory_stream)
        memory._proposal_log = log
    return log.refresh()


@contextlib.contextmanager
def learning_lock(layout: Layout):
    """Exclusive cross-process lock for the check-then-append sequences of the learning lifecycle."""
    from src.storage.coordination import locked

    try:
        with locked(layout.memory_stream.with_name("learning.lock"), mode="exclusive", timeout=_LOCK_TIMEOUT):
            yield
    except ProvisioningError:
        raise
    except OSError:
        raise ProvisioningError("stream_busy", "cannot lock the learning state") from None


def _event(op: str, now: datetime, **fields: Any) -> dict:
    m4 = {"domain": DOMAIN, "op": op, **{k: v for k, v in fields.items() if v is not None}}
    return {"event_id": f"lp-{uuid.uuid4().hex[:16]}", "event_type": EVENT_TYPE, "created_at": _ts(now), "m4": m4}


def settings_for(memory: Memory) -> ls.Settings:
    return ls.load_settings(getattr(memory, "_settings_path", None))


def current_version_is_approved(memory: Memory, source_id: str) -> bool:
    """Whether the LATEST version of ``source_id`` was written by an owner approval (provenance ``tool = approve``).
    Unknown / unreadable -> ``True`` (keep the approval-based expiry; never widen visibility on an error)."""
    try:
        with memory._lock:
            registry, _blobs = memory._corpus()
            registry.refresh()
            record = registry.get_by_source_id(source_id)
        if record is None:
            return True
        return (record.provenance or {}).get("tool") == "approve"
    except Exception:  # noqa: BLE001
        return True


def expired_source_ids(memory: Memory) -> frozenset:
    """Sources a recall/context must hide because their approval outlived ``active_ttl_days`` (read time, never raises)."""
    try:
        cfg = settings_for(memory)
        if not cfg.valid or cfg.active_ttl_days <= 0:
            return frozenset()
        return _log_for(memory).expired_active_sources(
            cfg.active_ttl_days, memory._now(), lambda sid: current_version_is_approved(memory, sid))
    except Exception:  # noqa: BLE001 - a read must never fail because of the learning log
        return frozenset()


# ---------------------------------------------------------------------------------------------
# agent-facing: propose / list own / withdraw
# ---------------------------------------------------------------------------------------------
def _check_evidence(evidence: Any) -> list:
    if evidence is None:
        return []
    if isinstance(evidence, str):
        evidence = [evidence]
    if not isinstance(evidence, (list, tuple)) or len(evidence) > MAX_PROPOSE_EVIDENCE:
        raise _Invalid("invalid_evidence")
    out: list = []
    for item in evidence:
        if not isinstance(item, str):
            raise _Invalid("invalid_evidence")
        clean = " ".join(item.split())
        if not clean or len(clean) > MAX_EVIDENCE_CHARS or "\x00" in item:
            raise _Invalid("invalid_evidence")
        if clean not in out:
            out.append(clean)
    return out


def submit_proposal(memory: Memory, text: Any, memory_type: Any, name: Any, scope: Any, project_id: Any,
                    evidence: Any, source: Any) -> ProposalResult:
    """Implementation of :meth:`Memory.propose` (see there)."""
    from src.redaction.prescan import scan_bytes, scan_text

    echo = {"memory_type": memory_type if isinstance(memory_type, str) else None}
    try:
        if source not in PROPOSAL_SOURCES:
            raise _Invalid("invalid_source")
        if not isinstance(memory_type, str) or memory_type not in PROPOSABLE_TYPES:
            raise _Invalid("invalid_memory_type")
        if scope is None:
            raise _Invalid("invalid_scope")
        memory_type, scope, project_id = memory._check_target(memory_type, scope, project_id)
        name = memory._check_name(name)
        clean = memory._clean_text(text)
        if len(clean.encode("utf-8")) > MAX_PROPOSAL_BYTES:
            raise _Invalid("text_too_large")
        evid = _check_evidence(evidence)
    except _Invalid as exc:
        return ProposalResult(status="invalid", reason=exc.reason, **echo)
    echo = {"memory_type": memory_type, "scope": scope, "project_id": project_id, "name": name}
    try:
        cfg = settings_for(memory)
        if not cfg.valid:
            return ProposalResult(status="rejected", reason="settings_invalid", **echo)
        if cfg.kill_switch:
            return ProposalResult(status="rejected", reason="kill_switch", **echo)
        if cfg.effective_mode == "off":
            return ProposalResult(status="rejected", reason="learning_off", **echo)
        if source in ("agent", "learner", "peer") and not cfg.allow_agent_proposals:
            return ProposalResult(status="rejected", reason="agent_proposals_disallowed", **echo)
        scanned = [clean] + ([name] if name else []) + evid
        for item in scanned:
            verdict = scan_text(item)
            if not verdict.safe:
                return ProposalResult(status="rejected_secret", reason="secret_detected",
                                      rule_ids=tuple(verdict.rule_ids), **echo)
        verdict = scan_bytes(clean.encode("utf-8"))
        if not verdict.safe:
            return ProposalResult(status="rejected_secret", reason="secret_detected",
                                  rule_ids=tuple(verdict.rule_ids), **echo)
        if ls.matches_deny_pattern(cfg, clean, name or "", *evid):
            return ProposalResult(status="rejected", reason="deny_pattern", **echo)
        now = memory._now()
        key = dedupe_key(clean, memory_type, scope, project_id, name)
        with learning_lock(memory.layout):
            log = _log_for(memory)
            if log.overflow:
                return ProposalResult(status="rejected", reason="proposal_log_too_large", **echo)
            existing = log.find_pending(memory.profile_id, key)
            if existing is not None and existing.effective_status(cfg.proposal_ttl_days, now) == "pending":
                append_canonical_event(memory.layout.memory_stream, _event(
                    "seen", now, proposal_id=existing.proposal_id, by=memory.profile_id, evidence=evid))
                _log_for(memory)
                return ProposalResult(status="merged", proposal_id=existing.proposal_id,
                                      seen=log.get(existing.proposal_id).seen, **echo)
            if log.count_on(memory.profile_id, _ts(now)[:10]) >= cfg.max_proposals_per_day:
                return ProposalResult(status="rejected", reason="daily_limit", **echo)
            proposal_id = "p-" + uuid.uuid4().hex[:12]
            append_canonical_event(memory.layout.memory_stream, _event(
                "propose", now, proposal_id=proposal_id, proposer=memory.profile_id, source=source,
                memory_type=memory_type, scope=scope, project_id=project_id, name=name, text=clean, evidence=evid))
            _log_for(memory)
        return ProposalResult(status="proposed", proposal_id=proposal_id, seen=1, **echo)
    except ProvisioningError as exc:
        return ProposalResult(status="error", reason=exc.code, **echo)
    except Exception as exc:  # noqa: BLE001
        return ProposalResult(status="error", reason=f"internal_error:{type(exc).__name__}", **echo)


def own_proposals(memory: Memory, status: Optional[str]) -> list:
    """The caller's OWN proposals as dicts (never another profile's)."""
    if status is not None and status != "all" and status not in STATUSES:
        return []
    cfg = settings_for(memory)
    ttl = cfg.proposal_ttl_days if cfg.valid else ls.DEFAULT_PROPOSAL_TTL_DAYS
    now = memory._now()
    log = _log_for(memory)
    return [p.as_dict(ttl_days=ttl, now=now) for p in log.select(
        status=status, proposer=memory.profile_id, ttl_days=ttl, now=now)]


def own_proposal(memory: Memory, proposal_id: Any) -> Optional[dict]:
    p = _log_for(memory).get(proposal_id)
    if p is None or p.proposer != memory.profile_id:
        return None
    cfg = settings_for(memory)
    return p.as_dict(ttl_days=cfg.proposal_ttl_days if cfg.valid else ls.DEFAULT_PROPOSAL_TTL_DAYS,
                     now=memory._now(), history=True)


def withdraw_own(memory: Memory, proposal_id: Any) -> ProposalResult:
    try:
        with learning_lock(memory.layout):
            log = _log_for(memory)
            p = log.get(proposal_id)
            if p is None or p.proposer != memory.profile_id:  # another profile's id is indistinguishable from none
                return ProposalResult(status="not_found", reason="unknown_proposal")
            if p.status != "pending":
                return ProposalResult(status="not_pending", reason=p.status, proposal_id=p.proposal_id)
            append_canonical_event(memory.layout.memory_stream, _event(
                "withdraw", memory._now(), proposal_id=p.proposal_id, by=memory.profile_id))
            _log_for(memory)
        return ProposalResult(status="withdrawn", proposal_id=proposal_id)
    except ProvisioningError as exc:
        return ProposalResult(status="error", reason=exc.code)
    except Exception as exc:  # noqa: BLE001
        return ProposalResult(status="error", reason=f"internal_error:{type(exc).__name__}")


# ---------------------------------------------------------------------------------------------
# operator-facing: review
# ---------------------------------------------------------------------------------------------
class Reviewer:
    """Owner control plane: list / show / approve / reject / revoke / expire.

    NOT reachable from an agent request (no MCP tool, no ``Memory`` method). Agents must not be given a shell that can
    run ``zero-mem review``: the confirmation step is friction, not authentication (see ADR-V170-03).
    """

    def __init__(self, layout: Layout, *, operator: Optional[str] = None,
                 clock: Optional[Callable[[], datetime]] = None, settings_path=None, channel: str = "review") -> None:
        self._layout = layout
        self._operator = operator or _operator_name()
        self._clock = clock
        self._settings_path = settings_path
        self._channel = channel
        self._log = ProposalLog(layout.memory_stream)

    # -- plumbing ---------------------------------------------------------------------------
    def _now(self) -> datetime:
        return (self._clock() if self._clock else datetime.now(_UTC)).astimezone(_UTC)

    def _settings(self) -> ls.Settings:
        return ls.load_settings(self._settings_path)

    def _ttl(self) -> int:
        cfg = self._settings()
        return cfg.proposal_ttl_days if cfg.valid else ls.DEFAULT_PROPOSAL_TTL_DAYS

    def _memory(self, profile: str) -> Memory:
        mem = Memory(profile, self._layout, channel=self._channel, clock=self._clock)
        mem._settings_path = self._settings_path
        return mem

    def _append(self, op: str, **fields: Any) -> None:
        append_canonical_event(self._layout.memory_stream, _event(op, self._now(), **fields))

    # -- reads ------------------------------------------------------------------------------
    def list(self, status: Optional[str] = "pending", profile: Optional[str] = None) -> list:
        if status is not None and status != "all" and status not in STATUSES:
            return []
        cfg = self._settings()
        now = self._now()
        ttl = self._ttl()
        rows = self._log.refresh().select(status=status, proposer=profile, ttl_days=ttl, now=now)
        active = cfg.active_ttl_days if cfg.valid else 0
        out = [p.as_dict(ttl_days=ttl, now=now, active_ttl_days=active) for p in rows]
        if any(row.get("active_expired") for row in out):
            mem = self._memory("operator")
            try:
                for row in out:
                    if row.get("active_expired") and not current_version_is_approved(mem, row.get("source_id", "")):
                        row.pop("active_expired")  # replaced by an owner-written version: it does not expire
            finally:
                mem.close()
        return out

    def show(self, proposal_id: str) -> Optional[dict]:
        p = self._log.refresh().get(proposal_id)
        if p is None:
            return None
        cfg = self._settings()
        return p.as_dict(ttl_days=self._ttl(), now=self._now(),
                         active_ttl_days=cfg.active_ttl_days if cfg.valid else 0, history=True)

    # -- decisions --------------------------------------------------------------------------
    def approve(self, proposal_id: str, *, edit: Optional[str] = None, name: Optional[str] = None) -> ReviewResult:
        """Commit the proposal through the normal write path AS THE OWNER'S APPROVAL (single-write grant)."""
        try:
            with learning_lock(self._layout):
                p = self._log.refresh().get(proposal_id)
                if p is None:
                    return ReviewResult(status="not_found", reason="unknown_proposal")
                current = p.effective_status(self._ttl(), self._now())
                if current != "pending":
                    return ReviewResult(status="not_pending", reason=current, proposal_id=p.proposal_id)
                cfg = self._settings()
                if not cfg.valid:
                    return ReviewResult(status="blocked", reason="settings_invalid", proposal_id=p.proposal_id)
                if cfg.kill_switch:
                    return ReviewResult(status="blocked", reason="kill_switch", proposal_id=p.proposal_id)
                mem = self._memory(p.proposer)
                try:
                    final_text = mem._clean_text(edit) if edit is not None else p.text
                    final_name = mem._check_name(name) if name is not None else p.name
                    if len(final_text.encode("utf-8")) > MAX_PROPOSAL_BYTES:
                        raise _Invalid("text_too_large")
                except _Invalid as exc:
                    return ReviewResult(status="invalid", reason=exc.reason, proposal_id=p.proposal_id)
                if ls.matches_deny_pattern(cfg, final_text, final_name or ""):
                    return ReviewResult(status="blocked", reason="deny_pattern", proposal_id=p.proposal_id)
                approval = ApprovedWrite(p.proposal_id, p.proposer, self._operator)
                try:
                    snapshot = mem._approval_snapshot(final_text, p.memory_type, final_name, p.scope, p.project_id)
                    written = mem._apply_approved_write(
                        approval, final_text, p.memory_type, final_name, p.scope, p.project_id,
                        {"proposal": p.proposal_id, "proposer": p.proposer, "approver": self._operator[:64],
                         "proposed_by": p.source})
                    if not written.ok:
                        status = written.status if written.status in ("rejected_secret", "rejected_content", "invalid") \
                            else "error"
                        return ReviewResult(status=status, reason=written.reason, proposal_id=p.proposal_id,
                                            write_status=written.status)
                    superseded = written.status == "updated"
                    try:
                        self._append(
                            "approve", proposal_id=p.proposal_id, proposer=p.proposer,
                            approved_by=self._operator[:64], source_id=written.source_id,
                            external_ref=written.external_ref, version=written.version, scope=written.scope,
                            memory_type=written.memory_type, write_status=written.status,
                            final_text=final_text if final_text != p.text else None, final_name=final_name,
                            basis=APPROVAL_BASIS)
                    except Exception as exc:  # noqa: BLE001
                        # the source is committed but the canonical approval is not: undo it so that no active source
                        # exists without an approval record. A retry of approve is idempotent either way (an
                        # unchanged write commits nothing new).
                        undone = False
                        try:
                            undone = mem._undo_approved_write(approval, written, snapshot, final_name)
                        except Exception:  # noqa: BLE001
                            undone = False
                        code = exc.code if isinstance(exc, ProvisioningError) else f"internal_error:{type(exc).__name__}"
                        return ReviewResult(status="error", reason=code if undone else "approval_not_recorded",
                                            proposal_id=p.proposal_id,
                                            detail=None if undone else {"source_id": written.source_id})
                finally:
                    mem.close()
                self._log.refresh()
            return ReviewResult(status="approved", proposal_id=p.proposal_id, source_id=written.source_id,
                                external_ref=written.external_ref, version=written.version,
                                write_status=written.status, superseded=superseded)
        except ProvisioningError as exc:
            return ReviewResult(status="error", reason=exc.code)
        except Exception as exc:  # noqa: BLE001
            return ReviewResult(status="error", reason=f"internal_error:{type(exc).__name__}")

    def reject(self, proposal_id: str, reason: Optional[str] = None) -> ReviewResult:
        if reason is not None and (not isinstance(reason, str) or len(reason) > MAX_REASON_CHARS):
            return ReviewResult(status="invalid", reason="invalid_reason")
        try:
            with learning_lock(self._layout):
                p = self._log.refresh().get(proposal_id)
                if p is None:
                    return ReviewResult(status="not_found", reason="unknown_proposal")
                current = p.effective_status(self._ttl(), self._now())
                if current != "pending":
                    return ReviewResult(status="not_pending", reason=current, proposal_id=p.proposal_id)
                self._append("reject", proposal_id=p.proposal_id, by=self._operator[:64], reason=reason or None)
                self._log.refresh()
            return ReviewResult(status="rejected", proposal_id=proposal_id)
        except ProvisioningError as exc:
            return ReviewResult(status="error", reason=exc.code)
        except Exception as exc:  # noqa: BLE001
            return ReviewResult(status="error", reason=f"internal_error:{type(exc).__name__}")

    def revoke(self, ref: str, reason: Optional[str] = None) -> ReviewResult:
        """Revoke an active item (source id, unique prefix or ``mem://`` ref): the existing forget tombstone."""
        if not isinstance(ref, str) or not 4 <= len(ref.strip()) <= 600:
            return ReviewResult(status="invalid", reason="invalid_source_id")
        try:
            with learning_lock(self._layout):
                mem = self._memory("operator")
                try:
                    forgot = mem._operator_forget(ref.strip())
                finally:
                    mem.close()
                if forgot.status == "not_found":
                    return ReviewResult(status="not_found", reason=forgot.reason)
                if forgot.status == "ambiguous":
                    return ReviewResult(status="invalid", reason="multiple_sources_match",
                                        detail={"candidates": list(forgot.candidates)})
                if forgot.status not in ("forgotten", "already_forgotten"):
                    return ReviewResult(status="error", reason=forgot.reason or forgot.status)
                self._append("revoke", source_id=forgot.source_id, external_ref=forgot.external_ref,
                             by=self._operator[:64], reason=_short(reason, MAX_REASON_CHARS))
                self._log.refresh()
            return ReviewResult(status="revoked", source_id=forgot.source_id, external_ref=forgot.external_ref,
                                version=forgot.version, write_status=forgot.status)
        except ProvisioningError as exc:
            return ReviewResult(status="error", reason=exc.code)
        except Exception as exc:  # noqa: BLE001
            return ReviewResult(status="error", reason=f"internal_error:{type(exc).__name__}")

    def expire(self) -> ReviewResult:
        """Record every pending proposal past ``proposal_ttl_days`` as expired; list approved items past
        ``active_ttl_days`` (those are already hidden from recall/context at read time)."""
        try:
            with learning_lock(self._layout):
                log = self._log.refresh()
                cfg = self._settings()
                ttl = self._ttl()
                now = self._now()
                ids = [p.proposal_id for p in log.select(status="expired", ttl_days=ttl, now=now)
                       if p.status == "pending"]
                for pid in ids:
                    self._append("expire", proposal_id=pid, by="system", reason="proposal_ttl")
                active = []
                if cfg.valid and cfg.active_ttl_days > 0:
                    mem = self._memory("operator")
                    try:
                        hidden = log.expired_active_sources(
                            cfg.active_ttl_days, now, lambda sid: current_version_is_approved(mem, sid))
                    finally:
                        mem.close()
                    active = [{"proposal_id": p.proposal_id, "source_id": p.source_id, "external_ref": p.external_ref}
                              for p in log.proposals.values() if p.status == "approved" and p.source_id in hidden]
                self._log.refresh()
            return ReviewResult(status="expired", detail={"proposals_expired": ids, "active_hidden": active})
        except ProvisioningError as exc:
            return ReviewResult(status="error", reason=exc.code)
        except Exception as exc:  # noqa: BLE001
            return ReviewResult(status="error", reason=f"internal_error:{type(exc).__name__}")


__all__ = [
    "ApprovedWrite", "EVENT_TYPE", "PROPOSABLE_TYPES", "PROPOSAL_SOURCES", "Proposal", "ProposalLog", "ProposalResult",
    "ReviewResult", "Reviewer", "STATUSES", "dedupe_key", "expired_source_ids", "learning_lock",
]
