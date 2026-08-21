from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from scripts.verify_v123_evidence import EvidenceError, verify_manifest


def _run(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True, check=True).stdout.strip()


def _git_repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    _run(root, "init", "-q")
    _run(root, "config", "user.email", "test@example.invalid")
    _run(root, "config", "user.name", "fixture")
    (root / "source.txt").write_text("source\n", encoding="utf-8")
    _run(root, "add", "source.txt")
    _run(root, "commit", "-qm", "source")
    return root, _run(root, "rev-parse", "HEAD")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_bundle(root: Path, source_sha: str) -> Path:
    bundle = root / "docs/v1.2.3/evidence" / source_sha
    (bundle / "logs").mkdir(parents=True)
    (bundle / "hashes").mkdir()
    (bundle / "assets").mkdir()
    log = bundle / "logs/full.log"
    log.write_text("full suite\n", encoding="utf-8")
    asset = bundle / "assets/package.whl"
    asset.write_bytes(b"wheel-bytes")
    log_sha, asset_sha = _hash(log), _hash(asset)
    (bundle / "manifest.md").write_text("source-bound v1.2.3 evidence\n", encoding="utf-8")
    (bundle / "environment.txt").write_text("Linux; Python 3.11\n", encoding="utf-8")
    (bundle / "independent-audit.md").write_text("independent audit\n", encoding="utf-8")
    (bundle / "commands.txt").write_text(
        f"ARTIFACT_SOURCE_SHA={source_sha}\nCOMMAND=pytest\nRAW_LOG=logs/full.log\nRAW_LOG_SHA256={log_sha}\n",
        encoding="utf-8",
    )
    (bundle / "hashes/SHA256SUMS.txt").write_text(
        f"{log_sha}  ./logs/full.log\n{asset_sha}  ./assets/package.whl\n", encoding="utf-8"
    )
    manifest = {
        "package": "R-00",
        "source_sha": source_sha,
        "artifact_source_sha": source_sha,
        "evidence_commit_sha": "DERIVED_FROM_CURRENT_HEAD",
        "logs": [{"path": "logs/full.log", "sha256": log_sha}],
        "assets": [{"path": "assets/package.whl", "sha256": asset_sha}],
        "full_suite": {
            "command": "pytest -q",
            "source_sha": source_sha,
            "environment": "isolated",
            "exit_code": 0,
            "passed": 10,
            "failed": 0,
            "skipped": 0,
            "raw_log": "logs/full.log",
            "raw_log_sha256": log_sha,
        },
        "platforms": {
            "linux": {"status": "PASS", "evidence": "local"},
            "windows": {"status": "NOT_RUN", "evidence": "runner pending"},
            "macos": {"status": "NOT_RUN", "evidence": "runner pending"},
        },
    }
    manifest_path = bundle / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def _commit_bundle(root: Path) -> None:
    _run(root, "add", "docs/v1.2.3")
    _run(root, "commit", "-qm", "evidence")


def test_non_circular_source_ancestor_and_real_hashes_pass(tmp_path: Path) -> None:
    root, source = _git_repo(tmp_path)
    manifest = _write_bundle(root, source)
    _commit_bundle(root)
    result = verify_manifest(manifest)
    assert result["status"] == "PASS"
    assert result["artifact_source_sha"] == source
    assert result["current_head"] != source


def test_rejects_disallowed_source_delta(tmp_path: Path) -> None:
    root, source = _git_repo(tmp_path)
    _write_bundle(root, source)
    (root / "source.py").write_text("not evidence\n", encoding="utf-8")
    _run(root, "add", ".")
    _run(root, "commit", "-qm", "bad delta")
    with __import__("pytest").raises(EvidenceError, match="evidence_delta_path_not_allowed"):
        verify_manifest(root / "docs/v1.2.3/evidence" / source / "manifest.json")


def test_rejects_modified_bytes_and_duplicate_checksum_paths(tmp_path: Path) -> None:
    root, source = _git_repo(tmp_path)
    manifest = _write_bundle(root, source)
    _commit_bundle(root)
    sums = manifest.parent / "hashes/SHA256SUMS.txt"
    sums.write_text(sums.read_text() + sums.read_text().splitlines()[0] + "\n", encoding="utf-8")
    _run(root, "add", "docs/v1.2.3")
    _run(root, "commit", "-qm", "bad sums")
    with __import__("pytest").raises(EvidenceError, match="sha256sum_duplicate_path"):
        verify_manifest(manifest)


def test_rejects_dirty_checkout(tmp_path: Path) -> None:
    root, source = _git_repo(tmp_path)
    manifest = _write_bundle(root, source)
    _commit_bundle(root)
    (root / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    with __import__("pytest").raises(EvidenceError, match="working_tree_not_clean"):
        verify_manifest(manifest)
