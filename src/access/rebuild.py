"""M5.6 — deterministic policy-state rebuild from canonical JSONL.

Reconstructs the M5 DERIVED policy tables (``zm_access_grants``,
``zm_policy_audit``) from their canonical source events (``access_grant``,
``policy_decision`` JSONL lines). SQLite remains derived/disposable; JSONL remains
authoritative.

Scope is NARROW: only the two M5 policy tables are dropped/rebuilt. All M0-M4
derived tables, M4 project memory, artifacts, FTS, relations/scopes, verification
records, and the canonical JSONL itself are preserved untouched.

The rebuild reuses the EXACT projection functions used by the incremental path
(``project_grant_event`` / ``project_policy_decision``), so incremental projection
and full rebuild are provably parity-equivalent by construction.

No LLM, no network. Deterministic (order-dependent replay, no timestamp-now state,
no generated identity).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Optional, Union

from .grant_events import AccessGrantEvent, project_grant_event
from .audit import project_policy_decision

# Canonical event types that belong to the M5 policy layer.
_POLICY_EVENT_TYPES = ("access_grant", "policy_decision")

# M5 derived tables managed by this rebuild (narrow scope).
M5_POLICY_TABLES = ("zm_access_grants", "zm_policy_audit")


def iter_canonical_policy_events(jsonl_paths: Union[Path, str, Iterable[Union[Path, str]]]) -> List[dict]:
    """Yield canonical M5 policy events (access_grant / policy_decision) from JSONL.

    Unknown / non-policy event types are skipped (JSONL remains authoritative and
    may contain M0-M4 memory events that this rebuild does not touch).
    """
    if isinstance(jsonl_paths, (str, Path)):
        paths: List[Path] = [Path(jsonl_paths)]
    else:
        paths = [Path(p) for p in jsonl_paths]
    events: List[dict] = []
    for path in paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict):
                    continue
                if rec.get("event_type") in _POLICY_EVENT_TYPES:
                    events.append(rec)
    return events


def _clear_m5_policy_tables(conn) -> None:
    """Drop only M5 derived policy rows (preserves M0-M4 state)."""
    cur = conn.cursor()
    for table in M5_POLICY_TABLES:
        cur.execute(f"DELETE FROM {table}")


def rebuild_policy_state(conn, jsonl_paths: Union[Path, str, Iterable[Union[Path, str]]]) -> dict:
    """Rebuild M5 derived policy tables from canonical JSONL (idempotent, repeatable).

    Returns a summary dict with counts. Caller manages the transaction boundary
    (commit) if atomicity across the whole batch is required; the projection
    functions are each individually safe.
    """
    events = iter_canonical_policy_events(jsonl_paths)
    _clear_m5_policy_tables(conn)

    grant_rows = 0
    audit_rows = 0
    for rec in events:
        etype = rec.get("event_type")
        if etype == "access_grant":
            ev = AccessGrantEvent.from_canonical_dict(rec)
            if ev is None:
                continue
            project_grant_event(conn, ev)
            grant_rows += 1
        elif etype == "policy_decision":
            project_policy_decision(conn, rec)
            audit_rows += 1
    return {
        "grant_events": grant_rows,
        "audit_events": audit_rows,
        "tables": list(M5_POLICY_TABLES),
    }


def normalize_grants(conn) -> List[tuple]:
    """Return grants as sort-stable tuples (excludes rowid/insertion order)."""
    rows = conn.execute(
        "SELECT grant_id, subject_profile, operation, target_type, target_id, "
        "resource_types, state, lifecycle_status, supersedes, replaced_by, "
        "verification_ref FROM zm_access_grants ORDER BY grant_id"
    ).fetchall()
    return [tuple(r) for r in rows]


def normalize_audit(conn) -> List[tuple]:
    """Return audit rows as sort-stable tuples (excludes rowid/insertion order)."""
    rows = conn.execute(
        "SELECT decision_id, operation, requester, target_scope, allow, reason_code, "
        "grant_refs FROM zm_policy_audit ORDER BY decision_id"
    ).fetchall()
    return [tuple(r) for r in rows]


__all__ = [
    "iter_canonical_policy_events",
    "rebuild_policy_state",
    "normalize_grants",
    "normalize_audit",
    "M5_POLICY_TABLES",
]
