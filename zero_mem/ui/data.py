"""Read-only data helpers of the control panel: the source inventory and the canonical audit log.

Nothing here writes. The inventory reads the canonical corpus registry through the same registry class ``Memory`` uses;
the audit log tails the canonical event stream (``events-v1.jsonl``) and the registry (writes and forgets are registry
versions). Both are bounded so a very large store cannot stall the panel.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

TAIL_BYTES = 6 * 1024 * 1024
PAGE_SIZE = 50
MAX_PAGES = 40


@dataclass(frozen=True)
class SourceRow:
    source_id: str
    external_ref: str
    memory_type: str
    scope: str
    profile_id: Optional[str]
    project_id: Optional[str]
    version: Optional[str]
    created_at: str
    kind: str
    expired: bool = False


def scope_of(record: Any, shared_space: str) -> str:
    if record.knowledge_space_id == shared_space:
        return "shared"
    if record.project_id is not None:
        return "project"
    if record.profile_id is None and record.knowledge_space_id is None:
        return "global"
    return "private"


def live_rows(memory, *, readable_only: bool) -> list:
    """Latest live (not forgotten) sources, newest first. ``readable_only`` restricts to what the memory's profile may read."""
    registry, _blobs = memory._corpus()
    registry.refresh()
    latest: dict = {}
    for rec in registry.all_records():
        latest[rec.source_id] = rec
    can_read = memory._reader() if readable_only else (lambda _record: True)
    expired = memory._expired_sources()
    rows = []
    for rec in latest.values():
        if rec.lifecycle_status == "deleted" or not can_read(rec):
            continue
        rows.append(SourceRow(
            source_id=rec.source_id, external_ref=rec.external_ref,
            memory_type=(rec.custom_meta or {}).get("memory_type") or "unknown",
            scope=scope_of(rec, memory.shared_space), profile_id=rec.profile_id, project_id=rec.project_id,
            version=rec.source_version_id, created_at=rec.created_at, kind=rec.kind, expired=rec.source_id in expired))
    rows.sort(key=lambda r: (r.created_at, r.source_id), reverse=True)
    return rows


def latest_record(memory, source_id: str, *, readable_only: bool = True):
    """The newest registry record of ``source_id`` if the memory's profile may read it (else ``None``)."""
    registry, _blobs = memory._corpus()
    registry.refresh()
    record = registry.get_by_source_id(source_id)
    if record is None:
        return None
    if readable_only and not memory._reader()(record):
        return None
    return record


def read_blob_text(memory, record, limit: int = 64 * 1024) -> tuple:
    """``(text or None, size, truncated)``; ``None`` text for binary content (docx, images, ...)."""
    _registry, blobs = memory._corpus()
    if record.blob_ref is None:
        return None, 0, False
    try:
        data = blobs.get(record.blob_ref)
    except Exception:  # noqa: BLE001
        return None, 0, False
    size = len(data)
    chunk = data[:limit]
    if b"\x00" in chunk:
        return None, size, False
    try:
        text = chunk.decode("utf-8")
    except UnicodeDecodeError:
        if size > limit:  # a multibyte character cut by the limit
            try:
                text = chunk[:-3].decode("utf-8")
            except UnicodeDecodeError:
                return None, size, False
        else:
            return None, size, False
    return text, size, size > limit


# ------------------------------------------------------------------------------------------------ audit log
def _tail_lines(path: Path, limit: int = TAIL_BYTES) -> list:
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            start = max(0, size - limit)
            handle.seek(start)
            data = handle.read(limit)
    except OSError:
        return []
    lines = data.splitlines()
    if start > 0 and lines:
        lines = lines[1:]  # the first line of a window may be cut
    return lines


def _describe_event(rec: dict) -> Optional[dict]:
    kind = rec.get("event_type")
    m4 = rec.get("m4") if isinstance(rec.get("m4"), dict) else {}
    when = str(rec.get("created_at") or "")
    if kind == "learning_proposal":
        op = m4.get("op")
        actor = m4.get("approved_by") or m4.get("by") or m4.get("proposer") or ""
        detail = m4.get("external_ref") or m4.get("reason") or m4.get("text") or ""
        target = m4.get("proposal_id") or m4.get("source_id") or ""
        return {"at": when, "category": "proposal", "action": str(op), "actor": actor, "target": target,
                "detail": str(detail)[:240]}
    if kind == "operator_approval":
        return {"at": when, "category": "approval", "action": str(m4.get("op")),
                "actor": m4.get("approved_by") or m4.get("revoked_by") or "",
                "target": f"{m4.get('subject_profile', '')} {m4.get('operation', '')} {m4.get('target_type', '')}:{m4.get('target_id', '')}".strip(),
                "detail": str(m4.get("basis") or "")[:240]}
    if kind == "access_grant":
        return {"at": when, "category": "grant", "action": str(m4.get("op")), "actor": "",
                "target": f"{m4.get('subject_profile', '')} {m4.get('operation', '')} {m4.get('target_type', '')}:{m4.get('target_id', '')}",
                "detail": ""}
    if kind == "agent_profile":
        return {"at": when, "category": "agent", "action": str(m4.get("op")), "actor": m4.get("added_by") or "",
                "target": str(m4.get("profile_id") or ""), "detail": ""}
    if kind == "policy_decision":
        return {"at": when, "category": "policy", "action": "allow" if m4.get("allow") else "deny",
                "actor": str(m4.get("requester") or ""), "target": str(m4.get("target_scope") or ""),
                "detail": str(m4.get("reason_code") or "")}
    return {"at": when, "category": str(kind or "event"), "action": str(m4.get("op") or ""), "actor": "", "target": "",
            "detail": ""}


def audit_events(layout, page: int = 1, page_size: int = PAGE_SIZE) -> tuple:
    """``(rows for the page, has_next)`` of recent canonical events (stream + corpus writes/forgets), newest first."""
    events: list = []
    for raw in _tail_lines(layout.memory_stream):
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        if isinstance(rec, dict):
            row = _describe_event(rec)
            if row:
                events.append(row)
    registry_path = Path(layout.corpus_root) / "corpus_sources.jsonl"
    for raw in _tail_lines(registry_path):
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        prov = rec.get("provenance") if isinstance(rec.get("provenance"), dict) else {}
        deleted = rec.get("lifecycle_status") == "deleted"
        events.append({
            "at": str(rec.get("created_at") or ""), "category": "forget" if deleted else "write",
            "action": "forgotten" if deleted else str(prov.get("tool") or "write"),
            "actor": str(prov.get("profile") or rec.get("profile_id") or ""),
            "target": str(rec.get("external_ref") or ""),
            "detail": f"via {prov.get('channel', '?')}; version {rec.get('source_version_id', '')}"})
    for index, row in enumerate(events):
        row["_n"] = index
    # newest first; events inside one second keep their file order (later = newer)
    events.sort(key=lambda row: (row["at"][:19], row["_n"]), reverse=True)
    for row in events:
        row.pop("_n", None)
    page = max(1, min(int(page), MAX_PAGES))
    start = (page - 1) * page_size
    chunk = events[start:start + page_size]
    return chunk, len(events) > start + page_size


def last_writes(layout, count: int = 5) -> list:
    rows, _more = audit_events(layout, 1, 200)
    return [r for r in rows if r["category"] in ("write", "forget")][:count]


def inventory(memory) -> dict:
    """Counts of live sources by type and scope (owner view: every profile) plus the forgotten count."""
    registry, _blobs = memory._corpus()
    registry.refresh()
    latest: dict = {}
    for rec in registry.all_records():
        latest[rec.source_id] = rec
    by_type: dict = {}
    by_scope: dict = {}
    forgotten = 0
    for rec in latest.values():
        if rec.lifecycle_status == "deleted":
            forgotten += 1
            continue
        t = (rec.custom_meta or {}).get("memory_type") or "unknown"
        s = scope_of(rec, memory.shared_space)
        by_type[t] = by_type.get(t, 0) + 1
        by_scope[s] = by_scope.get(s, 0) + 1
    return {"total": sum(by_type.values()), "forgotten": forgotten, "by_type": by_type, "by_scope": by_scope}
