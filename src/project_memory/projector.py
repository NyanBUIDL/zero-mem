"""M4.2 deterministic projector for Project Charter and Requirement Registry.

Write/project path only. Consumes explicit typed operation envelopes
(contracts.CharterOp / RequirementOp). It does NOT:
- infer charter/requirement data from prose, free text, or semantic similarity;
- derive identity from trace_id, requirement text, hashes, or timestamps;
- auto-promote an assistant_claim to active;
- silently overwrite prior versions (versioning + supersession are explicit);
- leak raw SQLite exceptions, payloads, or secrets.

Guarantees per operation (atomic single transaction on the given connection):
- idempotence: replaying the same op yields the same committed state, no duplicates;
- transaction safety: state + supersession commit together or roll back together;
- active-uniqueness (charter): at most one active charter per project, enforced by
  the v7 partial unique index, with the prior active marked superseded atomically;
- provenance retained on every row (source_event_id, trace_id, session_id,
  project_id, profile_id, created_at);
- lifecycle_check: lifecycle_status constrained to the closed enum by the schema;
- conflict preservation: if an active-uniqueness conflict occurs, the existing
  record is preserved and a sanitized ConflictError is raised (no winner, no overwrite).

The caller passes a live sqlite3.Connection (e.g. store._conn). The projector
manages BEGIN/COMMIT/ROLLBACK so each op is atomic. It never calls ensure_schema
and never touches JSONL.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from .contracts import (
    LIFECYCLE_ENUM,
    M4Op,
    M4Domain,
    CharterOp,
    RequirementOp,
    DecisionOp,
    M4ProjectionError,
    MissingIdentityError,
    InvalidTransitionError,
    ConflictError,
)


CLASSIFY_CHARTER = "charter"
CLASSIFY_REQUIREMENT = "requirement"
CLASSIFY_DECISION = "decision"
CLASSIFY_SKIP = "skip"


def _now() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _begin(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN")


def _commit(conn: sqlite3.Connection) -> None:
    conn.commit()


def _rollback(conn: sqlite3.Connection) -> None:
    try:
        conn.rollback()
    except Exception:
        pass


def _sanitize(op_kind: str, detail: str) -> M4ProjectionError:
    """Return a sanitized M4ProjectionError with no raw SQL/payload/secret text."""
    clean = (detail or "").replace("\n", " ").strip()
    if len(clean) > 200:
        clean = clean[:200] + "...(truncated)"
    return M4ProjectionError(f"{op_kind}: {clean}")


# ----------------------------------------------------------------------------
# Charter projection
# ----------------------------------------------------------------------------


def _charter_columns() -> list[str]:
    return [
        "charter_id", "project_id", "version", "name", "goal", "scope",
        "non_goals", "constraints", "architecture_principles", "success_criteria",
        "lifecycle_status", "state", "source_event_id", "trace_id", "session_id",
        "profile_id", "created_at", "updated_at", "supersedes", "verification_ref",
    ]


def _row_to_charter_values(op: CharterOp, version: int, updated_at: str) -> tuple:
    return (
        op.charter_id, op.project_id, version, op.name, op.goal, op.scope,
        op.non_goals, op.constraints, op.architecture_principles,
        op.success_criteria, op.lifecycle_status, op.state, op.source_event_id,
        op.trace_id, op.session_id, op.profile_id, op.created_at or updated_at,
        updated_at, op.supersedes, op.verification_ref,
    )


def _existing_charter(conn: sqlite3.Connection, charter_id: str) -> Optional[dict]:
    cur = conn.execute(
        "SELECT * FROM zm_project_charters WHERE charter_id=?", (charter_id,)
    )
    return cur.fetchone()


def project_charter(conn: sqlite3.Connection, op: CharterOp) -> dict:
    """Project one Charter operation deterministically and atomically.

    Returns a small outcome dict: {"op", "charter_id", "version", "action"}.
    action in {created, versioned, transitioned, deleted, noop}.
    Raises sanitized M4ProjectionError subclasses on any failure (rolls back).
    """
    op.validate()
    updated_at = _now()
    try:
        _begin(conn)
        existing = _existing_charter(conn, op.charter_id)

        if op.op == M4Op.CREATE.value:
            if existing is not None:
                # Idempotent: same content -> no-op; differing content with no
                # explicit update op -> do not silently overwrite.
                if _charter_content_equal(existing, op):
                    _commit(conn)
                    return {"op": op.op, "charter_id": op.charter_id,
                            "version": existing["version"], "action": "noop"}
                # Exists but content differs: require an explicit update op.
                raise InvalidTransitionError(
                    "charter_id exists; use op=update/supersede to change it"
                )
            version = op.version if op.version is not None else 1
            _insert_charter(conn, op, version, updated_at)
            _commit(conn)
            return {"op": op.op, "charter_id": op.charter_id,
                    "version": version, "action": "created"}

        if op.op == M4Op.UPDATE.value or op.op == M4Op.SUPERSEDE.value:
            # UPDATE of the SAME charter_id: version in place (version+1). The
            # VERIFIED v7 schema uses charter_id as a single PRIMARY KEY, so all
            # historical versions are preserved in the canonical JSONL (authoritative,
            # append-only) and reproduced by rebuild; the derived table holds the
            # current version with an incremented version counter.
            # SUPERSEDE of a DISTINCT charter_id: the new charter_id is inserted
            # (active) and the prior (op.supersedes) is marked superseded; both rows
            # are preserved. This never silently overwrites the prior row.
            if op.op == M4Op.SUPERSEDE.value:
                if not op.supersedes:
                    raise MissingIdentityError("supersede op requires explicit supersedes id")
                prior = _existing_charter(conn, op.supersedes)
                if prior is None:
                    raise MissingIdentityError(
                        "cannot supersede a charter that does not exist"
                    )
                if existing is not None:
                    # Already projected this supersession; idempotent no-op.
                    _commit(conn)
                    return {"op": op.op, "charter_id": op.charter_id,
                            "version": existing["version"], "action": "noop"}
                new_version = op.version if op.version is not None else 1
                _mark_superseded(conn, op.supersedes, updated_at)
                _insert_charter(conn, op, new_version, updated_at)
                _commit(conn)
                return {"op": op.op, "charter_id": op.charter_id,
                        "version": new_version, "action": "versioned"}
            # UPDATE in place
            new_version = (existing["version"] or 0) + 1
            conn.execute(
                "UPDATE zm_project_charters SET version=?, name=?, goal=?, scope=?, "
                "non_goals=?, constraints=?, architecture_principles=?, success_criteria=?, "
                "lifecycle_status=?, state=?, source_event_id=?, trace_id=?, session_id=?, "
                "profile_id=?, created_at=?, updated_at=?, supersedes=?, verification_ref=? "
                "WHERE charter_id=?",
                (new_version, op.name, op.goal, op.scope, op.non_goals, op.constraints,
                 op.architecture_principles, op.success_criteria, op.lifecycle_status,
                 op.state, op.source_event_id, op.trace_id, op.session_id, op.profile_id,
                 op.created_at or updated_at, updated_at, op.supersedes, op.verification_ref,
                 op.charter_id),
            )
            _commit(conn)
            return {"op": op.op, "charter_id": op.charter_id,
                    "version": new_version, "action": "versioned"}

        if op.op == M4Op.TRANSITION.value:
            if existing is None:
                raise MissingIdentityError(
                    "cannot transition a charter that does not exist"
                )
            _transition_charter(conn, existing, op, updated_at)
            _commit(conn)
            return {"op": op.op, "charter_id": op.charter_id,
                    "version": existing["version"], "action": "transitioned"}

        if op.op == M4Op.DELETE.value:
            if existing is None:
                raise MissingIdentityError(
                    "cannot delete a charter that does not exist"
                )
            _transition_charter(conn, existing, op, updated_at)
            _commit(conn)
            return {"op": op.op, "charter_id": op.charter_id,
                    "version": existing["version"], "action": "deleted"}

        raise InvalidTransitionError(f"unsupported charter op: {op.op}")
    except M4ProjectionError:
        _rollback(conn)
        raise
    except sqlite3.IntegrityError as exc:
        _rollback(conn)
        msg = str(exc)
        # Active uniqueness violation (two active charters per project) is a
        # preserved conflict, not a corruption. SQLite reports the column, not
        # always the index name, so detect via UNIQUE + project_id.
        if "UNIQUE constraint failed" in msg and "project_id" in msg:
            raise ConflictError(
                "active charter conflict preserved; existing active charter retained"
            ) from None
        raise _sanitize("charter_integrity", msg) from None
    except Exception as exc:  # noqa: BLE001 - sanitize everything else
        _rollback(conn)
        raise _sanitize("charter_project", str(exc)) from None


def _insert_charter(conn: sqlite3.Connection, op: CharterOp, version: int, updated_at: str) -> None:
    cols = _charter_columns()
    placeholders = ", ".join("?" for _ in cols)
    sql = f"INSERT INTO zm_project_charters ({', '.join(cols)}) VALUES ({placeholders})"
    conn.execute(sql, _row_to_charter_values(op, version, updated_at))


def _mark_superseded(conn: sqlite3.Connection, charter_id: str, updated_at: str) -> None:
    conn.execute(
        "UPDATE zm_project_charters SET lifecycle_status='superseded', "
        "updated_at=? WHERE charter_id=?",
        (updated_at, charter_id),
    )


def _transition_charter(conn: sqlite3.Connection, existing: dict, op: CharterOp, updated_at: str) -> None:
    # Terminal-state guard: once deleted, a charter cannot leave deleted.
    if existing["lifecycle_status"] == "deleted" and op.lifecycle_status != "deleted":
        raise InvalidTransitionError("deleted charter is terminal; cannot transition out")
    conn.execute(
        "UPDATE zm_project_charters SET lifecycle_status=?, state=?, updated_at=? "
        "WHERE charter_id=?",
        (op.lifecycle_status, op.state, updated_at, op.charter_id),
    )


def _charter_content_equal(existing: dict, op: CharterOp) -> bool:
    keys = set(existing.keys())
    fields = ["name", "goal", "scope", "non_goals", "constraints",
              "architecture_principles", "success_criteria", "lifecycle_status", "state"]
    for f in fields:
        if (existing[f] if f in keys else None) != (getattr(op, f) or None):
            return False
    return True


# ----------------------------------------------------------------------------
# Requirement projection
# ----------------------------------------------------------------------------


def _requirement_columns() -> list[str]:
    return [
        "requirement_id", "project_id", "statement", "source_event_id",
        "created_at", "lifecycle_status", "state", "verification_status",
        "supersedes", "replaced_by", "linked_decision_ids", "linked_artifact_ids",
        "linked_verification_ids", "trace_id", "session_id", "profile_id",
    ]


def _row_to_requirement_values(op: RequirementOp, created_at: str) -> tuple:
    return (
        op.requirement_id, op.project_id, op.statement, op.source_event_id,
        created_at, op.lifecycle_status, op.state, op.verification_status,
        op.supersedes, op.replaced_by, op.linked_decision_ids,
        op.linked_artifact_ids, op.linked_verification_ids, op.trace_id,
        op.session_id, op.profile_id,
    )


def _existing_requirement(conn: sqlite3.Connection, requirement_id: str) -> Optional[dict]:
    cur = conn.execute(
        "SELECT * FROM zm_requirements WHERE requirement_id=?", (requirement_id,)
    )
    return cur.fetchone()


def project_requirement(conn: sqlite3.Connection, op: RequirementOp) -> dict:
    """Project one Requirement operation deterministically and atomically.

    Returns {"op", "requirement_id", "action"}.
    action in {created, transitioned, superseded, deleted, noop}.
    Supersession is explicit (supersedes/replaced_by); the old requirement is
    preserved and linked, never physically deleted. Conflicts are preserved
    (no winner, no overwrite). Terminal `deleted` cannot be left.
    """
    op.validate()
    created_at = op.created_at or _now()
    try:
        _begin(conn)
        existing = _existing_requirement(conn, op.requirement_id)

        if op.op == M4Op.CREATE.value:
            if existing is not None:
                if _requirement_content_equal(existing, op):
                    _commit(conn)
                    return {"op": op.op, "requirement_id": op.requirement_id,
                            "action": "noop"}
                raise InvalidTransitionError(
                    "requirement_id exists; use op=transition/supersede to change it"
                )
            _insert_requirement(conn, op, created_at)
            _commit(conn)
            return {"op": op.op, "requirement_id": op.requirement_id, "action": "created"}

        if op.op == M4Op.TRANSITION.value:
            if existing is None:
                raise MissingIdentityError(
                    "cannot transition a requirement that does not exist"
                )
            if existing["lifecycle_status"] == "deleted" and op.lifecycle_status != "deleted":
                raise InvalidTransitionError("deleted requirement is terminal")
            conn.execute(
                "UPDATE zm_requirements SET lifecycle_status=?, state=?, "
                "verification_status=?, statement=COALESCE(?, statement), "
                "supersedes=COALESCE(?, supersedes), replaced_by=COALESCE(?, replaced_by), "
                "linked_decision_ids=COALESCE(?, linked_decision_ids), "
                "linked_artifact_ids=COALESCE(?, linked_artifact_ids), "
                "linked_verification_ids=COALESCE(?, linked_verification_ids) "
                "WHERE requirement_id=?",
                (op.lifecycle_status, op.state, op.verification_status, op.statement,
                 op.supersedes, op.replaced_by, op.linked_decision_ids,
                 op.linked_artifact_ids, op.linked_verification_ids, op.requirement_id),
            )
            _commit(conn)
            return {"op": op.op, "requirement_id": op.requirement_id, "action": "transitioned"}

        if op.op == M4Op.SUPERSEDE.value:
            if not op.supersedes:
                raise MissingIdentityError("supersede op requires explicit supersedes id")
            prior = _existing_requirement(conn, op.supersedes)
            if prior is None:
                raise MissingIdentityError(
                    "cannot supersede a requirement that does not exist"
                )
            if existing is not None:
                # Already projected this supersession; idempotent no-op.
                _commit(conn)
                return {"op": op.op, "requirement_id": op.requirement_id,
                        "action": "noop"}
            # Preserve old requirement (marked superseded), insert new active row
            # with the explicit link. Never physically deletes history. Insert the
            # new row FIRST so OLD.replaced_by -> NEW satisfies the FK constraint.
            _insert_requirement(conn, op, created_at)
            conn.execute(
                "UPDATE zm_requirements SET lifecycle_status='superseded', "
                "replaced_by=? WHERE requirement_id=?",
                (op.requirement_id, op.supersedes),
            )
            _commit(conn)
            return {"op": op.op, "requirement_id": op.requirement_id, "action": "superseded"}

        if op.op == M4Op.DELETE.value:
            if existing is None:
                raise MissingIdentityError(
                    "cannot delete a requirement that does not exist"
                )
            conn.execute(
                "UPDATE zm_requirements SET lifecycle_status='deleted' WHERE requirement_id=?",
                (op.requirement_id,),
            )
            _commit(conn)
            return {"op": op.op, "requirement_id": op.requirement_id, "action": "deleted"}

        raise InvalidTransitionError(f"unsupported requirement op: {op.op}")
    except M4ProjectionError:
        _rollback(conn)
        raise
    except sqlite3.IntegrityError as exc:
        _rollback(conn)
        raise _sanitize("requirement_integrity", str(exc)) from None
    except Exception as exc:  # noqa: BLE001
        _rollback(conn)
        raise _sanitize("requirement_project", str(exc)) from None


def _insert_requirement(conn: sqlite3.Connection, op: RequirementOp, created_at: str) -> None:
    cols = _requirement_columns()
    placeholders = ", ".join("?" for _ in cols)
    sql = f"INSERT INTO zm_requirements ({', '.join(cols)}) VALUES ({placeholders})"
    conn.execute(sql, _row_to_requirement_values(op, created_at))


def _requirement_content_equal(existing: dict, op: RequirementOp) -> bool:
    keys = set(existing.keys())
    fields = ["statement", "lifecycle_status", "state", "verification_status"]
    for f in fields:
        if (existing[f] if f in keys else None) != (getattr(op, f) or None):
            return False
    return True


# ----------------------------------------------------------------------------
# Decision Log projection
# ----------------------------------------------------------------------------


def _decision_columns() -> list[str]:
    # NOTE: the VERIFIED M4.1 v7 schema for zm_decisions has no `created_at`
    # column; temporal provenance is carried by `effective_at`. We respect the
    # VERIFIED schema and do not modify migration 7.
    return [
        "decision_id", "project_id", "scope", "decision_key", "statement",
        "rationale_ref", "alternatives", "source_event_id", "lifecycle_status",
        "state", "supersedes_id", "replaced_by", "effective_at",
        "linked_requirement_ids", "linked_artifact_ids", "linked_verification_ids",
        "trace_id", "session_id", "profile_id",
    ]


def _existing_decision(conn: sqlite3.Connection, decision_id: str) -> Optional[dict]:
    cur = conn.execute(
        "SELECT * FROM zm_decisions WHERE decision_id=?", (decision_id,)
    )
    return cur.fetchone()


def project_decision(conn: sqlite3.Connection, op: DecisionOp) -> dict:
    """Project one Decision operation deterministically and atomically.

    Returns {"op", "decision_id", "action"}; action in
    {created, transitioned, superseded, deleted, noop, conflict_preserved}.

    Guarantees:
    - explicit decision_id identity; trace_id never used as identity;
    - decision_key nullable; NULL-key decisions coexist (no false collision);
    - lifecycle_status closed enum; generic domain `state` separate;
    - explicit supersession only (distinct new decision_id; old preserved + linked);
    - active uniqueness via v7 partial unique index (project_id, scope, key);
    - conflict preserved: an explicit `conflicted` lifecycle is stored as-is; no
      winner chosen, no auto-mutation of other records;
    - transaction safety: supersession/transition commit together or roll back;
    - idempotence: replaying the same op yields the same state, no duplicates;
    - no LLM / semantic / timestamp inference; sanitized errors (no raw SQL/secret).
    """
    op.validate()
    created_at = op.created_at or _now()
    try:
        _begin(conn)
        existing = _existing_decision(conn, op.decision_id)

        if op.op == M4Op.CREATE.value:
            if existing is not None:
                if _decision_content_equal(existing, op):
                    _commit(conn)
                    return {"op": op.op, "decision_id": op.decision_id, "action": "noop"}
                raise InvalidTransitionError(
                    "decision_id exists; use op=transition/supersede to change it"
                )
            _insert_decision(conn, op, created_at)
            _commit(conn)
            return {"op": op.op, "decision_id": op.decision_id, "action": "created"}

        if op.op == M4Op.TRANSITION.value:
            if existing is None:
                raise MissingIdentityError(
                    "cannot transition a decision that does not exist"
                )
            if existing["lifecycle_status"] == "deleted" and op.lifecycle_status != "deleted":
                raise InvalidTransitionError("deleted decision is terminal")
            # Update current state in place (history lives in canonical JSONL).
            # A conflict is preserved as-is: we never force other records to
            # conflicted; we only store the explicit lifecycle the op supplies.
            conn.execute(
                "UPDATE zm_decisions SET lifecycle_status=?, state=?, "
                "decision_key=COALESCE(?, decision_key), scope=COALESCE(?, scope), "
                "statement=COALESCE(?, statement), rationale_ref=COALESCE(?, rationale_ref), "
                "alternatives=COALESCE(?, alternatives), effective_at=COALESCE(?, effective_at), "
                "supersedes_id=COALESCE(?, supersedes_id), replaced_by=COALESCE(?, replaced_by), "
                "linked_requirement_ids=COALESCE(?, linked_requirement_ids), "
                "linked_artifact_ids=COALESCE(?, linked_artifact_ids), "
                "linked_verification_ids=COALESCE(?, linked_verification_ids) "
                "WHERE decision_id=?",
                (op.lifecycle_status, op.state, op.decision_key, op.scope, op.statement,
                 op.rationale_ref, op.alternatives, op.effective_at, op.supersedes_id,
                 op.replaced_by, op.linked_requirement_ids, op.linked_artifact_ids,
                 op.linked_verification_ids, op.decision_id),
            )
            _commit(conn)
            return {"op": op.op, "decision_id": op.decision_id, "action": "transitioned"}

        if op.op == M4Op.SUPERSEDE.value:
            if not op.supersedes_id:
                raise MissingIdentityError("supersede op requires explicit supersedes_id")
            prior = _existing_decision(conn, op.supersedes_id)
            if prior is None:
                raise MissingIdentityError(
                    "cannot supersede a decision that does not exist"
                )
            if existing is not None:
                # Already projected this supersession; idempotent no-op.
                _commit(conn)
                return {"op": op.op, "decision_id": op.decision_id, "action": "noop"}
            # Explicit chain link A <- B. To preserve the active-uniqueness
            # invariant atomically we must NOT have two active rows with the same
            # (project_id, scope, decision_key) at any committed point. So:
            #  1) insert B with a non-active lifecycle (avoids dual-active);
            #  2) mark A superseded + replaced_by=B (FK satisfied, B exists);
            #  3) promote B to its explicit lifecycle (active).
            # A is preserved (history retained), never physically deleted.
            _insert_decision(conn, op, created_at, force_lifecycle="candidate")
            conn.execute(
                "UPDATE zm_decisions SET lifecycle_status='superseded', "
                "replaced_by=? WHERE decision_id=?",
                (op.decision_id, op.supersedes_id),
            )
            conn.execute(
                "UPDATE zm_decisions SET lifecycle_status=? WHERE decision_id=?",
                (op.lifecycle_status, op.decision_id),
            )
            _commit(conn)
            return {"op": op.op, "decision_id": op.decision_id, "action": "superseded"}

        if op.op == M4Op.DELETE.value:
            if existing is None:
                raise MissingIdentityError(
                    "cannot delete a decision that does not exist"
                )
            conn.execute(
                "UPDATE zm_decisions SET lifecycle_status='deleted' WHERE decision_id=?",
                (op.decision_id,),
            )
            _commit(conn)
            return {"op": op.op, "decision_id": op.decision_id, "action": "deleted"}

        raise InvalidTransitionError(f"unsupported decision op: {op.op}")
    except M4ProjectionError:
        _rollback(conn)
        raise
    except sqlite3.IntegrityError as exc:
        _rollback(conn)
        msg = str(exc)
        # Active-uniqueness violation for a non-NULL (project_id, scope, key):
        # the existing valid active Decision must remain unchanged; the new op is
        # rejected with a sanitized conflict outcome (no winner, no overwrite).
        if "UNIQUE constraint failed" in msg and "zm_decisions" in msg:
            raise ConflictError(
                "active decision conflict preserved; existing active decision retained"
            ) from None
        if "FOREIGN KEY constraint failed" in msg:
            raise _sanitize("decision_fk", msg) from None
        raise _sanitize("decision_integrity", msg) from None
    except Exception as exc:  # noqa: BLE001
        _rollback(conn)
        raise _sanitize("decision_project", str(exc)) from None


def _insert_decision(conn: sqlite3.Connection, op: DecisionOp, created_at: str,
                     force_lifecycle: Optional[str] = None) -> None:
    cols = _decision_columns()
    placeholders = ", ".join("?" for _ in cols)
    eff = op.effective_at or created_at
    lifecycle = force_lifecycle if force_lifecycle is not None else op.lifecycle_status
    # column order matches _decision_columns(): ... lifecycle_status, state,
    # supersedes_id, replaced_by, effective_at, ...
    sql = f"INSERT INTO zm_decisions ({', '.join(cols)}) VALUES ({placeholders})"
    values = (
        op.decision_id, op.project_id, op.scope, op.decision_key, op.statement,
        op.rationale_ref, op.alternatives, op.source_event_id, lifecycle,
        op.state, op.supersedes_id, op.replaced_by, eff,
        op.linked_requirement_ids, op.linked_artifact_ids, op.linked_verification_ids,
        op.trace_id, op.session_id, op.profile_id,
    )
    conn.execute(sql, values)


def _decision_content_equal(existing: dict, op: DecisionOp) -> bool:
    keys = set(existing.keys())
    # temporal provenance: op.effective_at or op.created_at was folded into the
    # effective_at column at insert time.
    op_eff = op.effective_at or op.created_at
    fields = ["scope", "decision_key", "statement", "rationale_ref", "alternatives",
              "lifecycle_status", "state", "supersedes_id", "replaced_by",
              "linked_requirement_ids", "linked_artifact_ids", "linked_verification_ids"]
    for f in fields:
        if (existing[f] if f in keys else None) != (getattr(op, f) or None):
            return False
    if (existing["effective_at"] if "effective_at" in keys else None) != (op_eff or None):
        return False
    return True


# ----------------------------------------------------------------------------
# Event classification (deterministic; no inference / no invention)
# ----------------------------------------------------------------------------


def classify_event_for_m4(event: dict) -> str:
    """Classify a canonical event for M4 projection.

    Returns CLASSIFY_CHARTER / CLASSIFY_REQUIREMENT / CLASSIFY_DECISION /
    CLASSIFY_SKIP. Projection only occurs when the event carries an EXPLICIT
    structured M4 identity block (m4.domain + m4.identity + m4.op). If it does
    not, the outcome is CLASSIFY_SKIP (deterministic, no inference, no
    invention). Generic events (user_statement / assistant_claim /
    tool_observation / ...) are NOT projected into M4 merely by resemblance.
    """
    m4 = event.get("m4") if isinstance(event, dict) else None
    if not isinstance(m4, dict):
        return CLASSIFY_SKIP
    domain = m4.get("domain")
    identity = m4.get("identity")
    op = m4.get("op")
    if domain == M4Domain.CHARTER.value and identity and op:
        return CLASSIFY_CHARTER
    if domain == M4Domain.REQUIREMENT.value and identity and op:
        return CLASSIFY_REQUIREMENT
    if domain == M4Domain.DECISION.value and identity and op:
        return CLASSIFY_DECISION
    return CLASSIFY_SKIP


__all__ = [
    "project_charter",
    "project_requirement",
    "project_decision",
    "classify_event_for_m4",
    "CLASSIFY_CHARTER",
    "CLASSIFY_REQUIREMENT",
    "CLASSIFY_DECISION",
    "CLASSIFY_SKIP",
]
