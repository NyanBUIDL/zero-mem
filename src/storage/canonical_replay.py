"""Strict framing helpers for full replay of canonical JSONL streams.

This module is deliberately limited to replay preflight. Per-line M2 ingestion
has a different, tolerant invalid-record contract and does not use this helper.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable, List, Union


class CanonicalReplayError(Exception):
    """Sanitized typed failure for a blocked canonical replay.

    The public message contains only a fixed code and safe line number. It never
    includes raw input, exception text, secrets, or a full filesystem path.
    """

    def __init__(self, code: str, line_number: int | None = None) -> None:
        self.code = code
        self.line_number = line_number
        suffix = "" if line_number is None else f":line_{line_number}"
        super().__init__(f"canonical_replay_blocked:{code}{suffix}")


def load_strict_jsonl(
    jsonl_paths: Union[Path, str, Iterable[Union[Path, str]]],
    validate_record: Callable[[dict], None] | None = None,
) -> List[dict]:
    """Read a stable, fully validated JSONL snapshot for a full replay.

    Blank lines remain ignorable, matching the existing replay behavior. Every
    other line must be complete UTF-8 JSON with a dictionary top level. A final
    unterminated segment is treated as truncation when its JSON is incomplete;
    a complete final JSON object remains valid for compatibility with existing
    M4/M5 fixture writers.
    ``validate_record`` may reject malformed authoritative domain records while
    allowing valid unrelated domains to remain skippable.
    """
    if isinstance(jsonl_paths, (str, Path)):
        paths = [Path(jsonl_paths)]
    else:
        paths = [Path(path) for path in jsonl_paths]

    records: List[dict] = []
    for path in paths:
        try:
            data = path.read_bytes()
        except OSError:
            raise CanonicalReplayError("source_unreadable") from None
        for line_number, raw_line in enumerate(data.split(b"\n"), start=1):
            if not raw_line.strip():
                continue
            try:
                line = raw_line.decode("utf-8")
            except UnicodeDecodeError:
                raise CanonicalReplayError("invalid_utf8", line_number) from None
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                is_final_unterminated = (
                    line_number == data.count(b"\n") + 1 and not data.endswith(b"\n")
                )
                code = "truncated_line" if is_final_unterminated else "malformed_json"
                raise CanonicalReplayError(code, line_number) from None
            if not isinstance(record, dict):
                raise CanonicalReplayError("invalid_top_level", line_number)
            if validate_record is not None:
                validate_record(record)
            records.append(record)
    return records


__all__ = ["CanonicalReplayError", "load_strict_jsonl"]
