"""Typed results of :class:`zero_mem.memory.Memory` operations.

Every public operation returns one of these; nothing raises on a denied, rejected or invalid request, so
callers (CLI, MCP write tools) branch on ``status``/``reason`` instead of catching exceptions. All of them are
JSON-safe through ``as_dict()``. No result ever carries content that was rejected as a secret (only fixed rule ids).
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Optional

#: Statuses of a single write that left the store consistent and the content stored.
OK_WRITE_STATUSES = frozenset({"created", "updated", "unchanged"})
#: Every write status: the first three succeed; the rest name WHY nothing was stored.
WRITE_STATUSES = OK_WRITE_STATUSES | {
    "rejected_secret",   # a credential was detected before anything was persisted
    "rejected_content",  # unsupported / corrupt / empty / parser-unavailable content
    "denied",            # authorization (reason = the M5 reason code)
    "invalid",           # closed-schema validation (reason = invalid_<field> ...)
    "error",             # unexpected failure (reason = a fixed code)
}


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


@dataclass(frozen=True)
class WriteResult:
    status: str
    reason: Optional[str] = None
    name: Optional[str] = None
    source_id: Optional[str] = None
    external_ref: Optional[str] = None
    memory_type: Optional[str] = None
    scope: Optional[str] = None
    profile_id: Optional[str] = None
    project_id: Optional[str] = None
    knowledge_space_id: Optional[str] = None
    version: Optional[str] = None
    units: Optional[int] = None
    extraction: Optional[str] = None
    rule_ids: tuple = ()

    @property
    def ok(self) -> bool:
        return self.status in OK_WRITE_STATUSES

    def as_dict(self) -> dict:
        out = {f.name: getattr(self, f.name) for f in fields(self)}
        out = {k: v for k, v in out.items() if v not in (None, ())}
        out["ok"] = self.ok
        return _clean(out)


@dataclass(frozen=True)
class IngestReport:
    """Outcome of ``Memory.ingest``: one :class:`WriteResult` per attempted file plus the skip report."""

    status: str  # ok | partial | denied | invalid | error
    reason: Optional[str] = None
    files: list = field(default_factory=list)
    skipped: list = field(default_factory=list)  # [{"name": ..., "reason": ...}]
    counts: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def as_dict(self) -> dict:
        out: dict = {"ok": self.ok, "status": self.status, "counts": dict(self.counts),
                     "files": [f.as_dict() for f in self.files], "skipped": [dict(s) for s in self.skipped]}
        if self.reason:
            out["reason"] = self.reason
        return out


#: Skip reasons that are expected for ordinary trees and never make an ingest "partial".
BENIGN_SKIPS = frozenset({"hidden", "excluded_dir", "symlink", "empty", "unsupported_binary", "not_regular_file"})
_COUNT_KEYS = ("created", "updated", "unchanged", "rejected_secret", "rejected_content", "invalid", "denied", "error")


def build_ingest_report(status: Optional[str], reason: Optional[str], results: list, skipped: list) -> IngestReport:
    """Aggregate per-file results; ``status=None`` derives ok/partial (rejections or non-benign skips = partial)."""
    counts = {k: 0 for k in _COUNT_KEYS}
    for res in results:
        counts[res.status] = counts.get(res.status, 0) + 1
    counts["skipped"] = len(skipped)
    if status is None:
        bad = sum(counts[k] for k in ("rejected_secret", "rejected_content", "invalid", "denied", "error"))
        loud = [s for s in skipped if s.get("reason") not in BENIGN_SKIPS]
        status = "ok" if not bad and not loud else "partial"
    return IngestReport(status=status, reason=reason, files=list(results), skipped=list(skipped), counts=counts)


@dataclass(frozen=True)
class RecallHit:
    text: str
    score: float
    external_ref: Optional[str]
    memory_type: Optional[str]
    source_id: str
    unit_id: str
    unit_kind: str
    scope: str  # shared | private | project | global
    profile_id: Optional[str] = None
    project_id: Optional[str] = None
    knowledge_space_id: Optional[str] = None
    page: Optional[int] = None

    def as_dict(self) -> dict:
        out = {f.name: getattr(self, f.name) for f in fields(self)}
        return {k: v for k, v in out.items() if v is not None}


@dataclass(frozen=True)
class RecallResult:
    """Ranked hits. Iterates / indexes / ``len()`` like the list of hits."""

    status: str  # ok | empty | denied | invalid | error
    reason: Optional[str] = None
    hits: list = field(default_factory=list)
    notes: dict = field(default_factory=dict)  # per sub-request decision codes, e.g. {"shared": "ALLOW_GLOBAL_READ"}

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "empty")

    def __iter__(self):
        return iter(self.hits)

    def __len__(self) -> int:
        return len(self.hits)

    def __getitem__(self, index):
        return self.hits[index]

    def as_dict(self) -> dict:
        out: dict = {"ok": self.ok, "status": self.status, "hits": [h.as_dict() for h in self.hits]}
        if self.reason:
            out["reason"] = self.reason
        if self.notes:
            out["notes"] = dict(self.notes)
        return out


@dataclass(frozen=True)
class ContextBundle:
    """Compact session-start bundle (``text``) plus what went into it."""

    status: str  # ok | empty | invalid | error
    text: str = ""
    reason: Optional[str] = None
    sections: dict = field(default_factory=dict)  # section -> number of items included
    sources: list = field(default_factory=list)   # external refs included, in order
    truncated: bool = False
    max_chars: int = 0

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "empty")

    def __str__(self) -> str:
        return self.text

    def as_dict(self) -> dict:
        out: dict = {"ok": self.ok, "status": self.status, "text": self.text, "chars": len(self.text),
                     "max_chars": self.max_chars, "truncated": self.truncated,
                     "sections": dict(self.sections), "sources": list(self.sources)}
        if self.reason:
            out["reason"] = self.reason
        return out


@dataclass(frozen=True)
class ForgetResult:
    status: str  # forgotten | already_forgotten | not_found | ambiguous | denied | invalid | error
    reason: Optional[str] = None
    source_id: Optional[str] = None
    external_ref: Optional[str] = None
    memory_type: Optional[str] = None
    version: Optional[str] = None
    candidates: tuple = ()  # for status == "ambiguous": the matching source ids

    @property
    def ok(self) -> bool:
        return self.status in ("forgotten", "already_forgotten")

    def as_dict(self) -> dict:
        out = {f.name: getattr(self, f.name) for f in fields(self)}
        out = {k: v for k, v in out.items() if v not in (None, ())}
        out["ok"] = self.ok
        return _clean(out)


__all__ = [
    "BENIGN_SKIPS", "build_ingest_report", "ContextBundle", "ForgetResult", "IngestReport", "OK_WRITE_STATUSES", "RecallHit", "RecallResult",
    "WRITE_STATUSES", "WriteResult",
]
