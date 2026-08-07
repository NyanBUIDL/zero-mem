"""M2.2 Idempotent JSONL metadata ingestion (derived SQLite layer).

Reads the canonical M1 JSONL raw event stream (read-only) and inserts only
derived metadata into ``zm_meta``. Idempotent by ``event_id`` and
``sanitized_content_hash``. Resumable via ``zm_ingest_checkpoint`` and a
consumed-prefix hash that detects tampering with already-consumed bytes.

Invariants (required rules):
- JSONL is canonical and authoritative; SQLite is derived, disposable, rebuildable.
- SQLite never writes, truncates, reorders, or rewrites JSONL.
- No raw payload, secret, or exception text reaches ``zm_meta``, ``zm_ingest_log``,
  the in-memory report, or any diagnostic.
- Checkpoint advances ONLY after a committed outcome; ``transaction_failed`` and a
  crash-before-commit do NOT advance it.
- No retry, backoff, dead-letter store, or replay. ``zm_ingest_log`` is a committed
  sanitized record, not a dead-letter store.
- No LLM or network calls.

This module handles M2.2 (idempotent ingestion), M2.3 (lifecycle/verification projection +
rebuild_from_jsonl), M2.4 (relations/scopes/artifact-registry projection + active-key
and M2.5 (relational indexes, FTS5 over sanitized content, inspection helpers). It must
not be used for physical purge of canonical JSONL (Decision B: logical deletion only; M2.6),
retrieval, ranking, routing, MCP, Obsidian, or context injection (those are later milestones /
out of scope). M2.6 adds tombstone-based logical deletion: explicit deletion events project into
zm_tombstones + zm_deletion_audit + lifecycle/FTS state, deleted records are excluded from active
helpers, and historical provenance remains auditable via administrative helpers.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from src.storage.migrations import CURRENT_SCHEMA_VERSION
from src.storage.migrations import migrate_5 as _migrate_5
from ..capture.validation import validate_envelope


ZM_META_COLUMNS = (
    "event_id", "trace_id", "event_type", "source", "schema_version",
    "created_at", "observed_at", "sequence", "session_id", "profile_id",
    "project_id", "task_id", "turn_id", "parent_trace_id", "lifecycle_status",
    "verification_status", "confidence", "sensitivity", "retention",
    "content_hash", "redaction_applied", "ingested_at", "origin_jsonl",
)


class IngestionOutcome(str, Enum):
    NEW_EVENT = "new_event"
    DUPLICATE_EVENT_ID = "duplicate_event_id"
    DUPLICATE_CONTENT_HASH = "duplicate_content_hash"
    EVENT_ID_CONTENT_CONFLICT = "event_id_content_conflict"
    INVALID_RECORD = "invalid_record"
    TRANSACTION_FAILED = "transaction_failed"
    SOURCE_CHANGED = "source_changed"


# Outcomes that write a committed zm_ingest_log row and advance the checkpoint.
_COMMITTED_OUTCOMES = {
    IngestionOutcome.NEW_EVENT,
    IngestionOutcome.DUPLICATE_EVENT_ID,
    IngestionOutcome.DUPLICATE_CONTENT_HASH,
    IngestionOutcome.EVENT_ID_CONTENT_CONFLICT,
    IngestionOutcome.INVALID_RECORD,
}


def _commit(conn) -> None:
    conn.commit()


def _rollback(conn) -> None:
    conn.rollback()


def _now() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe_source_id(jsonl_path: Path) -> str:
    try:
        return jsonl_path.name
    except Exception:
        return "source"


def _classify_validation_error(exc: Exception) -> str:
    text = str(exc)
    if "missing required fields" in text:
        return "envelope_missing_field"
    return "envelope_invalid_value"


def _compute_prefix_hash(data: bytes, up_to_line: int) -> str:
    """sha256 over the exact bytes of complete lines 1..up_to_line (incl. newlines)."""
    parts = data.split(b"\n")
    complete_count = len(parts) - 1  # lines terminated by '\n'
    count = min(up_to_line, complete_count)
    h = hashlib.sha256()
    for i in range(count):
        h.update(parts[i] + b"\n")
    return h.hexdigest()


class PrefixHasher:
    """Incremental sha256 over committed complete-line bytes (incl. newlines)."""

    def __init__(self, initial: str = "") -> None:
        self._h = hashlib.sha256(bytes.fromhex(initial)) if initial else hashlib.sha256()

    def update(self, line_bytes_with_newline: bytes) -> None:
        self._h.update(line_bytes_with_newline)

    def hexdigest(self) -> str:
        return self._h.hexdigest()


@dataclass(frozen=True)
class IngestionFailure:
    """Sanitized failure: never carries raw line, payload, secret, or exception text."""
    source_id: str
    line_number: int
    failure_class: str
    diagnostic_code: str


@dataclass
class IngestionReport:
    source_id: str
    counts: dict = field(default_factory=lambda: {o.value: 0 for o in IngestionOutcome})
    failures: list = field(default_factory=list)  # list[IngestionFailure]
    stopped: bool = False  # True when ingestion halted (transaction_failed / source_changed)

    def add(self, outcome: IngestionOutcome) -> None:
        self.counts[outcome.value] = self.counts.get(outcome.value, 0) + 1

    def add_failure(self, failure: IngestionFailure) -> None:
        self.failures.append(failure)


def _iter_jsonl_lines(path: Path):
    """Yield (line_number, line_bytes, is_complete) for each line, read-only.

    Complete lines include their trailing newline. A trailing segment without a
    newline is yielded as incomplete (truncation guard) and is never hashed.
    """
    data = Path(path).read_bytes()
    parts = data.split(b"\n")
    complete_count = len(parts) - 1
    for i in range(complete_count):
        yield (i + 1, parts[i] + b"\n", True)
    if parts[-1]:
        yield (complete_count + 1, parts[-1], False)


def _project_row(env: dict, source_id: str) -> tuple:
    """Direct projection of approved envelope fields into zm_meta column order."""
    redaction = 1 if env.get("redaction_audit") else 0
    return (
        env["event_id"],
        env["trace_id"],
        env["event_type"],
        env["source"],
        int(env["schema_version"]),
        env["created_at"],
        env["observed_at"],
        int(env["sequence"]),
        env.get("session_id"),
        env.get("profile_id"),
        env.get("project_id"),
        env.get("task_id"),
        env.get("turn_id"),
        env.get("parent_trace_id"),
        env["lifecycle_status"],
        env["verification_status"],
        env["confidence"],
        env["sensitivity"],
        env["retention"],
        env["sanitized_content_hash"],
        redaction,
        _now(),
        source_id,
    )


def _seed_lifecycle_and_provenance(conn, env: dict) -> None:
    """Seed derived lifecycle-state and verification/provenance projections (M2.3).

    Called within the same per-line transaction as the zm_meta insert for a NEW_EVENT.
    - zm_lifecycle: mirrors the observed lifecycle_status; superseded_by/active_key are
      reserved (seeded NULL) for M2.4 enforcement — no invented transition logic here.
    - zm_provenance: one row from the envelope's verification_status + deterministic verifier;
      verifier-rank is stored as data only (no ranking/scoring/retrieval in M2).
    """
    event_id = env["event_id"]
    lifecycle_status = env["lifecycle_status"]
    conn.execute(
        "INSERT INTO zm_lifecycle (event_id, current_state, superseded_by, active_key, updated_at) "
        "VALUES (?,?,?,?,?)",
        (event_id, lifecycle_status, None, None, _now()),
    )
    conn.execute(
        "INSERT INTO zm_provenance (event_id, verification_status, verifier, evidence_ref, recorded_at) "
        "VALUES (?,?,?,?,?)",
        (event_id, env["verification_status"], "deterministic_check", env.get("trace_id"), _now()),
    )


def _earliest_event_id(conn, trace_id: str):
    """Return the earliest event_id for a trace (by sequence, then event_id), or None."""
    cur = conn.cursor()
    cur.execute(
        "SELECT event_id FROM zm_meta WHERE trace_id=? ORDER BY sequence ASC, event_id ASC LIMIT 1",
        (trace_id,),
    )
    row = cur.fetchone()
    return row["event_id"] if row is not None else None


def _project_relations_scopes(conn, env: dict) -> None:
    """Project derived relations, scopes, artifacts, and active-key enforcement (M2.4).

    Runs within the same per-line transaction as the zm_meta/lifecycle/provenance inserts for a
    NEW_EVENT. Derives edges ONLY from envelope-present signals:
    - parent_trace_id => child_of (to the parent trace's earliest event).
    - relation_ids entries => derived_from (to an existing event_id, or the earliest event of an
      existing trace_id); unknown targets are skipped (no invention).
    - project_id / profile_id (and optional knowledge_space_id) => zm_scopes rows (observed only).
    - active lifecycle_status => enforce at-most-one active per active_key (=trace_id): the prior
      active event is marked superseded and a 'supersedes' edge is written (no silent overwrite).
    - artifact_refs (if present) => zm_artifacts metadata rows (content storage deferred).
    """
    event_id = env["event_id"]
    trace_id = env.get("trace_id")
    now = _now()
    # --- relations: child_of from parent_trace_id ---
    parent = env.get("parent_trace_id")
    if parent:
        parent_event = _earliest_event_id(conn, parent)
        if parent_event is not None and parent_event != event_id:
            conn.execute(
                "INSERT INTO zm_relations (from_event_id, to_event_id, relation, verifier, evidence_ref, created_at) "
                "VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(from_event_id, to_event_id, relation) DO NOTHING",
                (event_id, parent_event, "child_of", "deterministic_check", trace_id, now),
            )
    # --- relations: derived_from from relation_ids ---
    for ref in env.get("relation_ids", ()) or ():
        ref = str(ref)
        target = None
        cur = conn.cursor()
        cur.execute("SELECT event_id FROM zm_meta WHERE event_id=? LIMIT 1", (ref,))
        r = cur.fetchone()
        if r is not None:
            target = r["event_id"]
        else:
            target = _earliest_event_id(conn, ref)
        if target is not None and target != event_id:
            conn.execute(
                "INSERT INTO zm_relations (from_event_id, to_event_id, relation, verifier, evidence_ref, created_at) "
                "VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(from_event_id, to_event_id, relation) DO NOTHING",
                (event_id, target, "derived_from", "deterministic_check", trace_id, now),
            )
    # --- scopes: observed project/profile/knowledge_space only ---
    for scope_type, scope_id in (
        ("project", env.get("project_id")),
        ("profile", env.get("profile_id")),
        ("knowledge_space", env.get("knowledge_space_id")),
    ):
        if scope_id:
            conn.execute(
                "INSERT INTO zm_scopes (scope_type, scope_id, display_name, parent_scope, created_at) "
                "VALUES (?,?,?,?,?) "
                "ON CONFLICT(scope_type, scope_id) DO NOTHING",
                (scope_type, scope_id, None, None, now),
            )
    # --- active-key uniqueness + supersession ---
    if env.get("lifecycle_status") == "active" and trace_id:
        cur = conn.cursor()
        cur.execute(
            "SELECT event_id FROM zm_lifecycle WHERE active_key=? AND current_state='active' AND event_id<>?",
            (trace_id, event_id),
        )
        prior = cur.fetchone()
        if prior is not None:
            prior_id = prior["event_id"]
            conn.execute(
                "UPDATE zm_lifecycle SET current_state='superseded', superseded_by=? WHERE event_id=?",
                (event_id, prior_id),
            )
            conn.execute(
                "INSERT INTO zm_relations (from_event_id, to_event_id, relation, verifier, evidence_ref, created_at) "
                "VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(from_event_id, to_event_id, relation) DO NOTHING",
                (event_id, prior_id, "supersedes", "deterministic_check", trace_id, now),
            )
        conn.execute(
            "UPDATE zm_lifecycle SET active_key=? WHERE event_id=?",
            (trace_id, event_id),
        )
    elif env.get("lifecycle_status") == "superseded":
        sup = env.get("superseded_by")
        if sup:
            conn.execute(
                "UPDATE zm_lifecycle SET superseded_by=? WHERE event_id=?",
                (str(sup), event_id),
            )
    # --- artifact metadata registry (authorized references only) ---
    for art in env.get("artifact_refs", ()) or ():
        if not isinstance(art, dict):
            continue
        aid = art.get("artifact_id")
        if not aid:
            continue
        conn.execute(
            "INSERT INTO zm_artifacts (artifact_id, content_hash, kind, retention, origin_event_id, stored_path, created_at) "
            "VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(artifact_id) DO NOTHING",
            (aid, art.get("content_hash", ""), art.get("kind"), art.get("retention", "persistent"),
             event_id, None, now),
        )


def _seed_fts(conn, env: dict) -> None:
    """Index the APPROVED SANITIZED content in FTS5 (M2.5). No-op when FTS5 unavailable.

    Only the envelope's ``sanitized_content`` (already redacted by M1's fail-closed redactor)
    is indexed. Raw payloads never reach SQLite (M2.2 secret guarantee). The FTS table is a
    derived, rebuildable index — not the system of record.
    """
    if not _migrate_5.FTS5_AVAILABLE:
        return
    content = env.get("sanitized_content")
    if content is None:
        return
    text = content if isinstance(content, str) else json.dumps(content, sort_keys=True, ensure_ascii=False)
    conn.execute(
        "INSERT INTO zm_fts (event_id, content) VALUES (?, ?)",
        (env["event_id"], text),
    )


def _apply_tombstone(conn, env: dict) -> None:
    """Project a deletion event into tombstone + audit + lifecycle/FTS state (M2.6).

    Called within the same per-line transaction as the tombstone's ``NEW_EVENT`` insert. The
    tombstone envelope's ``deletion`` block supplies (only) explicit data: target_event_id,
    optional reason_code / approved_scope / verification_status. Nothing is invented.

    - Known target: mark target ``current_state='deleted'``, remove its FTS row (capability-guarded),
      insert ``zm_tombstones`` (status='applied') + ``zm_deletion_audit`` (prior state retained).
    - Unknown target: insert ``zm_tombstones`` (status='pending_unknown_target') + audit with a
      sanitized diagnostic code; retained, never invented. Applied later via ``_apply_pending_tombstones``.
    """
    del_block = env.get("deletion") or {}
    target = del_block.get("target_event_id")
    now = _now()
    deletion_id = env["event_id"]
    target_trace = None
    prior_state = None
    cur = conn.cursor()
    # trace_id lives on zm_meta; current_state on zm_lifecycle.
    cur.execute("SELECT trace_id FROM zm_meta WHERE event_id=?", (target,))
    mrow = cur.fetchone()
    cur.execute("SELECT current_state FROM zm_lifecycle WHERE event_id=?", (target,))
    lrow = cur.fetchone()
    exists = mrow is not None and lrow is not None
    if exists:
        target_trace = mrow["trace_id"]
        prior_state = lrow["current_state"]
    reason = del_block.get("reason_code")
    scope = del_block.get("approved_scope")
    scope_blob = json.dumps(scope, sort_keys=True, ensure_ascii=False) if isinstance(scope, (dict, list)) else (scope if isinstance(scope, str) else None)
    status = "applied" if exists else "pending_unknown_target"
    diagnostic = "" if exists else "target_not_yet_present"
    # Tombstone row (PK = deletion_id; idempotent by construction at ingest level).
    conn.execute(
        "INSERT INTO zm_tombstones "
        "(tombstone_id, target_event_id, target_trace_id, reason_code, approved_scope, "
        " verifier, evidence_ref, deletion_event_id, current_state, status, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(tombstone_id) DO UPDATE SET "
        "status=excluded.status, target_trace_id=excluded.target_trace_id",
        (deletion_id, target, target_trace, reason, scope_blob, "deterministic_check",
         env.get("trace_id"), deletion_id, "deleted", status, now),
    )
    # Audit row (append-only; prior state kept for provenance).
    conn.execute(
        "INSERT INTO zm_deletion_audit "
        "(tombstone_id, target_event_id, target_trace_id, action, prior_lifecycle_state, "
        " reason_code, approved_scope, deletion_event_id, verifier, evidence_ref, diagnostic_code, recorded_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (deletion_id, target, target_trace, "logical_delete", prior_state, reason, scope_blob,
         deletion_id, "deterministic_check", env.get("trace_id"), diagnostic, now),
    )
    if exists:
        # Transition the target's derived lifecycle state; zm_meta/provenance rows are retained.
        conn.execute(
            "UPDATE zm_lifecycle SET current_state='deleted' WHERE event_id=?",
            (target,),
        )
        # Remove the target's FTS row (derived, rebuildable; avoids orphan matches).
        if _migrate_5.FTS5_AVAILABLE:
            try:
                conn.execute("DELETE FROM zm_fts WHERE event_id=?", (target,))
            except sqlite3.OperationalError:
                pass


def _apply_pending_tombstones(conn, target_event_id: str) -> None:
    """Apply any 'pending_unknown_target' tombstones now that the target has arrived (M2.6).

    Deterministic and order-dependent: identical between incremental ingest and
    ``rebuild_from_jsonl`` because both replay JSONL lines in the same file order.
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT tombstone_id, target_trace_id, reason_code, approved_scope, "
        "deletion_event_id, evidence_ref FROM zm_tombstones "
        "WHERE target_event_id=? AND status='pending_unknown_target'",
        (target_event_id,),
    )
    for t in cur.fetchall():
        tomb_id = t["tombstone_id"]
        target_trace = t["target_trace_id"]
        reason = t["reason_code"]
        scope_blob = t["approved_scope"]
        del_id = t["deletion_event_id"]
        # Capture the now-present target's prior lifecycle state for the audit.
        lf = conn.cursor()
        lf.execute("SELECT current_state FROM zm_lifecycle WHERE event_id=?", (target_event_id,))
        lr = lf.fetchone()
        prior_state = lr["current_state"] if lr is not None else None
        conn.execute(
            "UPDATE zm_tombstones SET status='applied', target_trace_id=? WHERE tombstone_id=?",
            (target_trace, tomb_id),
        )
        conn.execute(
            "INSERT INTO zm_deletion_audit "
            "(tombstone_id, target_event_id, target_trace_id, action, prior_lifecycle_state, "
            " reason_code, approved_scope, deletion_event_id, verifier, evidence_ref, diagnostic_code, recorded_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (tomb_id, target_event_id, target_trace, "logical_delete", prior_state, reason, scope_blob,
             del_id, "deterministic_check", t["evidence_ref"], "", _now()),
        )
        conn.execute(
            "UPDATE zm_lifecycle SET current_state='deleted' WHERE event_id=?",
            (target_event_id,),
        )
        if _migrate_5.FTS5_AVAILABLE:
            try:
                conn.execute("DELETE FROM zm_fts WHERE event_id=?", (target_event_id,))
            except sqlite3.OperationalError:
                pass


def _classify_existing(conn, event_id: str, content_hash: str):
    """Return the outcome given current zm_meta state for the incoming record."""
    cur = conn.cursor()
    cur.execute(
        "SELECT event_id, content_hash FROM zm_meta WHERE event_id=? OR content_hash=?",
        (event_id, content_hash),
    )
    rows = cur.fetchall()
    stored_event = next((r for r in rows if r["event_id"] == event_id), None)
    stored_hash = next((r for r in rows if r["content_hash"] == content_hash), None)
    if stored_event is not None:
        if stored_event["content_hash"] == content_hash:
            return IngestionOutcome.DUPLICATE_EVENT_ID
        return IngestionOutcome.EVENT_ID_CONTENT_CONFLICT
    if stored_hash is not None:
        return IngestionOutcome.DUPLICATE_CONTENT_HASH
    return IngestionOutcome.NEW_EVENT


def _insert_log(conn, source_id: str, line_number: int, outcome: IngestionOutcome,
                event_id: Optional[str], content_hash: Optional[str],
                diagnostic_code: str) -> None:
    conn.execute(
        "INSERT INTO zm_ingest_log "
        "(jsonl_path, line_number, outcome, event_id, content_hash, diagnostic_code, recorded_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (source_id, line_number, outcome.value, event_id, content_hash, diagnostic_code, _now()),
    )


def _update_checkpoint(conn, source_id: str, line_number: int,
                       last_event_id: Optional[str], last_sequence: Optional[int],
                       prefix_hash: str) -> None:
    conn.execute(
        "INSERT INTO zm_ingest_checkpoint "
        "(jsonl_path, last_line_number, last_event_id, last_sequence, consumed_prefix_hash, updated_at) "
        "VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(jsonl_path) DO UPDATE SET "
        "last_line_number=excluded.last_line_number, "
        "last_event_id=excluded.last_event_id, "
        "last_sequence=excluded.last_sequence, "
        "consumed_prefix_hash=excluded.consumed_prefix_hash, "
        "updated_at=excluded.updated_at",
        (source_id, line_number, last_event_id, last_sequence, prefix_hash, _now()),
    )


def _get_checkpoint_row(conn, source_id: str):
    cur = conn.cursor()
    cur.execute(
        "SELECT last_line_number, consumed_prefix_hash FROM zm_ingest_checkpoint "
        "WHERE jsonl_path=?",
        (source_id,),
    )
    return cur.fetchone()


def _resolve_outcome(conn, env: dict):
    """Determine the outcome and, for committed outcomes, the INSERT/conflict SQL action."""
    return _classify_existing(conn, env["event_id"], env["sanitized_content_hash"])


def ingest_file(store, jsonl_path, source_id: Optional[str] = None) -> IngestionReport:
    """Ingest a canonical JSONL file into the derived SQLite layer.

    Returns an :class:`IngestionReport`. On ``transaction_failed`` or ``source_changed``
    ingestion halts (``report.stopped = True``) and the checkpoint is left at the prior
    line so a later explicit resume can re-attempt.
    """
    path = Path(jsonl_path)
    sid = source_id or _safe_source_id(path)
    report = IngestionReport(source_id=sid)
    conn = store._conn  # same internal package; raw connection for transactional control

    data = path.read_bytes()
    parts = data.split(b"\n")
    complete_count = len(parts) - 1

    # --- resume verification via consumed-prefix hash ---
    cp = _get_checkpoint_row(conn, sid)
    hasher = PrefixHasher()
    if cp is not None:
        last_line = int(cp["last_line_number"])
        stored_hash = cp["consumed_prefix_hash"]
        # Truncation below the checkpoint, or a consumed-prefix mismatch => stop.
        if last_line > complete_count:
            report.stopped = True
            report.add(IngestionOutcome.SOURCE_CHANGED)
            report.add_failure(IngestionFailure(sid, last_line, "source_changed", "truncation_below_checkpoint"))
            return report
        recomputed = _compute_prefix_hash(data, last_line)
        if recomputed != stored_hash:
            report.stopped = True
            report.add(IngestionOutcome.SOURCE_CHANGED)
            report.add_failure(IngestionFailure(sid, last_line, "source_changed", "consumed_prefix_mismatch"))
            return report
        # Seed the incremental hasher up to the committed prefix.
        for i in range(last_line):
            hasher.update(parts[i] + b"\n")
        start_line = last_line + 1
    else:
        start_line = 1

    for line_number, line_bytes, is_complete in _iter_jsonl_lines(path):
        if line_number < start_line:
            continue  # already accounted for in a prior run
        if not is_complete:
            # Trailing partial line (no newline): truncation guard. Do NOT ingest,
            # do NOT advance the checkpoint, and do NOT update the prefix hash, so a
            # later completed append is picked up on resume (plan §3/§5).
            report.add(IngestionOutcome.INVALID_RECORD)
            report.add_failure(IngestionFailure(sid, line_number, "invalid_record", "truncation"))
            continue

        try:
            parsed = json.loads(line_bytes.decode("utf-8"))
        except Exception:
            _commit_outcome(
                conn, sid, line_number, IngestionOutcome.INVALID_RECORD,
                None, None, "json_unparseable", hasher, line_bytes, report,
                env=None,
            )
            continue

        try:
            validate_envelope(parsed)
        except ValueError as exc:
            _commit_outcome(
                conn, sid, line_number, IngestionOutcome.INVALID_RECORD,
                None, None, _classify_validation_error(exc), hasher, line_bytes, report,
                env=None,
            )
            continue

        outcome = _resolve_outcome(conn, parsed)
        event_id = parsed["event_id"]
        content_hash = parsed["sanitized_content_hash"]
        last_seq = int(parsed.get("sequence", 0))

        # new_event performs an actual zm_meta INSERT; other committed outcomes only log.
        row = _project_row(parsed, sid) if outcome is IngestionOutcome.NEW_EVENT else None

        halted = _commit_outcome(
            conn, sid, line_number, outcome,
            event_id, content_hash, "", hasher, line_bytes, report,
            env=parsed, row=row, last_seq=last_seq,
        )
        if halted:
            # transaction_failed: checkpoint NOT advanced; stop so resume can retry.
            report.stopped = True
            break

    return report


def _commit_outcome(conn, source_id, line_number, outcome, event_id, content_hash,
                    diagnostic_code, hasher, line_bytes, report, env=None, row=None,
                    last_seq=None) -> bool:
    """Execute one atomic transaction for the line. Returns True if halted (txn failure).

    Checkpoint advances only after a committed outcome. ``transaction_failed`` rolls
    back and returns True (caller stops). ``source_changed`` is handled by the caller
    before this is reached.
    """
    try:
        conn.execute("BEGIN")
        if outcome is IngestionOutcome.NEW_EVENT and row is not None:
            placeholders = ", ".join("?" for _ in ZM_META_COLUMNS)
            conn.execute(
                f"INSERT INTO zm_meta ({', '.join(ZM_META_COLUMNS)}) "
                f"VALUES ({placeholders})",
                row,
            )
            _seed_lifecycle_and_provenance(conn, env)
            _project_relations_scopes(conn, env)
            _seed_fts(conn, env)
            # If this newly inserted event is itself the target of a previously-pending
            # tombstone, apply that tombstone now (deterministic, order-dependent).
            _apply_pending_tombstones(conn, env["event_id"])
        # A deletion event (lifecycle_status=='deleted' with a deletion block) projects
        # tombstone + audit + target lifecycle/FTS state within the same transaction.
        if env is not None and env.get("lifecycle_status") == "deleted" and env.get("deletion"):
            _apply_tombstone(conn, env)
        if outcome in _COMMITTED_OUTCOMES:
            _insert_log(conn, source_id, line_number, outcome, event_id, content_hash, diagnostic_code)
            # Advance the incremental prefix hash with this committed complete line.
            hasher.update(line_bytes)
            _update_checkpoint(
                conn, source_id, line_number,
                event_id if outcome is IngestionOutcome.NEW_EVENT else None,
                last_seq if outcome is IngestionOutcome.NEW_EVENT else None,
                hasher.hexdigest(),
            )
        _commit(conn)
    except Exception:
        try:
            _rollback(conn)
        except Exception:
            pass
        if outcome in _COMMITTED_OUTCOMES:
            # A genuine transaction failure on a normally-committed outcome: report in-memory.
            report.add(IngestionOutcome.TRANSACTION_FAILED)
            report.add_failure(IngestionFailure(source_id, line_number, "transaction_failed", "txn_commit_failed"))
            return True
        # Defensive: any other failure on a non-committed path also halts in-memory.
        report.add(IngestionOutcome.TRANSACTION_FAILED)
        report.add_failure(IngestionFailure(source_id, line_number, "transaction_failed", "txn_commit_failed"))
        return True
    report.add(outcome)
    # Plan §12: committed non-new outcomes are also collected in the in-memory
    # report (the committed zm_ingest_log row is the durable record; the report
    # mirrors it as a sanitized failure for testability). transaction_failed is
    # appended in the rollback branch above.
    if outcome in _COMMITTED_OUTCOMES and outcome is not IngestionOutcome.NEW_EVENT:
        code = diagnostic_code or _default_failure_code(outcome)
        report.add_failure(IngestionFailure(source_id, line_number, outcome.value, code))
    return False


def _default_failure_code(outcome: IngestionOutcome) -> str:
    return {
        IngestionOutcome.DUPLICATE_EVENT_ID: "duplicate_id",
        IngestionOutcome.DUPLICATE_CONTENT_HASH: "duplicate_hash",
        IngestionOutcome.EVENT_ID_CONTENT_CONFLICT: "conflict",
        IngestionOutcome.INVALID_RECORD: "invalid",
    }.get(outcome, outcome.value)


# ---- minimal read-only inspection helpers (no ranking/routing) ---------------

def get_trace(store, event_id: str) -> Optional[dict]:
    cur = store._conn.cursor()
    cur.execute(f"SELECT {', '.join(ZM_META_COLUMNS)} FROM zm_meta WHERE event_id=?", (event_id,))
    row = cur.fetchone()
    if row is None:
        return None
    return {c: row[c] for c in ZM_META_COLUMNS}


def count_metadata(store) -> int:
    cur = store._conn.cursor()
    cur.execute("SELECT COUNT(*) AS n FROM zm_meta")
    return int(cur.fetchone()["n"])


def get_checkpoint(store, source_id: str) -> Optional[dict]:
    cur = store._conn.cursor()
    cur.execute(
        "SELECT jsonl_path, last_line_number, last_event_id, last_sequence, "
        "consumed_prefix_hash, updated_at FROM zm_ingest_checkpoint WHERE jsonl_path=?",
        (source_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "jsonl_path": row["jsonl_path"],
        "last_line_number": int(row["last_line_number"]),
        "last_event_id": row["last_event_id"],
        "last_sequence": row["last_sequence"],
        "consumed_prefix_hash": row["consumed_prefix_hash"],
        "updated_at": row["updated_at"],
    }


def scan_sqlite_for_secrets(store, secret_corpus) -> list:
    """Return any secret-corpus token found in derived SQLite rows/logs (empty = clean).

    Covers zm_meta, zm_lifecycle, zm_provenance, and zm_ingest_log. Sanitized content is
    never stored in any of these tables (secrets cannot appear by construction).
    """
    found: list = []
    corpus = list(secret_corpus)
    if not corpus:
        return found
    conn = store._conn
    cur = conn.cursor()
    cur.execute(f"SELECT {', '.join(ZM_META_COLUMNS)} FROM zm_meta")
    for row in cur.fetchall():
        blob = " ".join("" if row[c] is None else str(row[c]) for c in ZM_META_COLUMNS)
        for token in corpus:
            if token and token in blob:
                found.append(token)
    cur.execute("SELECT event_id, current_state, superseded_by, active_key FROM zm_lifecycle")
    for row in cur.fetchall():
        blob = " ".join("" if row[c] is None else str(row[c]) for c in ("event_id", "current_state", "superseded_by", "active_key"))
        for token in corpus:
            if token and token in blob:
                found.append(token)
    cur.execute("SELECT event_id, verification_status, verifier, evidence_ref FROM zm_provenance")
    for row in cur.fetchall():
        blob = " ".join("" if row[c] is None else str(row[c]) for c in ("event_id", "verification_status", "verifier", "evidence_ref"))
        for token in corpus:
            if token and token in blob:
                found.append(token)
    cur.execute("SELECT jsonl_path, event_id, content_hash, diagnostic_code FROM zm_ingest_log")
    for row in cur.fetchall():
        blob = " ".join("" if row[c] is None else str(row[c]) for c in ("jsonl_path", "event_id", "content_hash", "diagnostic_code"))
        for token in corpus:
            if token and token in blob:
                found.append(token)
    # zm_relations / zm_scopes / zm_artifacts (derived, sanitized-content-free).
    cur.execute("SELECT from_event_id, to_event_id, relation, evidence_ref FROM zm_relations")
    for row in cur.fetchall():
        blob = " ".join("" if row[c] is None else str(row[c]) for c in ("from_event_id", "to_event_id", "relation", "evidence_ref"))
        for token in corpus:
            if token and token in blob:
                found.append(token)
    cur.execute("SELECT scope_type, scope_id, display_name, parent_scope FROM zm_scopes")
    for row in cur.fetchall():
        blob = " ".join("" if row[c] is None else str(row[c]) for c in ("scope_type", "scope_id", "display_name", "parent_scope"))
        for token in corpus:
            if token and token in blob:
                found.append(token)
    cur.execute("SELECT artifact_id, content_hash, kind, retention, origin_event_id, stored_path FROM zm_artifacts")
    for row in cur.fetchall():
        blob = " ".join("" if row[c] is None else str(row[c]) for c in ("artifact_id", "content_hash", "kind", "retention", "origin_event_id", "stored_path"))
        for token in corpus:
            if token and token in blob:
                found.append(token)
    # zm_fts (FTS5 over sanitized content) — must never carry raw secrets
    if _migrate_5.FTS5_AVAILABLE:
        try:
            cur.execute("SELECT event_id, content FROM zm_fts")
            for row in cur.fetchall():
                blob = " ".join("" if row[c] is None else str(row[c]) for c in ("event_id", "content"))
                for token in corpus:
                    if token and token in blob:
                        found.append(token)
        except sqlite3.OperationalError:
            pass
    # zm_tombstones (logical-deletion records) — must never carry raw secrets.
    cur.execute("SELECT tombstone_id, target_event_id, target_trace_id, reason_code, "
                "approved_scope, evidence_ref, deletion_event_id FROM zm_tombstones")
    for row in cur.fetchall():
        blob = " ".join("" if row[c] is None else str(row[c]) for c in
                        ("tombstone_id", "target_event_id", "target_trace_id", "reason_code",
                         "approved_scope", "evidence_ref", "deletion_event_id"))
        for token in corpus:
            if token and token in blob:
                found.append(token)
    # zm_deletion_audit (append-only deletion audit) — must never carry raw secrets.
    cur.execute("SELECT tombstone_id, target_event_id, target_trace_id, reason_code, "
                "approved_scope, deletion_event_id, evidence_ref, diagnostic_code FROM zm_deletion_audit")
    for row in cur.fetchall():
        blob = " ".join("" if row[c] is None else str(row[c]) for c in
                        ("tombstone_id", "target_event_id", "target_trace_id", "reason_code",
                         "approved_scope", "deletion_event_id", "evidence_ref", "diagnostic_code"))
        for token in corpus:
            if token and token in blob:
                found.append(token)
    return found


# ---- M2.3: lifecycle / provenance projection + rebuild ---------------------

DERIVED_TABLES = ("zm_meta", "zm_lifecycle", "zm_provenance", "zm_ingest_checkpoint", "zm_ingest_log",
                   "zm_relations", "zm_scopes", "zm_artifacts", "zm_tombstones", "zm_deletion_audit",
                   "zm_project_charters", "zm_requirements", "zm_decisions",
                   "zm_project_state", "zm_verifications", "zm_project_artifacts",
                   "zm_migrations")


def get_lifecycle(store, event_id: str) -> Optional[dict]:
    """Return the zm_lifecycle row for an event, or None."""
    cur = store._conn.cursor()
    cur.execute(
        "SELECT event_id, current_state, superseded_by, active_key, updated_at "
        "FROM zm_lifecycle WHERE event_id=?",
        (event_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "event_id": row["event_id"],
        "current_state": row["current_state"],
        "superseded_by": row["superseded_by"],
        "active_key": row["active_key"],
        "updated_at": row["updated_at"],
    }


def get_provenance(store, event_id: str) -> list:
    """Return all zm_provenance rows for an event (list of dicts)."""
    cur = store._conn.cursor()
    cur.execute(
        "SELECT id, event_id, verification_status, verifier, evidence_ref, recorded_at "
        "FROM zm_provenance WHERE event_id=?",
        (event_id,),
    )
    return [
        {
            "id": int(r["id"]),
            "event_id": r["event_id"],
            "verification_status": r["verification_status"],
            "verifier": r["verifier"],
            "evidence_ref": r["evidence_ref"],
            "recorded_at": r["recorded_at"],
        }
        for r in cur.fetchall()
    ]


def list_by_lifecycle_state(store, state: str) -> list:
    """Return event_ids whose derived current_state equals `state` (exact-key inspection)."""
    cur = store._conn.cursor()
    cur.execute("SELECT event_id FROM zm_lifecycle WHERE current_state=?", (state,))
    return [r["event_id"] for r in cur.fetchall()]


def rebuild_from_jsonl(store, jsonl_paths, source_ids=None, synchronous_full: bool = False) -> dict:
    """Rebuild the entire derived SQLite layer from canonical JSONL (M2.3).

    Drops all derived tables, recreates schema, then ingests every supplied file in order
    via ``ingest_file``. Deterministic and idempotent: identical input -> identical derived
    state. ``zm_migrations`` (schema version) is preserved. JSONL is never mutated.

    Returns ``{source_id: IngestionReport}`` for each file.
    """
    conn = store._conn
    if synchronous_full:
        try:
            conn.execute("PRAGMA synchronous=FULL")
        except Exception:
            pass
    # Drop every derived table (preserving zm_migrations + any future zm_artifacts).
    try:
        conn.execute("BEGIN")
        for table in DERIVED_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    # Recreate all derived tables for the current schema version.
    store.ensure_schema()
    # Ingest each file in order, reusing M2.2 per-line transactions/idempotence.
    reports: dict = {}
    if isinstance(jsonl_paths, (str, bytes)) or hasattr(jsonl_paths, "__fspath__"):
        jsonl_paths = [jsonl_paths]
    for idx, path in enumerate(jsonl_paths):
        sid = None
        if source_ids is not None and idx < len(source_ids):
            sid = source_ids[idx]
        reports[_safe_source_id(Path(path)) if sid is None else sid] = ingest_file(store, path, source_id=sid)
    return reports


def verify_rebuild_parity(store_a, store_b) -> bool:
    """True if two derived DBs hold identical key sets + states across all projection tables.

    Used by tests to assert rebuild parity vs incremental ingest. ``zm_ingest_checkpoint`` /
    ``zm_ingest_log`` history is intentionally excluded (not part of the parity contract).
    """
    conn_a, conn_b = store_a._conn, store_b._conn

    def snapshot(conn):
        meta = {
            (r["event_id"], r["trace_id"], r["lifecycle_status"], r["verification_status"])
            for r in conn.execute(
                "SELECT zm_meta.event_id, zm_meta.trace_id, zm_meta.lifecycle_status, "
                "zm_meta.verification_status FROM zm_meta"
            ).fetchall()
        }
        life = {
            (r["event_id"], r["current_state"], r["superseded_by"], r["active_key"])
            for r in conn.execute("SELECT event_id, current_state, superseded_by, active_key FROM zm_lifecycle").fetchall()
        }
        prov = {
            (r["event_id"], r["verification_status"], r["verifier"], r["evidence_ref"])
            for r in conn.execute(
                "SELECT event_id, verification_status, verifier, evidence_ref FROM zm_provenance"
            ).fetchall()
        }
        rel = {
            (r["from_event_id"], r["to_event_id"], r["relation"])
            for r in conn.execute("SELECT from_event_id, to_event_id, relation FROM zm_relations").fetchall()
        }
        scopes = {
            (r["scope_type"], r["scope_id"])
            for r in conn.execute("SELECT scope_type, scope_id FROM zm_scopes").fetchall()
        }
        arts = {
            (r["artifact_id"], r["content_hash"], r["kind"], r["retention"])
            for r in conn.execute("SELECT artifact_id, content_hash, kind, retention FROM zm_artifacts").fetchall()
        }
        tombs = {
            (r["tombstone_id"], r["target_event_id"], r["status"])
            for r in conn.execute("SELECT tombstone_id, target_event_id, status FROM zm_tombstones").fetchall()
        }
        audit = {
            (r["target_event_id"], r["action"])
            for r in conn.execute("SELECT target_event_id, action FROM zm_deletion_audit").fetchall()
        }
        fts = set()
        if _migrate_5.FTS5_AVAILABLE:
            try:
                fts = {
                    (r["event_id"], r["content"])
                    for r in conn.execute("SELECT event_id, content FROM zm_fts").fetchall()
                }
            except sqlite3.OperationalError:
                fts = set()
        return meta, life, prov, rel, scopes, arts, tombs, audit, fts

    a_meta, a_life, a_prov, a_rel, a_scopes, a_arts, a_tombs, a_audit, a_fts = snapshot(conn_a)
    b_meta, b_life, b_prov, b_rel, b_scopes, b_arts, b_tombs, b_audit, b_fts = snapshot(conn_b)
    return (
        a_meta == b_meta and a_life == b_life and a_prov == b_prov
        and a_rel == b_rel and a_scopes == b_scopes and a_arts == b_arts
        and a_tombs == b_tombs and a_audit == b_audit and a_fts == b_fts
    )


def get_relations(store, event_id: str) -> list:
    """Return all zm_relations edges where from_event_id == event_id (list of dicts)."""
    cur = store._conn.cursor()
    cur.execute(
        "SELECT id, from_event_id, to_event_id, relation, verifier, evidence_ref, created_at "
        "FROM zm_relations WHERE from_event_id=?",
        (event_id,),
    )
    return [
        {
            "id": int(r["id"]),
            "from_event_id": r["from_event_id"],
            "to_event_id": r["to_event_id"],
            "relation": r["relation"],
            "verifier": r["verifier"],
            "evidence_ref": r["evidence_ref"],
            "created_at": r["created_at"],
        }
        for r in cur.fetchall()
    ]


def get_scopes(store, scope_type: str) -> list:
    """Return all scope_ids observed for a given scope_type (list of str)."""
    cur = store._conn.cursor()
    cur.execute("SELECT scope_id FROM zm_scopes WHERE scope_type=?", (scope_type,))
    return [r["scope_id"] for r in cur.fetchall()]


def get_artifact(store, artifact_id: str) -> Optional[dict]:
    """Return the zm_artifacts metadata row for an artifact, or None."""
    cur = store._conn.cursor()
    cur.execute(
        "SELECT artifact_id, content_hash, kind, retention, origin_event_id, stored_path, created_at "
        "FROM zm_artifacts WHERE artifact_id=?",
        (artifact_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "artifact_id": row["artifact_id"],
        "content_hash": row["content_hash"],
        "kind": row["kind"],
        "retention": row["retention"],
        "origin_event_id": row["origin_event_id"],
        "stored_path": row["stored_path"],
        "created_at": row["created_at"],
    }


def list_active_for_key(store, active_key: str) -> list:
    """Return event_ids currently 'active' for a given active_key (exact-key inspection)."""
    cur = store._conn.cursor()
    cur.execute(
        "SELECT event_id FROM zm_lifecycle WHERE active_key=? AND current_state='active'",
        (active_key,),
    )
    return [r["event_id"] for r in cur.fetchall()]


def list_deleted(store, scope_type: Optional[str] = None, scope_id: Optional[str] = None) -> list:
    """Administrative helper: return event_ids whose derived lifecycle state is 'deleted'.

    This is the only sanctioned route to deleted records from normal inspection. Optionally
    filtered by an explicitly supplied scope (project_id/profile_id column on zm_meta).
    """
    cur = store._conn.cursor()
    sql = (
        "SELECT DISTINCT m.event_id FROM zm_meta m "
        "JOIN zm_lifecycle l ON m.event_id = l.event_id "
        "WHERE l.current_state='deleted'"
    )
    params: list = []
    if scope_type in ("project", "profile") and scope_id:
        column = "project_id" if scope_type == "project" else "profile_id"
        sql += f" AND m.{column}=?"
        params.append(scope_id)
    return [r["event_id"] for r in cur.execute(sql, params).fetchall()]


def get_tombstone(store, tombstone_id: str) -> Optional[dict]:
    """Administrative helper: return the zm_tombstones row for a deletion, or None."""
    cur = store._conn.cursor()
    cur.execute(
        "SELECT tombstone_id, target_event_id, target_trace_id, reason_code, approved_scope, "
        "verifier, evidence_ref, deletion_event_id, current_state, status, created_at "
        "FROM zm_tombstones WHERE tombstone_id=?",
        (tombstone_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "tombstone_id": row["tombstone_id"],
        "target_event_id": row["target_event_id"],
        "target_trace_id": row["target_trace_id"],
        "reason_code": row["reason_code"],
        "approved_scope": row["approved_scope"],
        "verifier": row["verifier"],
        "evidence_ref": row["evidence_ref"],
        "deletion_event_id": row["deletion_event_id"],
        "current_state": row["current_state"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


def get_deletion_audit(store, target_event_id: Optional[str] = None,
                       tombstone_id: Optional[str] = None) -> list:
    """Administrative helper: return zm_deletion_audit rows (by target and/or tombstone)."""
    cur = store._conn.cursor()
    clauses = []
    params: list = []
    if target_event_id:
        clauses.append("target_event_id=?")
        params.append(target_event_id)
    if tombstone_id:
        clauses.append("tombstone_id=?")
        params.append(tombstone_id)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    cur.execute(
        "SELECT audit_id, tombstone_id, target_event_id, target_trace_id, action, "
        "prior_lifecycle_state, reason_code, approved_scope, deletion_event_id, verifier, "
        "evidence_ref, diagnostic_code, recorded_at FROM zm_deletion_audit" + where,
        params,
    )
    return [
        {
            "audit_id": int(r["audit_id"]),
            "tombstone_id": r["tombstone_id"],
            "target_event_id": r["target_event_id"],
            "target_trace_id": r["target_trace_id"],
            "action": r["action"],
            "prior_lifecycle_state": r["prior_lifecycle_state"],
            "reason_code": r["reason_code"],
            "approved_scope": r["approved_scope"],
            "deletion_event_id": r["deletion_event_id"],
            "verifier": r["verifier"],
            "evidence_ref": r["evidence_ref"],
            "diagnostic_code": r["diagnostic_code"],
            "recorded_at": r["recorded_at"],
        }
        for r in cur.fetchall()
    ]
def search_fts(store, query: str, limit: int = 20) -> list:
    """Return FTS5 matches over SANITIZED content as [{event_id, snippet}] (no ranking trusted).

    Exact-key M2.5 inspection only: returns candidate event_ids. No relevance score is exposed or
    used for retrieval/ranking/routing (those are M3+). Returns [] when FTS5 is unavailable.
    """
    if not _migrate_5.FTS5_AVAILABLE:
        return []
    cur = store._conn.cursor()
    try:
        cur.execute(
            "SELECT event_id, snippet(zm_fts, 1, '[', ']', '...', 8) AS snip "
            "FROM zm_fts WHERE zm_fts MATCH ? ORDER BY rowid LIMIT ?",
            (query, limit),
        )
    except sqlite3.OperationalError:
        return []
    return [{"event_id": r["event_id"], "snippet": r["snip"]} for r in cur.fetchall()]


def find_related(store, event_id: str) -> list:
    """Return event_ids related to event_id via zm_relations (both directions, exact-key)."""
    cur = store._conn.cursor()
    out: list = []
    for r in cur.execute(
        "SELECT to_event_id AS eid FROM zm_relations WHERE from_event_id=?", (event_id,)
    ).fetchall():
        out.append(r["eid"])
    for r in cur.execute(
        "SELECT from_event_id AS eid FROM zm_relations WHERE to_event_id=?", (event_id,)
    ).fetchall():
        out.append(r["eid"])
    return out


def find_by_trace_id(store, trace_id: str) -> list:
    """Return zm_meta rows for a trace_id (exact-key inspection).

    Deleted records (zm_lifecycle.current_state='deleted') are excluded from this active helper;
    use list_deleted / get_tombstone / get_deletion_audit to inspect deleted state.
    """
    cur = store._conn.cursor()
    cols = ", ".join(ZM_META_COLUMNS)
    return [
        {c: row[c] for c in ZM_META_COLUMNS}
        for row in cur.execute(
            f"SELECT {cols} FROM zm_meta WHERE trace_id=? "
            f"AND event_id NOT IN (SELECT event_id FROM zm_lifecycle WHERE current_state='deleted')",
            (trace_id,),
        ).fetchall()
    ]


def list_events_in_scope(store, scope_type: str, scope_id: str) -> list:
    """Return event_ids observed in a scope (project_id/profile_id column; exact-key).

    Deleted records are excluded from this active helper.
    """
    column = {"project": "project_id", "profile": "profile_id"}.get(scope_type)
    if column is None:
        return []
    cur = store._conn.cursor()
    return [
        r["event_id"]
        for r in cur.execute(
            f"SELECT event_id FROM zm_meta WHERE {column}=? "
            f"AND event_id NOT IN (SELECT event_id FROM zm_lifecycle WHERE current_state='deleted')",
            (scope_id,),
        ).fetchall()
    ]


__all__ = [
    "IngestionOutcome",
    "IngestionFailure",
    "IngestionReport",
    "ingest_file",
    "rebuild_from_jsonl",
    "get_trace",
    "get_lifecycle",
    "get_provenance",
    "get_relations",
    "get_scopes",
    "get_artifact",
    "list_by_lifecycle_state",
    "list_deleted",
    "get_tombstone",
    "get_deletion_audit",
    "search_fts",
    "find_related",
    "find_by_trace_id",
    "list_events_in_scope",
    "count_metadata",
    "get_checkpoint",
    "verify_rebuild_parity",
    "scan_sqlite_for_secrets",
    "CURRENT_SCHEMA_VERSION",
]
