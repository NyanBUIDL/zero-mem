"""One-time, idempotent migration of the retired ``zero_mem.notes`` store into corpus sources.

The old store kept ``<data root>/data/notes/notes-v1.jsonl`` (``{chunk_id, text, source, ts}`` per line) beside a
derived FTS index. Both were a second source of truth outside authorization. ``zero-mem import-notes`` replays
every record through ``Memory.add`` so each one is validated, secret-scanned, authorized, registered and projected
like any other write; running it twice is a no-op (a note's id is the hash of its text). The old file is never
modified or deleted (AGENTS.md: raw traces are kept).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .memory import Memory
from .memory_results import IngestReport, WriteResult, build_ingest_report

NOTES_STREAM_RELATIVE = Path("data/notes/notes-v1.jsonl")
IMPORT_SOURCE = "notes-v1"
MAX_LINE_BYTES = 1024 * 1024
MAX_LINES = 5_000_000


class NotesImportError(RuntimeError):
    """Sanitized import failure (``code`` is stable)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def default_notes_path(memory: Memory) -> Path:
    return memory.layout.data_root / NOTES_STREAM_RELATIVE


def import_notes(
    memory: Memory,
    path: Optional[Path] = None,
    *,
    memory_type: str = "fact",
    scope: Optional[str] = None,
    project_id: Optional[str] = None,
) -> IngestReport:
    """Replay the old notes file as ``memory_type`` sources of ``memory``'s profile. Idempotent."""
    source = Path(path) if path is not None else default_notes_path(memory)
    if source.is_symlink() or not source.is_file():
        raise NotesImportError("notes_file_missing", f"no notes file at {source.name}: nothing to import")
    results: list[WriteResult] = []
    skipped: list[dict] = []
    try:
        handle = open(source, "rb")
    except OSError:
        raise NotesImportError("notes_file_unreadable", "cannot read the notes file") from None
    with handle:
        for number, raw in enumerate(handle, start=1):
            if number > MAX_LINES:
                skipped.append({"name": f"line {number}", "reason": "max_lines_reached"})
                break
            if not raw.strip():
                continue
            if len(raw) > MAX_LINE_BYTES:
                skipped.append({"name": f"line {number}", "reason": "line_too_long"})
                continue
            try:
                record = json.loads(raw)
            except ValueError:
                skipped.append({"name": f"line {number}", "reason": "malformed_json"})
                continue
            text = record.get("text") if isinstance(record, dict) else None
            if not isinstance(text, str) or not text.strip():
                skipped.append({"name": f"line {number}", "reason": "no_text"})
                continue
            provenance: dict = {"imported_from": IMPORT_SOURCE}
            for key, field in (("notes_source", "source"), ("notes_chunk_id", "chunk_id")):
                value = record.get(field)
                if isinstance(value, str) and value:
                    provenance[key] = value[:200]
            ts = record.get("ts")
            if isinstance(ts, int) and not isinstance(ts, bool):
                provenance["notes_ts"] = ts
            result = memory.add(text, memory_type, scope=scope, project_id=project_id, provenance=provenance)
            if result.status == "denied":
                # one authorization decision covers the whole import: stop instead of auditing every note
                return build_ingest_report("denied", result.reason, [], skipped)
            if result.status == "invalid" and result.reason in {"invalid_memory_type", "invalid_scope", "project_id_required",
                                                                "invalid_project_id", "project_id_not_allowed",
                                                                "devlog_requires_project_scope"}:
                return build_ingest_report("invalid", result.reason, [], skipped)
            results.append(WriteResult(**{**result.__dict__, "name": f"line {number}"}))
    return build_ingest_report(None, None, results, skipped)


__all__ = ["NOTES_STREAM_RELATIVE", "NotesImportError", "default_notes_path", "import_notes"]
