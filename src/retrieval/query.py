"""M3.1 — structured read-only query execution over the verified M2 substrate.

Implements the smallest approved helpers: ``get_event``, ``get_trace``,
``query_events``, ``list_session``, ``list_project``, ``list_profile``.

All queries run against a ``ReadonlyStore`` (mode=ro + query_only). They build
parameterized ``SELECT`` statements only; they never write. Normal paths exclude
``lifecycle_status='deleted'`` (Decision B). Ordering is the deterministic
``(created_at ASC, event_id ASC)`` key. Unknown filter names raise a fixed
``unsupported_filter`` error (never silently ignored).
"""

from __future__ import annotations

from typing import List, Optional

from .db import ReadonlyStore
from .models import (
    INVALID_TIME_RANGE,
    QueryError,
    QueryRequest,
    QueryResult,
    EventView,
)

# Reuse the verified M2 column list and the exact-key trace helper (read-only).
from src.storage.ingest import ZM_META_COLUMNS, find_by_trace_id  # noqa: E402

# Columns eligible for exact-equality structured filters in M3.1.
_EQUAL_FILTERS = (
    "event_id",
    "trace_id",
    "event_type",
    "source",
    "session_id",
    "profile_id",
    "project_id",
    "task_id",
    "turn_id",
    "parent_trace_id",
    "lifecycle_status",
    "verification_status",
    "retention",
)

# Time-range (inclusive) filters, mapped to the backing column.
_RANGE_FILTERS = {
    "created_at_after": ("created_at", ">="),
    "created_at_before": ("created_at", "<="),
    "observed_at_after": ("observed_at", ">="),
    "observed_at_before": ("observed_at", "<="),
}

_DELETED_EXCLUSION = (
    "event_id NOT IN (SELECT event_id FROM zm_lifecycle WHERE current_state='deleted')"
)


def _validate_timestamp(value: str) -> None:
    # ISO-8601 basic sanity: must look like a timestamp; do not silently normalize.
    if not isinstance(value, str) or not value:
        raise QueryError(code=INVALID_TIME_RANGE, message="empty_timestamp")
    if " " in value or value[0].isdigit() is False:
        # Reject obviously malformed values; allow digits / 'T' / '-' / ':' / 'Z' / '.'.
        allowed = set("0123456789TZ.:+-")
        if not all(c in allowed for c in value):
            raise QueryError(code=INVALID_TIME_RANGE, message="malformed_timestamp")


def _build_where(req: QueryRequest):
    clauses: List[str] = [_DELETED_EXCLUSION]
    params: List[object] = []
    for field_name in _EQUAL_FILTERS:
        value = getattr(req, field_name, None)
        if value is None:
            continue
        if field_name == "lifecycle_status" and value == "deleted":
            # Normal path never returns deleted; caller must use M2 admin helpers.
            raise QueryError(code="unsupported_filter", message="deleted_not_allowed_in_normal_query")
        if not isinstance(value, str):
            raise QueryError(code="invalid_query", message=f"non_string_filter:{field_name}")
        column = field_name
        if column not in ZM_META_COLUMNS:
            raise QueryError(code="unsupported_filter", message=f"unknown_column:{column}")
        clauses.append(f"{column} = ?")
        params.append(value)
    for attr, (column, op) in _RANGE_FILTERS.items():
        value = getattr(req, attr, None)
        if value is None:
            continue
        _validate_timestamp(value)
        clauses.append(f"{column} {op} ?")
        params.append(value)
    return " AND ".join(clauses), params


def _row_to_view(row) -> EventView:
    return EventView(
        event_id=row["event_id"],
        trace_id=row["trace_id"],
        event_type=row["event_type"],
        source=row["source"],
        schema_version=int(row["schema_version"]),
        created_at=row["created_at"],
        observed_at=row["observed_at"],
        sequence=int(row["sequence"]),
        session_id=row["session_id"],
        profile_id=row["profile_id"],
        project_id=row["project_id"],
        task_id=row["task_id"],
        turn_id=row["turn_id"],
        parent_trace_id=row["parent_trace_id"],
        lifecycle_status=row["lifecycle_status"],
        verification_status=row["verification_status"],
        confidence=row["confidence"],
        sensitivity=row["sensitivity"],
        retention=row["retention"],
        content_hash=row["content_hash"],
        content_source="metadata_only",
    )


def _select(store: ReadonlyStore, req: QueryRequest) -> List[EventView]:
    where, params = _build_where(req)
    cols = ", ".join(ZM_META_COLUMNS)
    sql = (
        f"SELECT {cols} FROM zm_meta WHERE {where} "
        f"ORDER BY created_at ASC, event_id ASC"
    )
    try:
        rows = store.conn.execute(sql, params).fetchall()
    except Exception as exc:  # pragma: no cover - defensive
        raise QueryError(code="database_unavailable", message="query_failed") from exc
    return [_row_to_view(r) for r in rows]


def query_events(store: ReadonlyStore, req: QueryRequest) -> QueryResult:
    """Deterministic AND query over structured M3.1 filters. Read-only."""
    if not isinstance(req, QueryRequest):
        raise QueryError(code="invalid_query", message="not_a_query_request")
    items = _select(store, req)
    return QueryResult(items=items, query=req.to_dict(), total=len(items))


def get_event(store: ReadonlyStore, event_id: str) -> Optional[EventView]:
    """Exact-key single event. Returns None if missing or deleted."""
    if not isinstance(event_id, str) or not event_id:
        raise QueryError(code="invalid_query", message="non_string_event_id")
    rows = _select(store, QueryRequest(event_id=event_id))
    return rows[0] if rows else None


def get_trace(store: ReadonlyStore, trace_id: str) -> List[EventView]:
    """All non-deleted events of a trace (reuses M2 exact-key helper)."""
    if not isinstance(trace_id, str) or not trace_id:
        raise QueryError(code="invalid_query", message="non_string_trace_id")
    # M2's find_by_trace_id already excludes deleted and returns zm_meta rows.
    try:
        rows = find_by_trace_id(store, trace_id)
    except Exception as exc:  # pragma: no cover - defensive
        raise QueryError(code="database_unavailable", message="trace_query_failed") from exc
    return [_row_to_view(r) for r in rows]


def list_session(store: ReadonlyStore, session_id: str) -> List[EventView]:
    if not isinstance(session_id, str) or not session_id:
        raise QueryError(code="invalid_query", message="non_string_session_id")
    return _select(store, QueryRequest(session_id=session_id))


def list_project(store: ReadonlyStore, project_id: str) -> List[EventView]:
    if not isinstance(project_id, str) or not project_id:
        raise QueryError(code="invalid_query", message="non_string_project_id")
    return _select(store, QueryRequest(project_id=project_id))


def list_profile(store: ReadonlyStore, profile_id: str) -> List[EventView]:
    if not isinstance(profile_id, str) or not profile_id:
        raise QueryError(code="invalid_query", message="non_string_profile_id")
    return _select(store, QueryRequest(profile_id=profile_id))
