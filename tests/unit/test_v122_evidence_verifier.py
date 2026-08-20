from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "scripts" / "verify_v122_evidence.py"
SOURCE_SHA = "a" * 40


def _write_fixture(root: Path, *, collection_errors: int = 0) -> Path:
    (root / "logs").mkdir(parents=True)
    (root / "assets").mkdir()
    (root / "logs" / "pytest.log").write_text("1 tests collected in 0.01s\n", encoding="utf-8")
    (root / "assets" / "package.whl").write_bytes(b"fixture-wheel")
    entries = []
    for relative in ("logs/pytest.log", "assets/package.whl"):
        entries.append({"path": relative, "sha256": hashlib.sha256((root / relative).read_bytes()).hexdigest()})
    manifest = {
        "package": "V122-00",
        "source_sha": SOURCE_SHA,
        "suite_status": "PASS",
        "collection": {"status": "PASS", "errors": collection_errors, "collected": 1, "collection_log": "logs/pytest.log"},
        "logs": [entries[0]],
        "assets": [entries[1]],
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    (root / "manifest.md").write_text(
        "\n".join(
            [
                "Parent SHA: fixture-parent",
                "Branch/ref: fixture-ref",
                "Baseline timestamp: fixture-time",
                "Evidence refresh timestamp: fixture-time",
                "Operator: fixture",
                "OS/architecture: Linux x86_64",
                "Python/SQLite/FTS5: fixture",
                "Build command: NOT APPLICABLE",
                "Collection count: 1",
                "Focused test count: 1 passed",
                "Changed files: fixture",
                "Reviewer: fixture",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "environment.txt").write_text("fixture environment\n", encoding="utf-8")
    (root / "sbom.txt").write_text("fixture sbom\n", encoding="utf-8")
    (root / "independent-audit.md").write_text("fixture audit\n", encoding="utf-8")
    log_hash = hashlib.sha256((root / "logs/pytest.log").read_bytes()).hexdigest()
    asset_hash = hashlib.sha256((root / "assets/package.whl").read_bytes()).hexdigest()
    (root / "commands.txt").write_text(
        "source SHA "
        + SOURCE_SHA
        + "\n## 1. Fixture command\n- Command: fixture\n- Working directory: <fixture>\n- Environment: fixture\n- Result: exit 0\n- Elapsed: 0.01s\n- Raw log: `logs/pytest.log`\n- Raw log SHA-256: `"
        + log_hash
        + "`\n",
        encoding="utf-8",
    )
    (root / "hashes").mkdir()
    (root / "hashes/SHA256SUMS.txt").write_text(
        f"{asset_hash} ./assets/package.whl\n{log_hash} ./logs/pytest.log\n",
        encoding="utf-8",
    )
    return path


def _run(manifest: Path, source_sha: str = SOURCE_SHA) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(manifest), "--source-sha", source_sha],
        text=True,
        capture_output=True,
        check=False,
    )


def test_valid_manifest_is_accepted(tmp_path: Path) -> None:
    result = _run(_write_fixture(tmp_path))
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "PASS"


def test_source_log_and_asset_integrity_fail_closed(tmp_path: Path) -> None:
    manifest = _write_fixture(tmp_path)
    payload = json.loads(manifest.read_text())

    payload["source_sha"] = "b" * 40
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    assert "source_sha_mismatch" in _run(manifest).stdout

    payload["source_sha"] = SOURCE_SHA
    payload["logs"][0]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    assert "raw_log_hash_mismatch" in _run(manifest).stdout

    payload["logs"][0]["sha256"] = hashlib.sha256((tmp_path / "logs/pytest.log").read_bytes()).hexdigest()
    payload["assets"][0]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    assert "asset_hash_mismatch" in _run(manifest).stdout


def test_missing_evidence_and_collection_failure_are_rejected(tmp_path: Path) -> None:
    manifest = _write_fixture(tmp_path, collection_errors=1)
    result = _run(manifest)
    assert result.returncode == 1
    assert "collection_not_pass" in result.stdout

    payload = json.loads(manifest.read_text())
    payload["collection"] = {"status": "PASS", "errors": False}
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    assert "collection_count_missing_or_invalid" in _run(manifest).stdout

    payload["collection"] = {"status": "PASS", "errors": 0.0, "collected": 1, "collection_log": "logs/pytest.log"}
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    assert "collection_not_pass" in _run(manifest).stdout

    payload["collection"] = {"status": "PASS", "errors": 0}
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    assert "collection_count_missing_or_invalid" in _run(manifest).stdout

    payload["collection"] = {"status": "PASS", "errors": 0, "collected": 2, "collection_log": "logs/pytest.log"}
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    assert "collection_count_mismatch" in _run(manifest).stdout

    payload["collection"] = {"status": "PASS", "errors": 0, "collected": 1, "collection_log": "logs/pytest.log"}
    payload["logs"] = []
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    assert "raw_log_missing" in _run(manifest).stdout


def test_command_linkage_and_hash_paths_fail_closed(tmp_path: Path) -> None:
    manifest = _write_fixture(tmp_path)
    commands = manifest.parent / "commands.txt"
    original = commands.read_text()
    commands.write_text(original.replace("- Raw log SHA-256:", "- Raw log SHA-256:", 1).replace("`logs/pytest.log`", "`logs/missing.log`", 1))
    assert "command_log_hash_not_bound" in _run(manifest).stdout

    commands.write_text(original)
    sums = manifest.parent / "hashes/SHA256SUMS.txt"
    sums.write_text(sums.read_text().replace("./assets/package.whl", "/etc/passwd"), encoding="utf-8")
    assert "evidence_hash_path_unsafe" in _run(manifest).stdout
