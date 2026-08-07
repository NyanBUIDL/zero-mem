"""M3.3 — deterministic, sanitized, TRUE READ-ONLY FTS5 search.

Reuses the verified M2.5 FTS substrate (``zm_fts`` over M1-sanitized content). It does
NOT create any new index, table, or migration. Capability is detected read-only by
inspecting the actual database (``sqlite_master`` for ``zm_fts``) — not the mutable module
global — so a stale global from another fixture cannot misreport availability. When ``zm_fts``
is absent the typed result carries ``error='fts_unavailable'`` (rather than overloading an
empty list). Malformed FTS expressions are intercepted (raw ``sqlite3.OperationalError`` is
caught; no raw text escapes) and surfaced as ``malformed_fts_expression``. Deleted records are
excluded via the same derived-state subquery used by the structured layer, so stale/synth FTS
rows can never surface a deleted event. Ordering is the deterministic ``(created_at ASC,
event_id ASC)`` key (no bm25/rowid/relevance). Pagination and cursor binding reuse the M3.2
machinery; the fingerprint also binds the normalized FTS text.
"""

from __future__ import annotations

import sqlite3
from typing import List, Optional

from .db import ReadonlyStore
from . import cursor as cursor_mod
from . import query as query_mod
from .models import (
    FTS_UNAVAILABLE,
    INVALID_LIMIT,
    MALFORMED_FTS_EXPRESSION,
    QueryError,
    QueryRequest,
    SearchHit,
    SearchResult,
)

# zm_fts is the verified M2.5 FTS table over SANITIZED content only.
from src.storage.ingest import ZM_META_COLUMNS  # noqa: E402


def _fts_substrate_present(store: ReadonlyStore) -> bool:
    """Read-only capability detection: does this database actually have zm_fts?"""
    try:
        row = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name='zm_fts'"
        ).fetchone()
    except sqlite3.OperationalError:
        return False
    return row is not None


def _row_to_hit(row, snippet: str) -> SearchHit:
    return SearchHit(
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
        snippet=snippet,
        content_source="fts",
    )


def search_text(
    store: ReadonlyStore,
    text: str,
    req: Optional[QueryRequest] = None,
    limit: Optional[int] = None,
    cursor: Optional[str] = None,
) -> SearchResult:
    """Deterministic FTS5 search over sanitized content. Read-only.

    - ``text`` is the raw FTS5 MATCH expression (parameterized; never concatenated into SQL).
    - ``req`` (optional) AND-composes structured M3.1 filters.
    - Returns a typed ``SearchResult``. ``error`` is set only for FTS-state conditions:
      ``fts_unavailable`` (zm_fts absent) or ``malformed_fts_expression`` (bad MATCH). Caller
      errors (invalid_limit / invalid_cursor / cursor_* / invalid_query) raise ``QueryError``.
    - Deleted records are excluded via derived state. Ordering is deterministic.
    - Supports M3.2 pagination: ``limit`` (default 50 / max 500) and a versioned, query-bound
      ``cursor`` (binds the normalized text + structured filters).
    """
    if not isinstance(text, str) or not text.strip():
        raise QueryError(code="invalid_query", message="empty_fts_text")
    if req is None:
        req = QueryRequest()
    if not isinstance(req, QueryRequest):
        raise QueryError(code="invalid_query", message="not_a_query_request")

    effective_limit = query_mod._validate_limit(limit)
    qf = cursor_mod.make_fingerprint(req, text=text)

    # Read-only capability detection against the actual database state.
    if not _fts_substrate_present(store):
        return SearchResult(results=[], error=FTS_UNAVAILABLE, next_cursor=None)

    keyset: Optional[tuple] = None
    if cursor is not None:
        data = cursor_mod.validate_cursor_binding(cursor, qf, effective_limit)
        keyset = (data["sort"][0], data["sort"][1])

    structured_where, structured_params = query_mod._build_where(req)
    cols = ", ".join(f"zm_meta.{c}" for c in ZM_META_COLUMNS)
    # Intersect the FTS candidate set (parameterized MATCH) with the structured-filtered,
    # deleted-excluded zm_meta rows. Snippet comes from zm_fts (sanitized content only).
    # NOTE: FTS5 snippet() markers/token-count must be literals (not bound params); they are
    # fixed constants here, so no caller-controlled value enters the SQL text.
    # All selected/compared columns are qualified with zm_meta. to avoid ambiguity with zm_fts.
    sql = (
        f"SELECT {cols}, snippet(zm_fts, 1, '[' , ']', '...', 8) AS snip "
        f"FROM zm_meta "
        f"JOIN zm_fts ON zm_fts.event_id = zm_meta.event_id "
        f"WHERE zm_fts MATCH ? "
        f"AND {structured_where} "
    )
    params: List[object] = [text]
    params.extend(structured_params)
    if keyset is not None:
        sql += " AND (zm_meta.created_at, zm_meta.event_id) > (?, ?)"
        params.extend([keyset[0], keyset[1]])
    sql += " ORDER BY zm_meta.created_at ASC, zm_meta.event_id ASC LIMIT ?"
    params.append(effective_limit)

    try:
        rows = store.conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        # Malformed FTS expression (or other FTS engine error). Sanitized, no raw text.
        return SearchResult(results=[], error=MALFORMED_FTS_EXPRESSION, next_cursor=None)
    except Exception:  # pragma: no cover - defensive
        raise QueryError(code="database_unavailable", message="fts_query_failed")

    hits = [_row_to_hit(r, r["snip"]) for r in rows]

    next_cursor: Optional[str] = None
    if len(hits) >= effective_limit:
        last = hits[effective_limit - 1]
        next_cursor = cursor_mod.encode_cursor(
            qf, last.created_at, last.event_id, effective_limit
        )

    return SearchResult(results=hits, error=None, next_cursor=next_cursor)
