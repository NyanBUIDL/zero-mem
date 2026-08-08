"""M4.7 — deterministic project-memory rebuild from canonical evidence.

Implements the approved ``rebuild_project_memory`` entrypoint. It reprojects the
six M4 derived tables (zm_project_charters, zm_requirements, zm_decisions,
zm_project_state, zm_verifications, zm_project_artifacts) from canonical JSONL
events that carry an explicit structured ``m4`` block.

Design constraints (from the approved M4 plan):
- Canonical JSONL is authoritative; SQLite derived state is disposable/rebuildable.
- The SAME per-event projection loop drives both the incremental path and the
  full-rebuild path, so incremental == rebuild is structural (not asserted by
  accident).
- Deterministic, idempotent: reprocessing the same canonical event never
  duplicates a row/link/supersession.
- No LLM calls, no network calls.
- No inference: identity/subject/supersession come ONLY from the explicit ``m4``
  block; trace_id is provenance only, never a logical key.
- The rebuild never mutates canonical JSONL, never alters artifact content, never
  writes to M2 surfaces (only the six M4 derived tables).

The canonical M4 event envelope (a JSONL object):

    {
      "event_id": "E1",
      "event_type": "m4_charter",          # provenance only (promotion guard)
      "trace_id": "T1", "session_id": "S1", "profile_id": "P1",
      "created_at": "2026-08-01T00:00:00Z",
      "m4": {
        "domain": "charter",               # one of the 6 M4 domains
        "identity": "C1",                  # explicit stable id
        "op": "create",                    # create/update/supersede/transition/delete
        "project_id": "P",
        ... domain fields (match Op field names) ...
      }
    }

``classify_event_for_m4`` decides whether an event is projected; events without an
explicit ``m4`` block are skipped (no inference, no invention).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from src.project_memory.projector import (
    project_charter,
    project_requirement,
    project_decision,
    project_state,
    project_verification,
    project_artifact,
    classify_event_for_m4,
    CLASSIFY_CHARTER,
    CLASSIFY_REQUIREMENT,
    CLASSIFY_DECISION,
    CLASSIFY_STATE,
    CLASSIFY_VERIFICATION,
    CLASSIFY_PROJECT_ARTIFACT,
)
from src.project_memory.contracts import (
    CharterOp,
    RequirementOp,
    DecisionOp,
    StateOp,
    VerificationOp,
    ArtifactOp,
    M4ProjectionError,
    ConflictError,
    InvalidTransitionError,
)

# The six M4 derived tables (dropped/recreated on a full rebuild).
M4_TABLES = (
    "zm_project_charters",
    "zm_requirements",
    "zm_decisions",
    "zm_project_state",
    "zm_verifications",
    "zm_project_artifacts",
)

_PROJECTORS = {
    CLASSIFY_CHARTER: project_charter,
    CLASSIFY_REQUIREMENT: project_requirement,
    CLASSIFY_DECISION: project_decision,
    CLASSIFY_STATE: project_state,
    CLASSIFY_VERIFICATION: project_verification,
    CLASSIFY_PROJECT_ARTIFACT: project_artifact,
}

_OP_CLASSES = {
    CLASSIFY_CHARTER: CharterOp,
    CLASSIFY_REQUIREMENT: RequirementOp,
    CLASSIFY_DECISION: DecisionOp,
    CLASSIFY_STATE: StateOp,
    CLASSIFY_VERIFICATION: VerificationOp,
    CLASSIFY_PROJECT_ARTIFACT: ArtifactOp,
}


def event_to_op(event: dict):
    """Convert a canonical M4-bearing event into the matching typed Op envelope.

    Reads the explicit ``m4`` block for domain fields and the event top-level
    fields for provenance. Never infers identity; trace_id is carried as
    provenance only. Raises if the event is not an M4 event.
    """
    m4 = event.get("m4")
    if not isinstance(m4, dict):
        raise ValueError("event has no m4 block")
    kind = classify_event_for_m4(event)
    if kind not in _OP_CLASSES:
        raise ValueError(f"event is not a projectable M4 event: {kind}")
    OpClass = _OP_CLASSES[kind]

    # Domain fields come from the m4 block, minus the classifier metadata.
    domain_fields = {
        k: v for k, v in m4.items() if k not in ("domain", "identity")
    }
    # Map the explicit structured identity -> the Op's id field.
    # StateOp has no single identity arg; identity is informational (state_key is
    # a domain field carried in m4). So only map identity for the 5 id-keyed domains.
    if kind in (CLASSIFY_CHARTER, CLASSIFY_REQUIREMENT, CLASSIFY_DECISION,
                CLASSIFY_VERIFICATION, CLASSIFY_PROJECT_ARTIFACT):
        id_field = {
            CLASSIFY_CHARTER: "charter_id",
            CLASSIFY_REQUIREMENT: "requirement_id",
            CLASSIFY_DECISION: "decision_id",
            CLASSIFY_VERIFICATION: "verification_id",
            CLASSIFY_PROJECT_ARTIFACT: "artifact_id",
        }[kind]
        domain_fields[id_field] = m4.get("identity")

    # Top-level provenance.
    provenance = {
        "source_event_id": event.get("event_id"),
        "trace_id": event.get("trace_id"),
        "session_id": event.get("session_id"),
        "profile_id": event.get("profile_id"),
        "created_at": event.get("created_at"),
        "derived_from_event_type": event.get("event_type"),
    }
    merged = {**domain_fields, **provenance}
    # Filter to declared Op fields (Op dataclass rejects unexpected kwargs).
    params = OpClass.__dataclass_fields__.keys()  # type: ignore[attr-defined]
    filtered = {k: v for k, v in merged.items() if k in params}
    return OpClass(**filtered)


def _project_event(conn, event: dict) -> Optional[str]:
    """Project a single canonical event into the M4 derived tables.

    Returns the classification kind if projected, else None. Sanitized M4
    projection errors are propagated (they indicate malformed canonical data,
    which must surface rather than be silently skipped).
    """
    kind = classify_event_for_m4(event)
    if kind not in _PROJECTORS:
        return None
    op = event_to_op(event)
    try:
        _PROJECTORS[kind](conn, op)
    except (ConflictError, InvalidTransitionError):
        # Recoverable / explicit-conflict outcomes are part of correct rebuild
        # semantics: an explicit `conflicted` lifecycle is stored as-is (no winner,
        # no overwrite); replaying the same op yields the same state (idempotent).
        # These must NOT abort the rebuild. Genuine schema/integrity errors
        # propagate unchanged below.
        conn.rollback()
    return kind


def _recreate_m4_tables(conn) -> None:
    """Idempotently (re)create the six M4 derived tables.

    ``ensure_schema()`` is a no-op once the v7 ledger row exists, so a full
    rebuild that drops the six tables would otherwise leave them missing. We
    recreate them directly from the v7 migration, which is re-runnable: each
    ``CREATE TABLE IF NOT EXISTS`` is a no-op if the table already exists, and
    the partial unique indexes carry the same guard. M2 surfaces are untouched.
    """
    from src.storage.migrations.migrate_7 import up as migrate_7_up
    conn.execute("BEGIN")
    try:
        migrate_7_up(conn, note="m4.7_rebuild")
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise


def rebuild_project_memory(store, jsonl_path, project_id: Optional[str] = None) -> dict:
    """Project all M4-bearing events from a canonical JSONL file into the store.

    This is the SAME per-event loop used by the incremental projector path:
    replaying the full file from an empty store yields the rebuilt state, and
    replaying events as they stream yields the incremental state. Both are
    identical because the projection is deterministic and idempotent.

    If ``project_id`` is given, only events whose ``m4.project_id`` matches are
    projected (other projects remain untouched).

    Returns a summary dict: {projected, skipped, by_domain}.
    """
    path = Path(jsonl_path)
    conn = store._conn
    by_domain: dict = {}
    projected = 0
    skipped = 0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                skipped += 1
                continue
            if not isinstance(event, dict):
                skipped += 1
                continue
            kind = classify_event_for_m4(event)
            if kind not in _PROJECTORS:
                skipped += 1
                continue
            m4 = event["m4"]
            if project_id is not None and m4.get("project_id") != project_id:
                skipped += 1
                continue
            before = by_domain.get(kind, 0)
            _project_event(conn, event)
            # Recoverable conflict/idempotent ops still count as processed.
            by_domain[kind] = before + 1
            projected += 1
    return {"projected": projected, "skipped": skipped, "by_domain": by_domain}


def rebuild_all_project_memory(store, jsonl_path, project_id: Optional[str] = None) -> dict:
    """Full rebuild: drop the six M4 derived tables, recreate them, replay.

    Canonical JSONL is never modified. M2 surfaces are untouched (only the six
    M4 tables are dropped/recreated). The recreate step uses the v7 migration
    directly so it works even though the schema ledger already records v7
    (``ensure_schema`` would otherwise be a no-op). Returns the per-event summary.
    """
    conn = store._conn
    conn.execute("BEGIN")
    try:
        for table in M4_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    _recreate_m4_tables(conn)
    return rebuild_project_memory(store, jsonl_path, project_id=project_id)


__all__ = [
    "M4_TABLES",
    "event_to_op",
    "rebuild_project_memory",
    "rebuild_all_project_memory",
]
