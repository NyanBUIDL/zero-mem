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
    M4ProjectionError,
    MissingIdentityError,
    InvalidTransitionError,
    ConflictError,
)


CLASSIFY_CHARTER = "charter"
CLASSIFY_REQUIREMENT = "requirement"
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
# Event classification (deterministic; no inference / no invention)
# ----------------------------------------------------------------------------


def classify_event_for_m4(event: dict) -> str:
    """Classify a canonical event for M4 projection.

    Returns CLASSIFY_CHARTER / CLASSIFY_REQUIREMENT / CLASSIFY_SKIP.
    Projection only occurs when the event carries an EXPLICIT structured M4
    identity block (m4_domain + m4_op + m4_identity). If it does not, the
    outcome is CLASSIFY_SKIP (deterministic, no inference, no invention). The
    projector is only invoked with an explicit typed envelope; generic events
    (user_statement / assistant_claim / tool_observation / ...) are NOT
    projected into Charter/Requirement merely by resemblance.
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
    return CLASSIFY_SKIP


__all__ = [
    "project_charter",
    "project_requirement",
    "classify_event_for_m4",
    "CLASSIFY_CHARTER",
    "CLASSIFY_REQUIREMENT",
    "CLASSIFY_SKIP",
]
