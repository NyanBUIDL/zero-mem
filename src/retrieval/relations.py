"""M3.4 — deterministic, sanitized, TRUE READ-ONLY relation / scope / artifact queries.

Reads ONLY the verified M2 derived projections (``zm_relations``, ``zm_scopes``, ``zm_artifacts``,
and ``zm_meta`` for target metadata). It does NOT create, infer, or rewrite relations; does NOT
implement authorization; does NOT traverse graphs beyond direct stored edges (depth=1). All queries
are SELECT-only against a ``ReadonlyStore`` (mode=ro + query_only). Deleted targets are excluded via
the same derived-state subquery used by the structured layer. Ordering of event results is the
deterministic ``(created_at ASC, event_id ASC)`` key. Pagination + cursor binding reuse the M3.2
machinery; the relation cursor fingerprint binds ``event_id`` + ``direction`` + ``relation_type``.

Notes on scope semantics (schema-truthful, no inference):
- project / profile scope -> ``zm_meta.project_id`` / ``profile_id`` (served by M3.1 list_project /
  list_profile; reused here unchanged).
- session scope -> ``zm_meta.session_id`` (M3.1 list_session).
- knowledge_space scope -> only an observed ``zm_scopes`` row (scope_type='knowledge_space'); there is
  NO event-level linkage column in the verified M2 schema, so ``list_knowledge_space`` returns ``[]``
  (no global fallback, no inferred membership).
- artifact references -> ``zm_artifacts`` metadata only; ``stored_path`` is never exposed (safe
  ``artifact:<id>`` reference instead).
"""

from __future__ import annotations

from typing import List, Optional

from .db import ReadonlyStore
from . import cursor as cursor_mod
from . import query as query_mod
from .models import (
    INVALID_DIRECTION,
    INVALID_RELATION_TYPE,
    QueryError,
    RelatedResult,
    RelatedView,
    ArtifactResult,
    ArtifactRefView,
    EventView,
)

from src.storage.ingest import ZM_META_COLUMNS  # noqa: E402

_DELETED_EXCLUSION = (
    "m.event_id NOT IN (SELECT event_id FROM zm_lifecycle WHERE current_state='deleted')"
)
_VALID_DIRECTIONS = ("outgoing", "incoming", "both")


def _row_to_event_view(row) -> EventView:
    return query_mod._row_to_view(row)


def get_related(
    store: ReadonlyStore,
    event_id: str,
    relation_type: Optional[str] = None,
    direction: Optional[str] = None,
    limit: Optional[int] = None,
    cursor: Optional[str] = None,
) -> RelatedResult:
    """Explicit stored relations for ``event_id`` (depth=1), both/out/in directions.

    - ``direction``: 'outgoing' (from_event_id=event_id), 'incoming' (to_event_id=event_id),
      or None/'both'. Invalid values raise ``invalid_direction``.
    - ``relation_type``: optional exact filter (e.g. 'child_of'); empty/non-string raises
      ``invalid_relation_type``. Unknown types simply yield no rows (no error).
    - Deleted targets are excluded. Ordering is deterministic. Pagination + cursor reuse M3.2.
    - A cursor from one relation query is rejected for another (``cursor_query_mismatch`` /
      ``cursor_limit_mismatch``); malformed -> ``invalid_cursor``.
    """
    if not isinstance(event_id, str) or not event_id:
        raise QueryError(code="invalid_query", message="non_string_event_id")
    direction = direction or "both"
    if direction not in _VALID_DIRECTIONS:
        raise QueryError(code=INVALID_DIRECTION, message=direction)
    if relation_type is not None:
        if not isinstance(relation_type, str) or not relation_type:
            raise QueryError(code=INVALID_RELATION_TYPE, message="empty_relation_type")
    effective_limit = query_mod._validate_limit(limit)
    qf = cursor_mod.make_relation_fingerprint(event_id, direction, relation_type)

    keyset: Optional[tuple] = None
    if cursor is not None:
        data = cursor_mod.validate_cursor_binding(cursor, qf, effective_limit)
        keyset = (data["sort"][0], data["sort"][1])

    if direction == "outgoing":
        dir_pred = "r.from_event_id = ?"
        dir_params = [event_id]
        target_expr = "r.to_event_id"
    elif direction == "incoming":
        dir_pred = "r.to_event_id = ?"
        dir_params = [event_id]
        target_expr = "r.from_event_id"
    else:  # both
        dir_pred = "(r.from_event_id = ? OR r.to_event_id = ?)"
        dir_params = [event_id, event_id]
        target_expr = ("CASE WHEN r.from_event_id = ? THEN r.to_event_id ELSE r.from_event_id END")

    type_pred = ""
    type_params: List[object] = []
    if relation_type is not None:
        type_pred = " AND r.relation = ?"
        type_params = [relation_type]

    cols = ", ".join(f"m.{c}" for c in ZM_META_COLUMNS)
    sql = (
        f"SELECT r.relation AS relation, r.verifier AS verifier, r.evidence_ref AS evidence_ref, "
        f"r.created_at AS edge_created_at, {target_expr} AS target_event_id, "
        f"CASE WHEN r.from_event_id = ? THEN 'outgoing' ELSE 'incoming' END AS direction, "
        f"{cols} "
        f"FROM zm_relations r JOIN zm_meta m ON m.event_id = {target_expr} "
        f"WHERE {dir_pred}{type_pred} AND {_DELETED_EXCLUSION} "
        f"ORDER BY m.created_at ASC, m.event_id ASC LIMIT ?"
    )
    # Placeholder order in the SQL text: [target_expr CASE ?] (only 'both') -> [SELECT direction CASE ?]
    # -> [dir_pred ?...] -> [type ?] -> [keyset] -> [limit].
    params: List[object] = []
    if direction == "both":
        params.append(event_id)  # SELECT target_expr CASE
        params.append(event_id)  # JOIN target_expr CASE (target_expr is referenced twice)
    params.append(event_id)      # SELECT direction CASE
    params.extend(dir_params)     # dir_pred placeholders (already contain event_id(s))
    params.extend(type_params)    # relation_type
    if keyset is not None:
        # Inject the keyset predicate into the WHERE clause (before ORDER BY).
        sql = sql.replace("ORDER BY", "AND (m.created_at, m.event_id) > (?, ?) ORDER BY")
        params.extend([keyset[0], keyset[1]])
    params.append(effective_limit)

    try:
        rows = store.conn.execute(sql, params).fetchall()
    except Exception as exc:  # pragma: no cover - defensive
        raise QueryError(code="database_unavailable", message="relation_query_failed") from exc

    items: List[RelatedView] = []
    for r in rows:
        if r["direction"] == "outgoing":
            from_eid, to_eid = event_id, r["target_event_id"]
        else:
            from_eid, to_eid = r["target_event_id"], event_id
        items.append(RelatedView(
            relation=r["relation"],
            direction=r["direction"],
            from_event_id=from_eid,
            to_event_id=to_eid,
            verifier=r["verifier"],
            evidence_ref=r["evidence_ref"],
            created_at=r["edge_created_at"],
            target_event_id=r["target_event_id"],
            target=_row_to_event_view(r),
        ))

    next_cursor: Optional[str] = None
    if len(items) >= effective_limit:
        last = items[effective_limit - 1]
        next_cursor = cursor_mod.encode_cursor(
            qf, last.target.created_at, last.target.event_id, effective_limit
        )
    return RelatedResult(
        items=items,
        query={"event_id": event_id, "direction": direction, "relation_type": relation_type},
        total=len(items),
        next_cursor=next_cursor,
    )


def get_parent(store: ReadonlyStore, event_id: str) -> Optional[RelatedView]:
    """Return the single explicit parent (outgoing 'child_of' edge), or None.

    Edge shape: from=child, to=parent, relation='child_of'. So the parent is the target of the
    outgoing 'child_of' edge. No inference; returns None if no such edge exists.
    """
    res = get_related(store, event_id, relation_type="child_of", direction="outgoing", limit=1)
    return res.items[0] if res.items else None


def get_children(
    store: ReadonlyStore,
    event_id: str,
    limit: Optional[int] = None,
    cursor: Optional[str] = None,
) -> RelatedResult:
    """Return explicit children (incoming 'child_of' edges). Bounded (depth=1)."""
    return get_related(store, event_id, relation_type="child_of", direction="incoming",
                        limit=limit, cursor=cursor)


def get_artifacts(
    store: ReadonlyStore,
    event_id: str,
    limit: Optional[int] = None,
    cursor: Optional[str] = None,
) -> ArtifactResult:
    """Return artifact-reference metadata for events whose origin is ``event_id``.

    Read-only; metadata only. ``stored_path`` (internal filesystem pointer) is NOT exposed;
    ``reference`` carries the safe ``artifact:<artifact_id>`` form. No artifact content is read.
    """
    if not isinstance(event_id, str) or not event_id:
        raise QueryError(code="invalid_query", message="non_string_event_id")
    effective_limit = query_mod._validate_limit(limit)
    qf = cursor_mod.make_artifact_fingerprint(event_id)

    keyset: Optional[tuple] = None
    if cursor is not None:
        data = cursor_mod.validate_cursor_binding(cursor, qf, effective_limit)
        keyset = (data["sort"][0], data["sort"][1])

    sql = (
        "SELECT artifact_id, content_hash, kind, retention, origin_event_id, created_at "
        "FROM zm_artifacts WHERE origin_event_id = ? "
    )
    params: List[object] = [event_id]
    if keyset is not None:
        sql += " AND (created_at, artifact_id) > (?, ?)"
        params.extend([keyset[0], keyset[1]])
    sql += " ORDER BY created_at ASC, artifact_id ASC LIMIT ?"
    params.append(effective_limit)

    try:
        rows = store.conn.execute(sql, params).fetchall()
    except Exception as exc:  # pragma: no cover - defensive
        raise QueryError(code="database_unavailable", message="artifact_query_failed") from exc

    items = [
        ArtifactRefView(
            artifact_id=r["artifact_id"],
            content_hash=r["content_hash"],
            kind=r["kind"],
            retention=r["retention"],
            origin_event_id=r["origin_event_id"],
            reference=f"artifact:{r['artifact_id']}",
            created_at=r["created_at"],
        )
        for r in rows
    ]
    next_cursor: Optional[str] = None
    if len(items) >= effective_limit:
        last = items[effective_limit - 1]
        next_cursor = cursor_mod.encode_cursor(
            qf, last.created_at, last.artifact_id, effective_limit
        )
    return ArtifactResult(
        items=items,
        query={"origin_event_id": event_id},
        total=len(items),
        next_cursor=next_cursor,
    )


def list_knowledge_space(
    store: ReadonlyStore,
    knowledge_space_id: str,
    limit: Optional[int] = None,
    cursor: Optional[str] = None,
) -> "QueryResult":
    """Return events in a knowledge space.

    Schema-truthful: in the verified M2 schema, ``knowledge_space_id`` is projected only into
    ``zm_scopes`` (scope_type='knowledge_space') with NO event-level linkage column. There is
    therefore no event set to return, and M3.4 must not infer membership from project/profile/
    file/relation/name. The correct, safe result is an empty page (``error=None``), consistent
    with the no-global-fallback rule. Callers that need event membership must supply an explicit
    project/profile/session scope via the existing structured queries.
    """
    if not isinstance(knowledge_space_id, str) or not knowledge_space_id:
        raise QueryError(code="invalid_query", message="non_string_knowledge_space_id")
    query_mod._validate_limit(limit)  # validate limit shape even when result is empty
    from .models import QueryResult  # local import to avoid any cycle confusion
    return QueryResult(items=[], query={"knowledge_space_id": knowledge_space_id}, total=0,
                        next_cursor=None)
