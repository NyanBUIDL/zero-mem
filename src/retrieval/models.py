"""M3.1 — query contract models (typed, read-only).

Defines the approved request/result/error contracts. M3.1 is metadata-only: result
views carry the approved ``zm_meta`` columns plus a ``content_source`` marker
(``metadata_only``). No raw payloads, secrets, or full JSONL text are returned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# Fixed sanitized error codes (no raw SQLite / exception text escapes to callers).
INVALID_QUERY = "invalid_query"
UNSUPPORTED_FILTER = "unsupported_filter"
INVALID_TIME_RANGE = "invalid_time_range"
INVALID_LIMIT = "invalid_limit"
INVALID_CURSOR = "invalid_cursor"
CURSOR_QUERY_MISMATCH = "cursor_query_mismatch"
CURSOR_LIMIT_MISMATCH = "cursor_limit_mismatch"
FTS_UNAVAILABLE = "fts_unavailable"
MALFORMED_FTS_EXPRESSION = "malformed_fts_expression"
DATABASE_UNAVAILABLE = "database_unavailable"
SCHEMA_MISMATCH = "schema_mismatch"


class QueryError(Exception):
    """Fixed-code sanitized query error. Never carries raw SQLite/exception text."""

    def __init__(self, code: str, message: Optional[str] = None) -> None:
        self.code = code
        self.message = message
        super().__init__(code if message is None else f"{code}: {message}")


@dataclass
class QueryRequest:
    """Deterministic AND query over verified M2 ``zm_meta`` columns.

    Every non-null field is AND-ed. None means "not filtered on this field".
    Time ranges are inclusive. NULL identities remain NULL (never invented).
    """

    event_id: Optional[str] = None
    trace_id: Optional[str] = None
    event_type: Optional[str] = None
    source: Optional[str] = None
    session_id: Optional[str] = None
    profile_id: Optional[str] = None
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    turn_id: Optional[str] = None
    parent_trace_id: Optional[str] = None
    lifecycle_status: Optional[str] = None
    verification_status: Optional[str] = None
    retention: Optional[str] = None
    created_at_after: Optional[str] = None
    created_at_before: Optional[str] = None
    observed_at_after: Optional[str] = None
    observed_at_before: Optional[str] = None

    # Fields explicitly NOT part of M3.1 (reserved for later increments):
    # relation traversal (M3.4), FTS text (M3.3), ranking (later), content
    # resolution from JSONL (later). M3.1 is metadata-only.

    def to_dict(self) -> Dict[str, Any]:
        """Canonical, safe, sorted serialization (no secrets/SQL/paths)."""
        return {k: v for k, v in sorted(self.__dict__.items()) if v is not None}


@dataclass
class EventView:
    """Approved metadata fields for one stored event. Metadata-only in M3.1."""

    event_id: str
    trace_id: str
    event_type: str
    source: str
    schema_version: int
    created_at: str
    observed_at: str
    sequence: int
    session_id: Optional[str]
    profile_id: Optional[str]
    project_id: Optional[str]
    task_id: Optional[str]
    turn_id: Optional[str]
    parent_trace_id: Optional[str]
    lifecycle_status: str
    verification_status: str
    confidence: str
    sensitivity: str
    retention: str
    content_hash: str
    content_source: str = "metadata_only"


@dataclass
class QueryResult:
    """Typed result. ``items`` is deterministically ordered; ``query`` is echoed.

    M3.2 adds ``next_cursor`` (None at end-of-results). ``total`` is the page length
    (M3.2 does not force a full COUNT scan unless ``include_total`` is added later).
    """

    items: List[EventView] = field(default_factory=list)
    query: Dict[str, Any] = field(default_factory=dict)
    total: int = 0
    next_cursor: Optional[str] = None


@dataclass
class SearchHit:
    """One FTS hit. Deterministic metadata + a sanitized snippet (content_source='fts').

    No raw FTS row, raw payload, secret-bearing text, or filesystem path is exposed.
    """

    event_id: str
    trace_id: str
    event_type: str
    source: str
    schema_version: int
    created_at: str
    observed_at: str
    sequence: int
    session_id: Optional[str]
    profile_id: Optional[str]
    project_id: Optional[str]
    task_id: Optional[str]
    turn_id: Optional[str]
    parent_trace_id: Optional[str]
    lifecycle_status: str
    verification_status: str
    confidence: str
    sensitivity: str
    retention: str
    content_hash: str
    snippet: str
    content_source: str = "fts"


@dataclass
class SearchResult:
    """Typed FTS result. ``error`` distinguishes zero-results from FTS-state errors.

    | situation                | results | error                  |
    |--------------------------|---------|------------------------|
    | success (>=1 hit)        | hits    | None                   |
    | success, zero hits       | []      | None                   |
    | FTS5 unavailable         | []      | "fts_unavailable"      |
    | malformed FTS expression | []      | "malformed_fts_expression" |
    """

    results: List[SearchHit] = field(default_factory=list)
    error: Optional[str] = None
    next_cursor: Optional[str] = None
