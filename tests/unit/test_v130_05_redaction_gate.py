"""V130-05 — Redaction gate tests for the real-corpus pipeline (D2).

Proves the export gate is fail-closed: a known secret in ANY source line blocks
the whole export; a clean corpus passes; fixtures stay outside git tracking.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from benchmarks.v130_real_corpus_pipeline import export_corpus, scan_line_secret


def _write_lines(path: Path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def test_known_secret_line_is_detected():
    """(a) REAL secret (raw, unredacted) must be detected — fail-closed kept."""
    line = '{"sanitized_content": {"text": "key sk-abcdef123456"}}'
    assert scan_line_secret(line)
    # even wrapped in prose
    assert scan_line_secret('{"t": "token ghp_AB...7890 leaked"}')


def test_redacted_marker_line_passes_scan():
    """(b) v1.3.1 WP-6: already-redacted marker carries NO live secret.

    Intentional behavior change: previously the substring "sk-" inside the
    redaction marker tripped the gate and blocked corpus export.
    """
    line = '{"sanitized_content": {"text": "key «redacted:sk-live1234» ok"}}'
    assert not scan_line_secret(line)


def test_secret_outside_marker_still_detected():
    """Redacted marker present but a LIVE secret elsewhere on the line."""
    line = ('{"sanitized_content": {"text": "old «redacted:sk-old» ", '
            '"note": "live sk-newsecret99"}}')
    assert scan_line_secret(line)


def test_clean_line_passes_scan():
    line = '{"sanitized_content": {"text": "benchmark labeled deployment result"}}'
    assert not scan_line_secret(line)


def test_gate_blocks_export_on_secret(tmp_path):
    src = tmp_path / "src.jsonl"
    out = tmp_path / "out" / "real-corpus.jsonl"
    _write_lines(src, [
        '{"event_id": "ok-1", "sanitized_content": {"text": "clean content"}}',
        '{"event_id": "bad-1", "sanitized_content": {"text": "token ghp_ABCDEF1234567890 leaked"}}',
        '{"event_id": "ok-2", "sanitized_content": {"text": "more clean content"}}',
    ])
    res = export_corpus(src, out, limit=100)
    assert res["status"] == "BLOCKED_SECRET_DETECTED"
    # fail closed: NO partial output may survive
    assert not out.exists()
    assert not out.with_suffix(".tmp").exists()


def test_clean_corpus_exports_ok(tmp_path):
    src = tmp_path / "src.jsonl"
    out = tmp_path / "out" / "real-corpus.jsonl"
    lines = [f'{{"event_id": "ok-{i}", "sanitized_content": {{"text": "clean note {i}"}}}}'
             for i in range(5)]
    _write_lines(src, lines)
    res = export_corpus(src, out, limit=100)
    assert res["status"] == "OK"
    assert res["written"] == 5
    assert res["sha256"]
    # deterministic: same input -> same digest
    res2 = export_corpus(src, tmp_path / "out2" / "real-corpus.jsonl", limit=100)
    assert res2["sha256"] == res["sha256"]


def test_real_archive_fixture_outside_git_tracking(tmp_path):
    """D2: the actual exported fixture from the archive lives under dev-data and
    is NOT tracked by git (release-artifact safety)."""
    repo = Path(__file__).resolve().parents[2]
    archive = Path("/home/lenovo/Hermes Workspace/_archive/zero-mem-v1.2.2-work/"
                   "artifacts/evidence/v1.2.2/af01e494a29410b11dd6d5c4c78275e6e08604df/"
                   "benchmark-run-1/corpus.jsonl")
    if not archive.exists():
        # archive unavailable on this machine: skip rather than fail (environment)
        import pytest
        pytest.skip("archive source not available")
    devdata_out = repo.parent / "zero-mem-dev-data" / "benchmarks" / "v130" / "real-corpus.jsonl"
    res = export_corpus(archive, devdata_out, limit=5000)
    assert res["status"] == "OK"
    tracked = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "--error-unmatch",
         "zero-mem-dev-data/benchmarks/v130/real-corpus.jsonl"],
        capture_output=True, text=True)
    assert tracked.returncode != 0  # NOT tracked
    status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                            capture_output=True, text=True).stdout
    assert "real-corpus.jsonl" not in status  # and not even visible as untracked in-repo
