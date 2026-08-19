"""Read-only recovery diagnosis over canonical JSONL and derived ``zm_*`` state."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import quote

from src.storage.coordination import coordinated, read_regular_bytes, regular_identity


class FailureClass(str, Enum):
    CANONICAL_MISSING = "CANONICAL_MISSING"
    CANONICAL_MALFORMED = "CANONICAL_MALFORMED"
    DERIVED_MISSING = "DERIVED_MISSING"
    DERIVED_CORRUPT = "DERIVED_CORRUPT"
    SCHEMA_INCOMPATIBLE = "SCHEMA_INCOMPATIBLE"
    DERIVED_UNAVAILABLE = "DERIVED_UNAVAILABLE"
    DERIVED_STALE = "DERIVED_STALE"
    READY = "READY"


@dataclass(frozen=True)
class RecoveryDiagnosis:
    status: FailureClass
    canonical_records: int
    derived_records: int | None
    canonical_bytes: int
    message: str


def _read_canonical(path: Path) -> tuple[list[dict[str, Any]], int] | None:
    try:
        raw = read_regular_bytes(path)
        if raw and not raw.endswith(b"\n"):
            return None
        records: list[dict[str, Any]] = []
        expected_sequence = 0
        for line in raw.splitlines():
            value: Any = json.loads(line.decode("utf-8"))
            event_id = value.get("event_id") if isinstance(value, dict) else None
            if not isinstance(value, dict) or not isinstance(event_id, str) or not event_id:
                return None
            sequence = value.get("sequence", expected_sequence)
            if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0 or sequence != expected_sequence:
                return None
            value["sequence"] = sequence
            records.append(value)
            expected_sequence += 1
        return records, len(raw)
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _checkpoint_for(conn: sqlite3.Connection, canonical_path: Path, source_id: str) -> tuple[int, str | None, int | None, str | None] | None:
    """Return checkpoint evidence for this exact canonical source, if present."""
    rows = conn.execute(
        "SELECT jsonl_path, last_line_number, last_event_id, last_sequence, consumed_prefix_hash "
        "FROM zm_ingest_checkpoint"
    ).fetchall()
    candidates = [row for row in rows if str(row[0]) == source_id]
    if not candidates:
        return None
    row = max(candidates, key=lambda item: int(item[1]))
    if (
        not isinstance(row[1], int) or isinstance(row[1], bool)
        or row[1] < 0
        or (row[2] is not None and not isinstance(row[2], str))
        or (row[3] is not None and (not isinstance(row[3], int) or isinstance(row[3], bool)))
        or (row[4] is not None and not isinstance(row[4], str))
    ):
        raise ValueError("checkpoint fields malformed")
    return row[1], row[2], row[3], row[4]


def _prefix_hash(path: Path, line_count: int) -> str:
    raw = read_regular_bytes(path)
    lines = raw.splitlines(keepends=True)
    if line_count < 0 or line_count > len(lines):
        raise ValueError("checkpoint line count outside canonical stream")
    return hashlib.sha256(b"".join(lines[:line_count])).hexdigest()


def _diagnose_impl(*, canonical_path: Path, derived_path: Path, source_id: str | None = None) -> RecoveryDiagnosis:
    """Inspect canonical/derived state without modifying either file."""
    if not canonical_path.is_file() or canonical_path.is_symlink():
        return RecoveryDiagnosis(FailureClass.CANONICAL_MISSING, 0, None, 0, "canonical stream missing")
    canonical = _read_canonical(canonical_path)
    if canonical is None:
        try:
            size = canonical_path.stat().st_size
        except OSError:
            size = 0
        return RecoveryDiagnosis(FailureClass.CANONICAL_MALFORMED, 0, None, size, "canonical stream is malformed")
    records, raw_size = canonical
    if not derived_path.is_file() or derived_path.is_symlink():
        return RecoveryDiagnosis(FailureClass.DERIVED_MISSING, len(records), None, raw_size, "derived store missing; rebuild from canonical")
    try:
        if regular_identity(canonical_path) == regular_identity(derived_path):
            return RecoveryDiagnosis(FailureClass.DERIVED_UNAVAILABLE, len(records), None, raw_size, "canonical and derived objects alias")
    except OSError:
        return RecoveryDiagnosis(FailureClass.DERIVED_UNAVAILABLE, len(records), None, raw_size, "derived store unavailable")

    try:
        derived_identity_before_open = regular_identity(derived_path)
    except OSError:
        return RecoveryDiagnosis(FailureClass.DERIVED_UNAVAILABLE, len(records), None, raw_size, "derived store unavailable")
    conn: sqlite3.Connection | None = None
    try:
        opened_conn = sqlite3.connect(f"file:{quote(derived_path.as_posix(), safe='/')}?mode=ro", uri=True)
        conn = opened_conn
        try:
            if regular_identity(derived_path) != derived_identity_before_open:
                opened_conn.close()
                conn = None
                return RecoveryDiagnosis(FailureClass.DERIVED_UNAVAILABLE, len(records), None, raw_size, "derived identity changed during open")
        except OSError:
            opened_conn.close()
            conn = None
            return RecoveryDiagnosis(FailureClass.DERIVED_UNAVAILABLE, len(records), None, raw_size, "derived store unavailable")
        conn.execute("PRAGMA query_only=ON")
        tables = {
            str(row[0]) for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                "('zm_meta','zm_ingest_checkpoint','zm_migrations')"
            )
        }
        if not {"zm_meta", "zm_ingest_checkpoint", "zm_migrations"}.issubset(tables):
            return RecoveryDiagnosis(FailureClass.SCHEMA_INCOMPATIBLE, len(records), None, raw_size, "derived schema incompatible")
        required_columns = {
            "zm_meta": {"event_id", "sequence"},
            "zm_ingest_checkpoint": {
                "jsonl_path", "last_line_number", "last_event_id",
                "last_sequence", "consumed_prefix_hash", "updated_at",
            },
            "zm_migrations": {"version", "applied_at", "note"},
        }
        for table_name, columns in required_columns.items():
            actual = {
                str(row[1]) for row in conn.execute(
                    f"PRAGMA table_info({table_name})"
                )
            }
            if not columns.issubset(actual):
                return RecoveryDiagnosis(
                    FailureClass.SCHEMA_INCOMPATIBLE,
                    len(records), None, raw_size,
                    "derived schema incompatible",
                )
        derived_records = int(conn.execute("SELECT COUNT(*) FROM zm_meta").fetchone()[0])
        checkpoint = _checkpoint_for(conn, canonical_path, source_id or str(canonical_path.resolve()))
        if checkpoint is None:
            return RecoveryDiagnosis(FailureClass.DERIVED_STALE, len(records), derived_records, raw_size, "derived checkpoint missing")
        last_line, last_event_id, last_sequence, consumed_prefix_hash = checkpoint
        final_sequence = int(records[-1].get("sequence", len(records) - 1)) if records else -1
        if last_line < 0 or last_line > len(records) or (last_sequence is not None and (last_sequence < 0 or last_sequence > final_sequence)):
            return RecoveryDiagnosis(FailureClass.DERIVED_CORRUPT, len(records), derived_records, raw_size, "derived checkpoint is inconsistent")
        committed_event_id = last_event_id
        committed_sequence = last_sequence
        if last_line and committed_event_id is None:
            try:
                latest = conn.execute(
                    "SELECT event_id FROM zm_ingest_log "
                    "WHERE jsonl_path=? AND line_number<=? AND outcome='new_event' "
                    "ORDER BY line_number DESC LIMIT 1",
                    (source_id or str(canonical_path.resolve()), last_line),
                ).fetchone()
            except sqlite3.Error:
                latest = None
            if latest is not None and isinstance(latest[0], str):
                committed_event_id = latest[0]
                committed_record = next((record for record in records[:last_line] if record.get("event_id") == committed_event_id), None)
                committed_sequence = int(committed_record["sequence"]) if committed_record is not None else None
        if last_line == 0 and (committed_event_id is not None or committed_sequence is not None):
            return RecoveryDiagnosis(FailureClass.DERIVED_CORRUPT, len(records), derived_records, raw_size, "empty checkpoint carries record identity")
        if last_line and committed_event_id is not None and committed_event_id not in {record.get("event_id") for record in records[:last_line]}:
            return RecoveryDiagnosis(FailureClass.DERIVED_CORRUPT, len(records), derived_records, raw_size, "derived checkpoint event identity is inconsistent")
        if last_line and committed_sequence is not None and not any(
            record.get("event_id") == committed_event_id and int(record.get("sequence", -1)) == committed_sequence
            for record in records[:last_line]
        ):
            return RecoveryDiagnosis(FailureClass.DERIVED_CORRUPT, len(records), derived_records, raw_size, "derived checkpoint sequence is inconsistent")
        if consumed_prefix_hash != _prefix_hash(canonical_path, last_line):
            return RecoveryDiagnosis(FailureClass.DERIVED_CORRUPT, len(records), derived_records, raw_size, "canonical prefix hash does not match checkpoint")
        if last_line < len(records) or (records and committed_sequence is not None and committed_sequence < final_sequence and committed_event_id == records[-1].get("event_id")):
            return RecoveryDiagnosis(FailureClass.DERIVED_STALE, len(records), derived_records, raw_size, "derived state lags canonical stream")
        hashes = [record.get("sanitized_content_hash") for record in records]
        if records and all(isinstance(content_hash, str) for content_hash in hashes):
            expected_logical_count = len(set(hashes))
        else:
            expected_logical_count = len(records)
        if derived_records != expected_logical_count:
            return RecoveryDiagnosis(FailureClass.DERIVED_STALE, len(records), derived_records, raw_size, "derived metadata does not match canonical logical state")
        derived_rows = []
        for row in conn.execute(
            "SELECT event_id, sequence FROM zm_meta "
            "ORDER BY sequence ASC, event_id ASC"
        ):
            if (
                not isinstance(row[0], str)
                or not row[0]
                or not isinstance(row[1], int)
                or isinstance(row[1], bool)
            ):
                return RecoveryDiagnosis(
                    FailureClass.DERIVED_CORRUPT,
                    len(records), derived_records, raw_size,
                    "derived event identity fields are malformed",
                )
            derived_rows.append((row[0], row[1]))
        expected_rows = []
        seen_hashes: set[str] = set()
        use_hash_dedupe = bool(records) and all(isinstance(record.get("sanitized_content_hash"), str) for record in records)
        for record in records:
            content_hash = record.get("sanitized_content_hash")
            if use_hash_dedupe and content_hash in seen_hashes:
                continue
            if use_hash_dedupe:
                assert isinstance(content_hash, str)
                seen_hashes.add(content_hash)
            expected_rows.append((record["event_id"], int(record["sequence"])))
        if derived_rows != expected_rows:
            return RecoveryDiagnosis(
                FailureClass.DERIVED_CORRUPT,
                len(records), derived_records, raw_size,
                "derived event identity does not match canonical stream",
            )
        return RecoveryDiagnosis(FailureClass.READY, len(records), derived_records, raw_size, "canonical and derived state are available")
    except (sqlite3.DatabaseError, ValueError, TypeError):
        return RecoveryDiagnosis(FailureClass.DERIVED_CORRUPT, len(records), None, raw_size, "derived store is corrupt or unreadable")
    except OSError:
        return RecoveryDiagnosis(FailureClass.DERIVED_UNAVAILABLE, len(records), None, raw_size, "derived store unavailable")
    finally:
        if conn is not None:
            conn.close()


def diagnose(*, canonical_path: Path, derived_path: Path, source_id: str | None = None, _coordination_held: bool = False) -> RecoveryDiagnosis:
    """Inspect state under the shared derived/canonical coordination domain."""
    if _coordination_held:
        return _diagnose_impl(canonical_path=canonical_path, derived_path=derived_path, source_id=source_id)
    try:
        with coordinated(canonical_path, derived_path, mode="shared", timeout=5.0):
            return _diagnose_impl(canonical_path=canonical_path, derived_path=derived_path, source_id=source_id)
    except (OSError, TimeoutError, ValueError):
        return RecoveryDiagnosis(FailureClass.DERIVED_UNAVAILABLE, 0, None, 0, "coordination unavailable")


__all__ = ["FailureClass", "RecoveryDiagnosis", "diagnose"]
