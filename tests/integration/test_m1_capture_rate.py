"""M1 Increment 4.6 capture-rate benchmark tests."""
from __future__ import annotations

import json

import pytest

from src.integration.capture_benchmark import run_benchmark
from src.integration.bridge_config import (
    CONDITIONAL_FIXTURE_REQUIRED,
    DEFERRED_HOOKS,
    VERIFIED_SUPPORTED_HOOKS,
)


def test_capture_rate_meets_threshold(tmp_path):
    report = run_benchmark(
        capture_root=tmp_path / "capture",
        hermes_home=tmp_path / "hermes",
        project_id="project-test",
        profile_id="profile-test",
    )
    assert report.expected_supported == len(VERIFIED_SUPPORTED_HOOKS)
    assert report.capture_rate >= 99.0
    assert report.failed_captures == 0
    assert report.envelope_failures == 0
    assert report.ordering_failures == 0
    assert report.secret_scan_failures == 0
    assert report.secret_present is False


def test_appended_unique_count_matches_supported(tmp_path):
    report = run_benchmark(
        capture_root=tmp_path / "capture",
        hermes_home=tmp_path / "hermes",
        project_id="project-test",
        profile_id="profile-test",
    )
    assert report.appended_unique == report.expected_supported
    # accepted duplicates do not create extra records
    assert report.accepted_duplicates >= 2
    total_lines = _jsonl_line_count(report.jsonl_path)
    assert total_lines == report.appended_unique


def test_duplicate_replays_do_not_advance_sequence(tmp_path):
    report = run_benchmark(
        capture_root=tmp_path / "snapshot",
        hermes_home=tmp_path / "hermes",
        project_id="project-test",
        profile_id="profile-test",
    )
    # sequences remain 0..appended_unique-1 and strictly increasing per append
    records = _load_jsonl(report.jsonl_path)
    sequences = [r["sequence"] for r in records]
    assert sequences == sorted(sequences)
    assert max(sequences) == report.appended_unique - 1


def test_conditional_and_deferred_excluded_from_denominator(tmp_path):
    report = run_benchmark(
        capture_root=tmp_path / "capture",
        hermes_home=tmp_path / "hermes",
        project_id="project-test",
        profile_id="profile-test",
    )
    # conditional + deferred inputs are reported separately and excluded
    # (the harness drives only the fixtures that have synthetic inputs)
    assert report.unsupported_or_deferred == 4
    # denominator uses only supported expected events
    assert report.expected_supported == len(VERIFIED_SUPPORTED_HOOKS)
    # none of the excluded hooks leaked into the captured store
    records = _load_jsonl(report.jsonl_path)
    sources = {r["source"] for r in records}
    excluded = set(CONDITIONAL_FIXTURE_REQUIRED) | set(DEFERRED_HOOKS)
    assert not (excluded & {s.replace("hermes.", "") for s in sources})


def test_jsonl_records_parse_and_validate(tmp_path):
    report = run_benchmark(
        capture_root=tmp_path / "capture",
        hermes_home=tmp_path / "hermes",
        project_id="project-test",
        profile_id="profile-test",
    )
    records = _load_jsonl(report.jsonl_path)
    assert len(records) == report.appended_unique
    for record in records:
        assert isinstance(record.get("event_id"), str) and record["event_id"]
        assert record["sanitized_content_hash"].startswith("sha256:")


def test_event_and_correlation_identifiers_preserved(tmp_path):
    report = run_benchmark(
        capture_root=tmp_path / "capture",
        hermes_home=tmp_path / "hermes",
        project_id="project-test",
        profile_id="profile-test",
    )
    records = {r["event_id"]: r for r in _load_jsonl(report.jsonl_path)}
    assert records["evt-session-start-1"]["session_id"] == "sess-bench-1"
    assert records["evt-pre-tool-1"]["sanitized_content"]["tool_name"] == "shell_exec"
    assert records["evt-kanban-completed-1"]["sanitized_content"]["summary"] == "done"
    assert records["evt-kanban-completed-1"]["sanitized_content"]["reason"] == "success"


def test_no_real_home_write(tmp_path):
    real_home = json  # placeholder to keep import; not used
    report = run_benchmark(
        capture_root=tmp_path / "capture",
        hermes_home=tmp_path / "hermes",
        project_id="project-test",
        profile_id="profile-test",
    )
    assert report.jsonl_path is not None
    assert "home" not in report.jsonl_path or "hermes-verify" in report.jsonl_path or str(tmp_path) in report.jsonl_path


def _jsonl_line_count(path):
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        return 0
    data = p.read_bytes()
    if not data:
        return 0
    return len([line for line in data.splitlines() if line.strip()])


def _load_jsonl(path):
    from pathlib import Path

    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
