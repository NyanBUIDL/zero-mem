"""M3 — deterministic, read-only retrieval/query layer over the verified M2 substrate.

M3.1 + M3.2 + M3.3 + M3.4 scope: query contract, structured read-only filters, deterministic
versioned-query-bound pagination, TRUE READ-ONLY FTS5 search, and relation/scope/artifact read
queries. No ranking/semantic/M3.5+/M4.

This package is strictly read-only:
- it opens SQLite through an explicitly read-only connection (`db.open_readonly`),
- it never calls migrations / ensure_schema / downgrade_to,
- it never reuses the M2 read-write `SQLiteStore`,
- it never writes to JSONL or derived SQLite state.

See `.hermes/plans/2026-08-07_000002-m3-read-only-retrieval-query.md`.
"""

from __future__ import annotations

from .db import ReadonlyStore, open_readonly
from .models import (
    CURSOR_LIMIT_MISMATCH,
    CURSOR_QUERY_MISMATCH,
    EventView,
    FTS_UNAVAILABLE,
    INVALID_CURSOR,
    INVALID_DIRECTION,
    INVALID_LIMIT,
    INVALID_RELATION_TYPE,
    INVALID_VERIFICATION_STATUS,
    INVALID_LIFECYCLE_STATUS,
    MALFORMED_FTS_EXPRESSION,
    QueryError,
    QueryRequest,
    QueryResult,
    SearchHit,
    SearchResult,
    RelatedView,
    RelatedResult,
    ArtifactRefView,
    ArtifactResult,
    ProvenanceMeta,
)
from .cursor import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    CURSOR_VERSION,
    decode_cursor,
    encode_cursor,
    make_fingerprint,
    make_relation_fingerprint,
    make_artifact_fingerprint,
    validate_cursor_binding,
)
from .query import (
    get_event,
    get_trace,
    list_profile,
    list_project,
    list_session,
    query_events,
)
from .search import search_text
from .relations import (
    get_related,
    get_parent,
    get_children,
    get_artifacts,
    list_knowledge_space,
)
from .verification import (
    get_provenance,
    list_deleted,
    get_tombstone,
    get_deletion_audit,
    search_filtered,
    validate_verification_status,
    validate_lifecycle_status,
)

__all__ = [
    "ReadonlyStore",
    "open_readonly",
    "EventView",
    "QueryError",
    "QueryRequest",
    "QueryResult",
    "SearchHit",
    "SearchResult",
    "RelatedView",
    "RelatedResult",
    "ArtifactRefView",
    "ArtifactResult",
    "CURSOR_VERSION",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "FTS_UNAVAILABLE",
    "MALFORMED_FTS_EXPRESSION",
    "INVALID_CURSOR",
    "INVALID_LIMIT",
    "INVALID_DIRECTION",
    "INVALID_RELATION_TYPE",
    "INVALID_VERIFICATION_STATUS",
    "INVALID_LIFECYCLE_STATUS",
    "CURSOR_QUERY_MISMATCH",
    "CURSOR_LIMIT_MISMATCH",
    "ProvenanceMeta",
    "make_fingerprint",
    "make_relation_fingerprint",
    "make_artifact_fingerprint",
    "encode_cursor",
    "decode_cursor",
    "validate_cursor_binding",
    "get_event",
    "get_trace",
    "query_events",
    "search_text",
    "list_session",
    "list_project",
    "list_profile",
    "get_related",
    "get_parent",
    "get_children",
    "get_artifacts",
    "list_knowledge_space",
    "get_provenance",
    "list_deleted",
    "get_tombstone",
    "get_deletion_audit",
    "search_filtered",
    "validate_verification_status",
    "validate_lifecycle_status",
]
