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

This module must not be used for lifecycle/provenance/relation/scope projection,
FTS5 indexing, retrieval, ranking, routing, MCP, Obsidian, or context injection
(those are later milestones / out of scope).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from .migrations import CURRENT_SCHEMA_VERSION
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
    """Return any secret-corpus token found in derived SQLite rows/logs (empty = clean)."""
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
    cur.execute("SELECT jsonl_path, event_id, content_hash, diagnostic_code FROM zm_ingest_log")
    for row in cur.fetchall():
        blob = " ".join("" if row[c] is None else str(row[c]) for c in ("jsonl_path", "event_id", "content_hash", "diagnostic_code"))
        for token in corpus:
            if token and token in blob:
                found.append(token)
    return found


__all__ = [
    "IngestionOutcome",
    "IngestionFailure",
    "IngestionReport",
    "ingest_file",
    "get_trace",
    "count_metadata",
    "get_checkpoint",
    "scan_sqlite_for_secrets",
    "CURRENT_SCHEMA_VERSION",
]
