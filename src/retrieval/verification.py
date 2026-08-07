"""M3.5 — deterministic, sanitized, TRUE READ-ONLY verification / lifecycle-aware retrieval.

This module adds the M3.5 layer on top of the already-verified M3.1 structured query
(note: ``query_events`` ALREADY supports ``verification_status`` / ``lifecycle_status`` /
``event_type`` exact AND filters and excludes ``deleted`` by default — M3.5 refines that with
value validation and enrichment), M3.3 FTS, and M3.4 relations.

Behavior (schema-truthful, no inference):
- Verification / lifecycle filters are EXACT deterministic equality over the stored
  ``zm_meta`` columns. Unknown status values raise a fixed sanitized error instead of
  silently querying.
- ``assistant_claim`` / ``user_statement`` / ``inference`` / ``tool_observation`` / ``verified_state``
  are surfaced as ``event_type`` labels only. An unverified ``assistant_claim`` is NEVER promoted
  to a fact; verification/lifecycle state never changes ordering.
- Provenance is enriched from the verified M2 ``zm_provenance`` projection (verifier /
  evidence_ref / verification_status / recorded_at). Stored ``confidence`` is returned as-is.
- Supersession / conflict / archived states are returned verbatim from ``zm_lifecycle``; M3.5
  invents no replacement relationship, chooses no winner, and applies no LLM reasoning.
- The administrative deleted-inspection path (``list_deleted`` / ``get_tombstone`` /
  ``get_deletion_audit``) is exposed read-only; it is the ONLY sanctioned route to deleted records
  and is separate from normal retrieval (Decision B).
- FTS composition: ``search_filtered`` selects text candidates via M3.3 FTS5 and then applies the
  same verification / lifecycle filters. No ranking by verification/recency/confidence.

No writes, no LLM, no network, no schema migration. All queries run against a ``ReadonlyStore``.
"""

from __future__ import annotations

from typing import List, Optional

from .db import ReadonlyStore
from . import cursor as cursor_mod
from . import query as query_mod
from . import search as search_mod
from .models import (
    INVALID_VERIFICATION_STATUS,
    INVALID_LIFECYCLE_STATUS,
    QueryError,
    ProvenanceMeta,
    SearchResult,
)

# Status vocabularies are taken VERBATIM from the verified M1/M2 contract
# (src/capture/event_types.py). M3.5 must not invent statuses. "deleted" is accepted only on the
# administrative deleted-inspection path, never on the normal retrieval path.
from src.capture.event_types import LifecycleStatus, VerificationStatus  # noqa: E402

_VALID_VERIFICATION_STATUSES = tuple(v.value for v in VerificationStatus)
_VALID_LIFECYCLE_STATUSES = tuple(s.value for s in LifecycleStatus)


def validate_verification_status(value: str) -> str:
    if not isinstance(value, str) or value not in _VALID_VERIFICATION_STATUSES:
        raise QueryError(code=INVALID_VERIFICATION_STATUS, message=f"unknown_verification_status:{value}")
    return value


def validate_lifecycle_status(value: str) -> str:
    if not isinstance(value, str) or value not in _VALID_LIFECYCLE_STATUSES:
        raise QueryError(code=INVALID_LIFECYCLE_STATUS, message=f"unknown_lifecycle_status:{value}")
    return value


# ---------------------------------------------------------------------------
# Provenance enrichment (read-only over verified M2 zm_provenance)
# ---------------------------------------------------------------------------
def get_provenance(store: ReadonlyStore, event_id: str) -> Optional[ProvenanceMeta]:
    """Return provenance metadata for an event (latest zm_provenance row), or None.

    Read-only wrapper over the verified M2 ``get_provenance`` helper. Surfaces only the
    already-projected fields; never recomputes or reinterprets confidence/verification.
    """
    if not isinstance(event_id, str) or not event_id:
        raise QueryError(code="invalid_query", message="non_string_event_id")
    from src.storage.ingest import get_provenance as _m2_get_provenance  # local import avoids cycle

    rows = _m2_get_provenance(store, event_id)
    if not rows:
        return None
    # Most-recently-recorded provenance row (stable: highest id).
    row = max(rows, key=lambda r: r["id"])
    return ProvenanceMeta(
        event_id=row["event_id"],
        verification_status=row["verification_status"],
        verifier=row["verifier"],
        evidence_ref=row["evidence_ref"],
        recorded_at=row["recorded_at"],
    )


# ---------------------------------------------------------------------------
# Administrative deleted-inspection passthrough (read-only; Decision B)
# ---------------------------------------------------------------------------
def list_deleted(
    store: ReadonlyStore,
    scope_type: Optional[str] = None,
    scope_id: Optional[str] = None,
) -> List[str]:
    """Administrative route to deleted event_ids (normal queries exclude them). Read-only."""
    from src.storage.ingest import list_deleted as _m2_list_deleted  # local import avoids cycle

    try:
        return _m2_list_deleted(store, scope_type=scope_type, scope_id=scope_id)
    except Exception as exc:  # pragma: no cover - defensive
        raise QueryError(code="database_unavailable", message="list_deleted_failed") from exc


def get_tombstone(store: ReadonlyStore, tombstone_id: str) -> Optional[dict]:
    """Administrative route to a deletion tombstone record. Read-only."""
    if not isinstance(tombstone_id, str) or not tombstone_id:
        raise QueryError(code="invalid_query", message="non_string_tombstone_id")
    from src.storage.ingest import get_tombstone as _m2_get_tombstone  # local import avoids cycle

    try:
        return _m2_get_tombstone(store, tombstone_id)
    except Exception as exc:  # pragma: no cover - defensive
        raise QueryError(code="database_unavailable", message="get_tombstone_failed") from exc


def get_deletion_audit(
    store: ReadonlyStore,
    target_event_id: Optional[str] = None,
    tombstone_id: Optional[str] = None,
) -> List[dict]:
    """Administrative route to deletion-audit rows. Read-only."""
    from src.storage.ingest import get_deletion_audit as _m2_get_deletion_audit  # local import avoids cycle

    try:
        return _m2_get_deletion_audit(store, target_event_id=target_event_id, tombstone_id=tombstone_id)
    except Exception as exc:  # pragma: no cover - defensive
        raise QueryError(code="database_unavailable", message="get_deletion_audit_failed") from exc


# ---------------------------------------------------------------------------
# FTS composition: text candidates + verification/lifecycle filters (no ranking)
# ---------------------------------------------------------------------------
def search_filtered(
    store: ReadonlyStore,
    text: str,
    verification_status: Optional[str] = None,
    lifecycle_status: Optional[str] = None,
    limit: Optional[int] = None,
    cursor: Optional[str] = None,
) -> SearchResult:
    """FTS5 text search whose candidate set is further filtered by verification/lifecycle state.

    FTS only selects text candidates; verification/lifecycle filters are applied as exact
    structured predicates (AND). Deterministic ordering is unchanged (created_at ASC, event_id
    ASC). No ranking by verification/recency/confidence is introduced.
    """
    if verification_status is not None:
        validate_verification_status(verification_status)
    if lifecycle_status is not None:
        validate_lifecycle_status(lifecycle_status)
    effective_limit = query_mod._validate_limit(limit)
    # Cursor fingerprint binds text + verification + lifecycle so a cursor is not reusable across
    # differently-filtered searches.
    qf = cursor_mod.make_fingerprint(
        query_mod.QueryRequest(
            verification_status=verification_status, lifecycle_status=lifecycle_status
        ),
        text=text,
    )
    keyset: Optional[tuple] = None
    if cursor is not None:
        data = cursor_mod.validate_cursor_binding(cursor, qf, effective_limit)
        keyset = (data["sort"][0], data["sort"][1])

    extra_clauses: List[str] = []
    extra_params: List[object] = []
    if verification_status is not None:
        extra_clauses.append("zm_meta.verification_status = ?")
        extra_params.append(verification_status)
    if lifecycle_status is not None:
        # Normal path never returns deleted; reuse the same rule.
        if lifecycle_status == "deleted":
            raise QueryError(code="unsupported_filter", message="deleted_not_allowed_in_normal_query")
        extra_clauses.append("zm_meta.lifecycle_status = ?")
        extra_params.append(lifecycle_status)

    cols = ", ".join(f"zm_meta.{c}" for c in query_mod.ZM_META_COLUMNS)
    sql = (
        f"SELECT {cols}, snippet(zm_fts, 1, '[', ']', '...', 8) AS snippet "
        f"FROM zm_fts JOIN zm_meta ON zm_meta.event_id = zm_fts.event_id "
        f"WHERE zm_fts MATCH ? "
        + ("AND " + " AND ".join(extra_clauses) + " " if extra_clauses else "")
        + "AND zm_meta.event_id NOT IN (SELECT event_id FROM zm_lifecycle WHERE current_state='deleted') "
    )
    if keyset is not None:
        sql += "AND (zm_meta.created_at, zm_meta.event_id) > (?, ?) "
        extra_params.extend([keyset[0], keyset[1]])
    sql += "ORDER BY zm_meta.created_at ASC, zm_meta.event_id ASC LIMIT ?"
    params: List[object] = [text] + extra_params + [effective_limit]

    try:
        rows = store.conn.execute(sql, params).fetchall()
    except Exception as exc:  # pragma: no cover - defensive
        if "fts5" in str(exc).lower() or "fts" in str(exc).lower():
            return SearchResult(results=[], error="malformed_fts_expression")
        raise QueryError(code="database_unavailable", message="fts_query_failed") from exc

    from .search import _row_to_hit  # reuse the M3.3 hit builder

    hits = [_row_to_hit(r, r["snippet"]) for r in rows]
    next_cursor: Optional[str] = None
    if len(hits) >= effective_limit:
        last = hits[effective_limit - 1]
        next_cursor = cursor_mod.encode_cursor(qf, last.created_at, last.event_id, effective_limit)
    return SearchResult(results=hits, error=None, next_cursor=next_cursor)
