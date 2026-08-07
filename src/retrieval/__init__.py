"""M3 — deterministic, read-only retrieval/query layer over the verified M2 substrate.

M3.1 scope: query contract + structured read-only filters only.

This package is strictly read-only:
- it opens SQLite through an explicitly read-only connection (`db.open_readonly`),
- it never calls migrations / ensure_schema / downgrade_to,
- it never reuses the M2 read-write `SQLiteStore`,
- it never writes to JSONL or derived SQLite state.

See `.hermes/plans/2026-08-07_000002-m3-read-only-retrieval-query.md`.
"""

from __future__ import annotations

from .db import ReadonlyStore, open_readonly
from .models import EventView, QueryError, QueryRequest, QueryResult
from .query import get_event, get_trace, list_profile, list_project, list_session, query_events

__all__ = [
    "ReadonlyStore",
    "open_readonly",
    "EventView",
    "QueryError",
    "QueryRequest",
    "QueryResult",
    "get_event",
    "get_trace",
    "query_events",
    "list_session",
    "list_project",
    "list_profile",
]
