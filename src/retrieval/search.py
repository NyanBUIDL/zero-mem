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
from typing import Any, List, Optional

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


# In the default unicode61 tokenizer an unquoted ``-`` is ALWAYS parsed by FTS5 as a
# column-filter operator (``walk-forward`` -> ``no such column: forward``), because FTS5
# negation is the ``NOT`` keyword, not ``-``. The index itself splits ``walk-forward``
# into ``walk`` + ``forward``, so replacing every ``-`` with whitespace re-tokenizes the
# query exactly like the index and restores the hit. Other legitimate FTS5 syntax
# (quotes / OR / AND / NOT / grouping) contains no ``-`` and is left untouched.


def _normalize_fts_query(text: str) -> str:
    """Deterministic FTS5 MATCH-text normalization. No schema, no migration, no LLM.

    Collapses whitespace and replaces hyphens with a space so a compound query term
    matches the way the index tokenized it. Well-formed operator queries without a
    hyphen are returned verbatim (modulo whitespace collapse).
    """
    return " ".join(text.split()).replace("-", " ")


def _quote_fts_term(term: str) -> str:
    """Safely double-quote a single term for an FTS5 MATCH expression (V130-01).

    Embedded double quotes are doubled per the FTS5 phrase-quoting rule, so caller
    text can never inject FTS operators (OR/AND/NOT/NEAR/column filters) — the whole
    term always matches as a literal token sequence.
    """
    return '"' + term.replace('"', '""') + '"'


def _term_list(normalized_text: str) -> List[str]:
    """Whitespace-split terms of the normalized query, non-empty only."""
    return [t for t in normalized_text.split() if t]


def _run_match(store: ReadonlyStore, match_expr: str,
               structured_where: str, structured_params: List[object],
               keyset: Optional[tuple], effective_limit: int):
    """One parameterized FTS candidate fetch. Returns raw rows (may be empty).

    Raises sqlite3.OperationalError on malformed MATCH (caller decides handling).
    """
    cols = ", ".join(f"zm_meta.{c}" for c in ZM_META_COLUMNS)
    sql = (
        f"SELECT {cols}, snippet(zm_fts, 1, '[' , ']', '...', 8) AS snip "
        f"FROM zm_meta "
        f"JOIN zm_fts ON zm_fts.event_id = zm_meta.event_id "
        f"WHERE zm_fts MATCH ? "
        f"AND {structured_where} "
    )
    params: List[object] = [match_expr]
    params.extend(structured_params)
    if keyset is not None:
        sql += " AND (zm_meta.created_at, zm_meta.event_id) > (?, ?)"
        params.extend([keyset[0], keyset[1]])
    sql += " ORDER BY zm_meta.created_at ASC, zm_meta.event_id ASC LIMIT ?"
    params.append(effective_limit)
    return store.conn.execute(sql, params).fetchall()


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
        knowledge_space_id=row["knowledge_space_id"],
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
    candidate_where: Optional[str] = None,
    candidate_params: Optional[List[Any]] = None,
    fingerprint_extra: str = "",
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

    # Normalize the FTS text before the cursor fingerprint and MATCH so compound
    # hyphenated terms (``walk-forward``) re-tokenize the same way the unicode61 index
    # did, instead of being parsed as a column operator and collapsing into
    # ``malformed_fts_expression``. Deterministic; a no-op for well-formed queries.
    text = _normalize_fts_query(text)

    effective_limit = query_mod._validate_limit(limit)
    # V130-01: the cursor is bound to the MATCH strategy that produced it. Both
    # mode-specific fingerprints are derived up front; validation uses the one for
    # the pass whose rows are returned.
    fingerprint_text = text + "\x1f" + fingerprint_extra
    qf_and = cursor_mod.make_fingerprint(req, text=fingerprint_text, match_mode="and")
    qf_or = cursor_mod.make_fingerprint(req, text=fingerprint_text, match_mode="or_fallback")

    # Read-only capability detection against the actual database state.
    if not _fts_substrate_present(store):
        return SearchResult(results=[], error=FTS_UNAVAILABLE, next_cursor=None)

    keyset: Optional[tuple] = None
    if cursor is not None:
        try:
            data = cursor_mod.validate_cursor_binding(cursor, qf_and, effective_limit)
            keyset = (data["sort"][0], data["sort"][1])
        except QueryError as exc:
            # Only a MODE binding mismatch falls through to the OR fingerprint;
            # limit mismatches / structural errors must surface unchanged.
            if exc.code != cursor_mod.CURSOR_QUERY_MISMATCH:
                raise
            # A cursor minted by an OR-fallback pass binds to qf_or instead.
            data = cursor_mod.validate_cursor_binding(cursor, qf_or, effective_limit)
            keyset = (data["sort"][0], data["sort"][1])

    structured_where, structured_params = query_mod._build_where(req)
    if candidate_where:
        structured_where = f"({structured_where}) AND ({candidate_where})"
        structured_params = structured_params + list(candidate_params or [])
    try:
        rows = _run_match(store, text, structured_where,
                          structured_params, keyset, effective_limit + 1)
        match_mode = "and"
        # V130-01 precision-guarded OR fallback: only when the implicit-AND pass
        # returned zero rows AND the query has >= 2 terms. Terms are FTS5-quoted so
        # caller text can never introduce operators; the expression stays a bound
        # parameter. Ordering/filters/pagination are identical in both modes.
        if not rows:
            terms = _term_list(text)
            if len(terms) >= 2:
                or_expr = " OR ".join(_quote_fts_term(t) for t in terms)
                # A paginated OR pass would need its own fingerprint binding (the
                # AND-mode cursor's keyset belongs to the same logical query, so
                # reuse is safe: identical sort key and filter set).
                rows = _run_match(store, or_expr, structured_where,
                                  structured_params, keyset, effective_limit + 1)
                match_mode = "or_fallback"
    except sqlite3.OperationalError:
        # Malformed FTS expression (or other FTS engine error). Sanitized, no raw text.
        return SearchResult(results=[], error=MALFORMED_FTS_EXPRESSION, next_cursor=None)
    except Exception:  # pragma: no cover - defensive
        raise QueryError(code="database_unavailable", message="fts_query_failed")

    hits = [_row_to_hit(r, r["snip"]) for r in rows]

    next_cursor: Optional[str] = None
    if len(hits) >= effective_limit:
        last = hits[effective_limit - 1]
        # Encode with the fingerprint of the mode that actually produced the rows.
        qf = qf_or if match_mode == "or_fallback" else qf_and
        next_cursor = cursor_mod.encode_cursor(
            qf, last.created_at, last.event_id, effective_limit
        )

    return SearchResult(results=hits[:effective_limit], error=None, next_cursor=next_cursor,
                        match_mode=match_mode)
