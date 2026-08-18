from __future__ import annotations

from pathlib import Path

from zero_mem.status import STATUS_SCHEMA_VERSION, collect_status


def test_status_is_versioned_content_free_and_constant_size(tmp_path: Path) -> None:
    canonical = tmp_path / "events.jsonl"
    derived = tmp_path / "memory.sqlite3"
    canonical.write_text('{"secret":"[REDACTED]"}\n')
    status = collect_status(canonical=canonical, derived=derived)
    assert status.schema_version == STATUS_SCHEMA_VERSION
    assert status.readiness == "NOT_READY"
    assert status.last_error_code == "DERIVED_MISSING"
    assert "secret" not in str(status.to_dict())
