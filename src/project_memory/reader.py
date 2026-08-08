"""M4.6 — TRUE READ-ONLY project-memory query APIs + M3 composition.

Reads the verified M4 v7 derived tables (zm_project_charters, zm_requirements,
zm_decisions, zm_project_state, zm_verifications, zm_project_artifacts) through
the M3 ``ReadonlyStore`` (``file:...?mode=ro`` + ``PRAGMA query_only=ON``). It
never opens a writer/projector connection, never invokes a projector, never runs
a migration, and never mutates store/JSONL state.

Design constraints (from the approved M4 plan):
- Active selection is by explicit stored ``lifecycle_status='active'`` — NEVER by
  MAX(created_at) / latest row / largest version alone.
- Deleted rows excluded from normal reads; historical non-deleted rows retrievable
  only when explicitly requested (include_history / lifecycle_status filter).
- Conflicts preserved (no winner, no timestamp truth, no merge).
- Supersession is read from stored supersedes/replaced_by only (never inferred).
- Domain ``state`` kept separate from ``lifecycle_status`` in result views.
- Pagination: versioned, query-bound, limit-bound keyset cursor (M3 cursor module).
- Provenance: only stored safe fields exposed; missing provenance not inferred.
- Source-event composition: ``include_source_event=True`` resolves via the M3
  read-only path; missing source event -> None (never fabricated).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from src.retrieval.db import ReadonlyStore, open_readonly, _readonly_conn_is_query_only
from src.retrieval.models import QueryError
from src.retrieval import cursor as _cursor
from src.retrieval.query import get_event as _m3_get_event

# Reuse M3 sanitized error codes (no new parallel framework).
from src.retrieval.models import (  # noqa: F401
    INVALID_QUERY,
    UNSUPPORTED_FILTER,
    INVALID_LIMIT,
    INVALID_CURSOR,
    CURSOR_QUERY_MISMATCH,
    CURSOR_LIMIT_MISMATCH,
    INVALID_VERIFICATION_STATUS,
    INVALID_LIFECYCLE_STATUS,
    DATABASE_UNAVAILABLE,
    SCHEMA_MISMATCH,
)

# M4-specific codes required by the directive but absent from M3 models.
INVALID_PROJECT_ID = "invalid_project_id"
INVALID_SUBJECT_TYPE = "invalid_subject_type"

_DELETED = "deleted"


# ---------------------------------------------------------------------------
# Result models (explicit, distinct per domain; metadata-only; provenance safe)
# ---------------------------------------------------------------------------


@dataclass
class CharterView:
    charter_id: str
    project_id: str
    version: int
    name: Optional[str]
    goal: Optional[str]
    scope: Optional[str]
    non_goals: Optional[str]
    constraints: Optional[str]
    architecture_principles: Optional[str]
    success_criteria: Optional[str]
    lifecycle_status: str
    state: Optional[str]
    source_event_id: Optional[str]
    trace_id: Optional[str]
    session_id: Optional[str]
    profile_id: Optional[str]
    created_at: str
    updated_at: Optional[str]
    supersedes: Optional[str]
    verification_ref: Optional[str]
    source_event: Optional[object] = None  # M3 EventView when include_source_event=True


@dataclass
class RequirementView:
    requirement_id: str
    project_id: str
    statement: Optional[str]
    lifecycle_status: str
    state: Optional[str]
    verification_status: str
    supersedes: Optional[str]
    replaced_by: Optional[str]
    linked_decision_ids: Optional[str]
    linked_artifact_ids: Optional[str]
    linked_verification_ids: Optional[str]
    source_event_id: Optional[str]
    trace_id: Optional[str]
    session_id: Optional[str]
    profile_id: Optional[str]
    created_at: str
    source_event: Optional[object] = None


@dataclass
class DecisionView:
    decision_id: str
    project_id: str
    scope: Optional[str]
    decision_key: Optional[str]
    statement: Optional[str]
    rationale_ref: Optional[str]
    alternatives: Optional[str]
    lifecycle_status: str
    state: Optional[str]
    supersedes_id: Optional[str]
    replaced_by: Optional[str]
    effective_at: Optional[str]
    linked_requirement_ids: Optional[str]
    linked_artifact_ids: Optional[str]
    linked_verification_ids: Optional[str]
    source_event_id: Optional[str]
    trace_id: Optional[str]
    session_id: Optional[str]
    profile_id: Optional[str]
    source_event: Optional[object] = None


@dataclass
class ProjectStateView:
    id: int
    project_id: str
    scope: Optional[str]
    state_key: Optional[str]
    state_value: Optional[str]
    state_ref: Optional[str]
    lifecycle_status: str
    verification_status: str
    effective_at: Optional[str]
    supersedes: Optional[str]
    source_event_id: Optional[str]
    trace_id: Optional[str]
    session_id: Optional[str]
    profile_id: Optional[str]


@dataclass
class VerificationView:
    verification_id: str
    subject_type: Optional[str]
    subject_id: Optional[str]
    project_id: str
    method: Optional[str]
    command_ref: Optional[str]
    observed_result: Optional[str]
    tested_commit: Optional[str]
    source_event_id: Optional[str]
    timestamp: Optional[str]
    verification_status: str
    artifact_references: Optional[str]


@dataclass
class ProjectArtifactView:
    artifact_id: str
    project_id: str
    artifact_type: Optional[str]
    version: Optional[str]
    safe_reference: Optional[str]
    source_event_id: Optional[str]
    created_at: str
    verification_status: str
    linked_requirement_ids: Optional[str]
    linked_decision_ids: Optional[str]
    linked_state_keys: Optional[str]
    # Joined M2 safe metadata (no stored_path, no content).
    kind: Optional[str] = None
    content_hash: Optional[str] = None
    retention: Optional[str] = None


@dataclass
class ProjectMemoryResult:
    items: List[object] = None  # type: ignore[assignment]
    query: dict = None  # type: ignore[assignment]
    total: int = 0
    next_cursor: Optional[str] = None
    error: Optional[str] = None  # None on success; sanitized code on query-state error

    def __post_init__(self) -> None:
        if self.items is None:
            self.items = []
        if self.query is None:
            self.query = {}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_project_id(project_id: str) -> None:
    if not isinstance(project_id, str) or not project_id:
        raise QueryError(code=INVALID_PROJECT_ID, message="empty_project_id")


def _validate_lifecycle(value: Optional[str]) -> None:
    if value is None:
        return
    allowed = {
        "raw", "observed", "candidate", "confirmed", "active",
        "superseded", "conflicted", "archived", "deleted",
    }
    if value not in allowed:
        raise QueryError(code=INVALID_LIFECYCLE_STATUS, message=f"unknown:{value}")


def _validate_verification_status(value: Optional[str]) -> None:
    if value is None:
        return
    allowed = {
        "none", "direct_tool_output", "user_confirmation",
        "deterministic_verification", "approval",
    }
    if value not in allowed:
        raise QueryError(code=INVALID_VERIFICATION_STATUS, message=f"unknown:{value}")


def _validate_subject_type(value: Optional[str]) -> None:
    if value is None:
        return
    allowed = {
        "requirement", "decision", "state", "artifact",
        "task", "implementation", "milestone",
    }
    if value not in allowed:
        raise QueryError(code=INVALID_SUBJECT_TYPE, message=f"unknown:{value}")


def _validate_limit_local(limit: Optional[int]) -> int:
    if limit is None:
        return _cursor.DEFAULT_LIMIT
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise QueryError(code=INVALID_LIMIT, message="non_integer_limit")
    if limit <= 0:
        raise QueryError(code=INVALID_LIMIT, message="non_positive_limit")
    if limit > _cursor.MAX_LIMIT:
        raise QueryError(code=INVALID_LIMIT, message="above_max_limit")
    return limit


def _resolve_source(store: ReadonlyStore, source_event_id: Optional[str]):
    if not source_event_id:
        return None
    try:
        return _m3_get_event(store, source_event_id)
    except QueryError:
        return None


def _key_clause(sort_cols: List[str], keyset) -> tuple:
    """Build a keyset > (?,?) clause for the 2-tuple stable sort key."""
    if keyset is None:
        return "", []
    return " AND ({a}, {b}) > (?, ?)".format(a=sort_cols[0], b=sort_cols[1]), [keyset[0], keyset[1]]


def _paginate(store: ReadonlyStore, table: str, where: str, params: List[object],
              sort_cols: List[str], limit: Optional[int], cursor: Optional[str],
              row_to_view, fingerprint_fields: dict) -> ProjectMemoryResult:
    """Deterministic keyset pagination over a single M4 table.

    sort_cols: 2 stable columns used for ordering + keyset (NULLs coalesced to '').
    """
    effective_limit = _validate_limit_local(limit)
    fp = _fp(fingerprint_fields)
    keyset = None
    if cursor is not None:
        data = _cursor.validate_cursor_binding(cursor, fp, effective_limit)
        keyset = (data["sort"][0], data["sort"][1])

    key_sql, key_params = _key_clause(sort_cols, keyset)
    sql = (
        f"SELECT * FROM {table} WHERE {where}{key_sql} "
        f"ORDER BY {sort_cols[0]} ASC, {sort_cols[1]} ASC LIMIT ?"
    )
    try:
        rows = store.conn.execute(sql, params + key_params + [effective_limit]).fetchall()
    except Exception as exc:  # pragma: no cover - defensive
        raise QueryError(code=DATABASE_UNAVAILABLE, message="query_failed") from exc

    views = [row_to_view(r) for r in rows]

    next_cursor = None
    if len(views) >= effective_limit:
        last = rows[effective_limit - 1]
        next_cursor = _cursor.encode_cursor(
            fp,
            str(last[sort_cols[0]] if last[sort_cols[0]] is not None else ""),
            str(last[sort_cols[1]] if last[sort_cols[1]] is not None else ""),
            effective_limit,
        )
    return ProjectMemoryResult(items=views, query=fingerprint_fields, total=len(views), next_cursor=next_cursor)


def _fp(fields: dict) -> str:
    """M4 query fingerprint: SHA-256 over sorted, None-excluded field dict."""
    import hashlib, json
    canonical = json.dumps({k: v for k, v in sorted(fields.items()) if v is not None},
                            sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Row -> View mappers (metadata-only; provenance safe)
# ---------------------------------------------------------------------------


def _charter_view(row) -> CharterView:
    return CharterView(
        charter_id=row["charter_id"], project_id=row["project_id"], version=int(row["version"]),
        name=row["name"], goal=row["goal"], scope=row["scope"], non_goals=row["non_goals"],
        constraints=row["constraints"], architecture_principles=row["architecture_principles"],
        success_criteria=row["success_criteria"], lifecycle_status=row["lifecycle_status"],
        state=row["state"], source_event_id=row["source_event_id"], trace_id=row["trace_id"],
        session_id=row["session_id"], profile_id=row["profile_id"], created_at=row["created_at"],
        updated_at=row["updated_at"], supersedes=row["supersedes"], verification_ref=row["verification_ref"],
    )


def _requirement_view(row) -> RequirementView:
    return RequirementView(
        requirement_id=row["requirement_id"], project_id=row["project_id"], statement=row["statement"],
        lifecycle_status=row["lifecycle_status"], state=row["state"],
        verification_status=row["verification_status"], supersedes=row["supersedes"],
        replaced_by=row["replaced_by"], linked_decision_ids=row["linked_decision_ids"],
        linked_artifact_ids=row["linked_artifact_ids"], linked_verification_ids=row["linked_verification_ids"],
        source_event_id=row["source_event_id"], trace_id=row["trace_id"], session_id=row["session_id"],
        profile_id=row["profile_id"], created_at=row["created_at"],
    )


def _decision_view(row) -> DecisionView:
    return DecisionView(
        decision_id=row["decision_id"], project_id=row["project_id"], scope=row["scope"],
        decision_key=row["decision_key"], statement=row["statement"], rationale_ref=row["rationale_ref"],
        alternatives=row["alternatives"], lifecycle_status=row["lifecycle_status"], state=row["state"],
        supersedes_id=row["supersedes_id"], replaced_by=row["replaced_by"], effective_at=row["effective_at"],
        linked_requirement_ids=row["linked_requirement_ids"], linked_artifact_ids=row["linked_artifact_ids"],
        linked_verification_ids=row["linked_verification_ids"], source_event_id=row["source_event_id"],
        trace_id=row["trace_id"], session_id=row["session_id"], profile_id=row["profile_id"],
    )


def _state_view(row) -> ProjectStateView:
    return ProjectStateView(
        id=int(row["id"]), project_id=row["project_id"], scope=row["scope"], state_key=row["state_key"],
        state_value=row["state_value"], state_ref=row["state_ref"], lifecycle_status=row["lifecycle_status"],
        verification_status=row["verification_status"], effective_at=row["effective_at"],
        supersedes=row["supersedes"], source_event_id=row["source_event_id"], trace_id=row["trace_id"],
        session_id=row["session_id"], profile_id=row["profile_id"],
    )


def _verification_view(row) -> VerificationView:
    return VerificationView(
        verification_id=row["verification_id"], subject_type=row["subject_type"], subject_id=row["subject_id"],
        project_id=row["project_id"], method=row["method"], command_ref=row["command_ref"],
        observed_result=row["observed_result"], tested_commit=row["tested_commit"],
        source_event_id=row["source_event_id"], timestamp=row["timestamp"],
        verification_status=row["verification_status"], artifact_references=row["artifact_references"],
    )


def _artifact_view(row) -> ProjectArtifactView:
    return ProjectArtifactView(
        artifact_id=row["artifact_id"], project_id=row["project_id"], artifact_type=row["artifact_type"],
        version=row["version"], safe_reference=row["safe_reference"], source_event_id=row["source_event_id"],
        created_at=row["created_at"], verification_status=row["verification_status"],
        linked_requirement_ids=row["linked_requirement_ids"], linked_decision_ids=row["linked_decision_ids"],
        linked_state_keys=row["linked_state_keys"],
        kind=row["kind"] if "kind" in row.keys() else None,
        content_hash=row["content_hash"] if "content_hash" in row.keys() else None,
        retention=row["retention"] if "retention" in row.keys() else None,
    )


# ---------------------------------------------------------------------------
# Charter reads
# ---------------------------------------------------------------------------


def get_project_charter(store: ReadonlyStore, project_id: str, charter_id: Optional[str] = None,
                         include_history: bool = False, include_source_event: bool = False) -> Optional[CharterView]:
    _require_project_id(project_id)
    try:
        if charter_id is not None:
            row = store.conn.execute(
                "SELECT * FROM zm_project_charters WHERE charter_id=? AND project_id=?",
                (charter_id, project_id),
            ).fetchone()
            if row is None:
                return None
            if not include_history and row["lifecycle_status"] == _DELETED:
                return None
            view = _charter_view(row)
            if include_source_event:
                view.source_event = _resolve_source(store, view.source_event_id)
            return view
        # Active charter selected by stored lifecycle_status='active' (not latest/version).
        row = store.conn.execute(
            "SELECT * FROM zm_project_charters WHERE project_id=? AND lifecycle_status='active'",
            (project_id,),
        ).fetchone()
        if row is None:
            return None
        view = _charter_view(row)
        if include_source_event:
            view.source_event = _resolve_source(store, view.source_event_id)
        return view
    except QueryError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise QueryError(code=DATABASE_UNAVAILABLE, message="charter_query_failed") from exc


def list_project_charters(store: ReadonlyStore, project_id: str, lifecycle_status: Optional[str] = None,
                          include_deleted: bool = False, limit: Optional[int] = None,
                          cursor: Optional[str] = None) -> ProjectMemoryResult:
    _require_project_id(project_id)
    _validate_lifecycle(lifecycle_status)
    clauses = ["project_id=?"]
    params: List[object] = [project_id]
    if lifecycle_status is not None:
        clauses.append("lifecycle_status=?")
        params.append(lifecycle_status)
    elif not include_deleted:
        clauses.append("lifecycle_status<>?")
        params.append(_DELETED)
    where = " AND ".join(clauses)
    fp_fields = {"project_id": project_id, "lifecycle_status": lifecycle_status, "tbl": "charters"}
    return _paginate(store, "zm_project_charters", where, params, ["charter_id", "created_at"],
                     limit, cursor, _charter_view, fp_fields)


# ---------------------------------------------------------------------------
# Requirement reads
# ---------------------------------------------------------------------------


def get_requirement(store: ReadonlyStore, requirement_id: str, include_source_event: bool = False) -> Optional[RequirementView]:
    if not isinstance(requirement_id, str) or not requirement_id:
        raise QueryError(code=INVALID_QUERY, message="empty_requirement_id")
    try:
        row = store.conn.execute(
            "SELECT * FROM zm_requirements WHERE requirement_id=?", (requirement_id,)
        ).fetchone()
        if row is None or row["lifecycle_status"] == _DELETED:
            return None
        view = _requirement_view(row)
        if include_source_event:
            view.source_event = _resolve_source(store, view.source_event_id)
        return view
    except QueryError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise QueryError(code=DATABASE_UNAVAILABLE, message="requirement_query_failed") from exc


def list_requirements(store: ReadonlyStore, project_id: str, state: Optional[str] = None,
                       lifecycle_status: Optional[str] = None, limit: Optional[int] = None,
                       cursor: Optional[str] = None) -> ProjectMemoryResult:
    _require_project_id(project_id)
    _validate_lifecycle(lifecycle_status)
    clauses = ["project_id=?"]
    params: List[object] = [project_id]
    if lifecycle_status is not None:
        clauses.append("lifecycle_status=?")
        params.append(lifecycle_status)
    else:
        clauses.append("lifecycle_status<>?")
        params.append(_DELETED)
    if state is not None:
        clauses.append("state=?")
        params.append(state)
    where = " AND ".join(clauses)
    fp_fields = {"project_id": project_id, "state": state, "lifecycle_status": lifecycle_status, "tbl": "requirements"}
    return _paginate(store, "zm_requirements", where, params, ["requirement_id", "created_at"],
                     limit, cursor, _requirement_view, fp_fields)


# ---------------------------------------------------------------------------
# Decision reads
# ---------------------------------------------------------------------------


def get_decision(store: ReadonlyStore, decision_id: str) -> Optional[DecisionView]:
    if not isinstance(decision_id, str) or not decision_id:
        raise QueryError(code=INVALID_QUERY, message="empty_decision_id")
    try:
        row = store.conn.execute(
            "SELECT * FROM zm_decisions WHERE decision_id=?", (decision_id,)
        ).fetchone()
        if row is None or row["lifecycle_status"] == _DELETED:
            return None
        return _decision_view(row)
    except QueryError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise QueryError(code=DATABASE_UNAVAILABLE, message="decision_query_failed") from exc


def list_decisions(store: ReadonlyStore, project_id: str, lifecycle_status: Optional[str] = None,
                   limit: Optional[int] = None, cursor: Optional[str] = None) -> ProjectMemoryResult:
    _require_project_id(project_id)
    _validate_lifecycle(lifecycle_status)
    clauses = ["project_id=?"]
    params: List[object] = [project_id]
    if lifecycle_status is not None:
        clauses.append("lifecycle_status=?")
        params.append(lifecycle_status)
    else:
        clauses.append("lifecycle_status<>?")
        params.append(_DELETED)
    where = " AND ".join(clauses)
    fp_fields = {"project_id": project_id, "lifecycle_status": lifecycle_status, "tbl": "decisions"}
    return _paginate(store, "zm_decisions", where, params, ["decision_id", "effective_at"],
                     limit, cursor, _decision_view, fp_fields)


def get_active_decision(store: ReadonlyStore, project_id: str, scope: Optional[str],
                        decision_key: str) -> Optional[DecisionView]:
    _require_project_id(project_id)
    if not isinstance(decision_key, str) or not decision_key:
        raise QueryError(code=INVALID_QUERY, message="decision_key_required")
    try:
        row = store.conn.execute(
            "SELECT * FROM zm_decisions "
            "WHERE project_id=? AND scope IS ? AND decision_key=? AND lifecycle_status='active'",
            (project_id, scope, decision_key),
        ).fetchone()
        if row is None:
            return None
        return _decision_view(row)
    except QueryError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise QueryError(code=DATABASE_UNAVAILABLE, message="active_decision_query_failed") from exc


# ---------------------------------------------------------------------------
# Current Project State reads
# ---------------------------------------------------------------------------


def get_current_project_state(store: ReadonlyStore, project_id: str,
                               scope: Optional[str] = None) -> List[ProjectStateView]:
    _require_project_id(project_id)
    clauses = ["project_id=?", "lifecycle_status='active'"]
    params: List[object] = [project_id]
    if scope is not None:
        clauses.append("scope IS ?")
        params.append(scope)
    where = " AND ".join(clauses)
    try:
        rows = store.conn.execute(
            f"SELECT * FROM zm_project_state WHERE {where} ORDER BY state_key ASC, effective_at ASC",
            params,
        ).fetchall()
    except Exception as exc:  # pragma: no cover - defensive
        raise QueryError(code=DATABASE_UNAVAILABLE, message="state_query_failed") from exc
    return [_state_view(r) for r in rows]


def get_state_value(store: ReadonlyStore, project_id: str, scope: Optional[str],
                    state_key: str) -> Optional[ProjectStateView]:
    _require_project_id(project_id)
    if not isinstance(state_key, str) or not state_key:
        # NULL state_key is NOT a logical lookup slot; do not invent one.
        raise QueryError(code=INVALID_QUERY, message="state_key_required")
    try:
        row = store.conn.execute(
            "SELECT * FROM zm_project_state "
            "WHERE project_id=? AND scope IS ? AND state_key=? AND lifecycle_status='active'",
            (project_id, scope, state_key),
        ).fetchone()
        if row is None:
            return None
        return _state_view(row)
    except QueryError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise QueryError(code=DATABASE_UNAVAILABLE, message="state_value_query_failed") from exc


# ---------------------------------------------------------------------------
# Verification reads
# ---------------------------------------------------------------------------


def get_verification(store: ReadonlyStore, verification_id: str) -> Optional[VerificationView]:
    if not isinstance(verification_id, str) or not verification_id:
        raise QueryError(code=INVALID_QUERY, message="empty_verification_id")
    try:
        row = store.conn.execute(
            "SELECT * FROM zm_verifications WHERE verification_id=?", (verification_id,)
        ).fetchone()
        return _verification_view(row) if row is not None else None
    except QueryError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise QueryError(code=DATABASE_UNAVAILABLE, message="verification_query_failed") from exc


def list_verifications(store: ReadonlyStore, project_id: Optional[str] = None,
                        subject_type: Optional[str] = None, subject_id: Optional[str] = None,
                        verification_status: Optional[str] = None, limit: Optional[int] = None,
                        cursor: Optional[str] = None) -> ProjectMemoryResult:
    _validate_subject_type(subject_type)
    _validate_verification_status(verification_status)
    clauses = []
    params: List[object] = []
    if project_id is not None:
        if not project_id:
            raise QueryError(code=INVALID_PROJECT_ID, message="empty_project_id")
        clauses.append("project_id=?")
        params.append(project_id)
    if subject_type is not None:
        clauses.append("subject_type=?")
        params.append(subject_type)
    if subject_id is not None:
        clauses.append("subject_id=?")
        params.append(subject_id)
    if verification_status is not None:
        clauses.append("verification_status=?")
        params.append(verification_status)
    where = " AND ".join(clauses) if clauses else "1=1"
    fp_fields = {"project_id": project_id, "subject_type": subject_type, "subject_id": subject_id,
                 "verification_status": verification_status, "tbl": "verifications"}
    return _paginate(store, "zm_verifications", where, params, ["verification_id", "timestamp"],
                     limit, cursor, _verification_view, fp_fields)


# ---------------------------------------------------------------------------
# Project Artifact reads (joins M2 zm_artifacts for safe metadata only)
# ---------------------------------------------------------------------------


def list_project_artifacts(store: ReadonlyStore, project_id: str, artifact_type: Optional[str] = None,
                           limit: Optional[int] = None, cursor: Optional[str] = None) -> ProjectMemoryResult:
    _require_project_id(project_id)
    clauses = ["pa.project_id=?"]
    params: List[object] = [project_id]
    if artifact_type is not None:
        clauses.append("pa.artifact_type=?")
        params.append(artifact_type)
    where = " AND ".join(clauses)
    fp_fields = {"project_id": project_id, "artifact_type": artifact_type, "tbl": "project_artifacts"}
    effective_limit = _validate_limit_local(limit)
    fp = _fp(fp_fields)
    keyset = None
    if cursor is not None:
        data = _cursor.validate_cursor_binding(cursor, fp, effective_limit)
        keyset = (data["sort"][0], data["sort"][1])
    key_sql, key_params = _key_clause(["pa.artifact_id", "pa.created_at"], keyset)
    sql = (
        "SELECT pa.*, a.kind, a.content_hash, a.retention "
        "FROM zm_project_artifacts pa LEFT JOIN zm_artifacts a ON pa.artifact_id=a.artifact_id "
        f"WHERE {where}{key_sql} ORDER BY pa.artifact_id ASC, pa.created_at ASC LIMIT ?"
    )
    try:
        rows = store.conn.execute(sql, params + key_params + [effective_limit]).fetchall()
    except Exception as exc:  # pragma: no cover - defensive
        raise QueryError(code=DATABASE_UNAVAILABLE, message="artifact_query_failed") from exc
    views = [_artifact_view(r) for r in rows]
    next_cursor = None
    if len(views) >= effective_limit:
        last = rows[effective_limit - 1]
        next_cursor = _cursor.encode_cursor(
            fp,
            str(last["artifact_id"]),
            str(last["created_at"] if last["created_at"] is not None else ""),
            effective_limit,
        )
    return ProjectMemoryResult(items=views, query=fp_fields, total=len(views), next_cursor=next_cursor)


# ---------------------------------------------------------------------------
# Read-only proof helper
# ---------------------------------------------------------------------------


def is_query_only(store: ReadonlyStore) -> bool:
    """Reflect whether the store connection enforces query_only (TRUE READ-ONLY)."""
    return _readonly_conn_is_query_only(store)


__all__ = [
    "INVALID_PROJECT_ID",
    "INVALID_SUBJECT_TYPE",
    "CharterView",
    "RequirementView",
    "DecisionView",
    "ProjectStateView",
    "VerificationView",
    "ProjectArtifactView",
    "ProjectMemoryResult",
    "get_project_charter",
    "list_project_charters",
    "get_requirement",
    "list_requirements",
    "get_decision",
    "list_decisions",
    "get_active_decision",
    "get_current_project_state",
    "get_state_value",
    "get_verification",
    "list_verifications",
    "list_project_artifacts",
    "is_query_only",
    "open_readonly",
    "ReadonlyStore",
]
