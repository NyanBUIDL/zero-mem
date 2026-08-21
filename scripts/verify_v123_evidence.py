#!/usr/bin/env python3
"""Fail-closed verifier for Zero-Mem v1.2.3 source-bound evidence.

The product source revision is immutable evidence input. Evidence may be added by
an additive descendant commit, but the verifier never requires a manifest to
contain the SHA of the commit that contains that manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

SHA1 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PLATFORM_STATUSES = {"PASS", "FAIL", "NOT_RUN", "UNSUPPORTED", "PREREQUISITE_UNAVAILABLE"}
ALLOWED_DELTA = (
    "docs/v1.2.3/evidence/",
    "docs/v1.2.3/work-packages/",
    "docs/v1.2.3/release-control-system/",
    "docs/v1.2.3/BASELINE-AUDIT.md",
    "docs/v1.2.3/TASK-BOARD.md",
    "docs/v1.2.3/FINAL-CHECKLIST-RECONCILIATION.md",
    "project-state.yaml",
    "docs/v1.2.3/README.md",
    "docs/v1.2.3/RELEASE-NOTES.md",
)


class EvidenceError(ValueError):
    pass


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise EvidenceError("git_unavailable") from exc
    if result.returncode != 0:
        raise EvidenceError("git_command_failed")
    return result.stdout.strip()


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise EvidenceError("evidence_file_unreadable") from exc
    return digest.hexdigest()


def _safe_relative(value: Any, reason: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise EvidenceError(reason)
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise EvidenceError(reason)
    return path.as_posix()


def _inside(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise EvidenceError("evidence_path_escapes_root") from exc
    if (root / relative).is_symlink():
        raise EvidenceError("evidence_symlink")
    return candidate


def _verify_entry(root: Path, entry: Any, kind: str) -> tuple[str, str]:
    if not isinstance(entry, dict):
        raise EvidenceError(f"{kind}_entry_invalid")
    relative = _safe_relative(entry.get("path"), f"{kind}_path_invalid")
    expected = entry.get("sha256")
    if not isinstance(expected, str) or not SHA256.fullmatch(expected):
        raise EvidenceError(f"{kind}_hash_invalid")
    path = _inside(root, relative)
    if not path.is_file() or _hash(path) != expected:
        raise EvidenceError(f"{kind}_hash_mismatch")
    return relative, expected


def _verify_sha256sums(root: Path) -> None:
    sums = root / "hashes" / "SHA256SUMS.txt"
    if sums.is_symlink() or not sums.is_file():
        raise EvidenceError("sha256sums_missing")
    seen: set[str] = set()
    for line in sums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or not SHA256.fullmatch(parts[0]):
            raise EvidenceError("sha256sum_entry_invalid")
        relative = parts[1].removeprefix("./")
        relative = _safe_relative(relative, "sha256sum_path_invalid")
        if relative in seen:
            raise EvidenceError("sha256sum_duplicate_path")
        seen.add(relative)
        path = _inside(root, relative)
        if not path.is_file() or _hash(path) != parts[0]:
            raise EvidenceError("sha256sum_mismatch")


def _verify_delta(repository_root: Path, artifact_source_sha: str, current_head: str) -> None:
    try:
        subprocess.run(
            ["git", "-C", str(repository_root), "merge-base", "--is-ancestor", artifact_source_sha, current_head],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise EvidenceError("artifact_source_not_ancestor") from exc
    changed = _git(repository_root, "diff", "--name-only", f"{artifact_source_sha}..{current_head}").splitlines()
    for raw in changed:
        path = _safe_relative(raw, "delta_path_invalid")
        if not any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in ALLOWED_DELTA):
            raise EvidenceError("evidence_delta_path_not_allowed")


def _verify_schema(payload: dict[str, Any], root: Path, source_sha: str) -> None:
    for relative in ("manifest.md", "commands.txt", "environment.txt", "independent-audit.md", "hashes/SHA256SUMS.txt"):
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise EvidenceError("evidence_schema_file_missing")
    if payload.get("artifact_source_sha") != source_sha or payload.get("source_sha") != source_sha:
        raise EvidenceError("artifact_source_sha_mismatch")
    if payload.get("evidence_commit_sha") not in (None, "DERIVED_FROM_CURRENT_HEAD"):
        raise EvidenceError("evidence_commit_sha_self_reference")
    commands = (root / "commands.txt").read_text(encoding="utf-8")
    if f"ARTIFACT_SOURCE_SHA={source_sha}" not in commands:
        raise EvidenceError("command_source_sha_missing")
    suite = payload.get("full_suite")
    if not isinstance(suite, dict):
        raise EvidenceError("full_suite_schema_missing")
    for field in ("command", "source_sha", "environment", "exit_code", "passed", "failed", "skipped", "raw_log", "raw_log_sha256"):
        if field not in suite:
            raise EvidenceError("full_suite_schema_missing")
    if suite["source_sha"] != source_sha or suite["exit_code"] != 0 or suite["failed"] != 0:
        raise EvidenceError("full_suite_not_pass")
    if not isinstance(suite["raw_log"], str) or not SHA256.fullmatch(str(suite["raw_log_sha256"])):
        raise EvidenceError("full_suite_log_invalid")
    log_path = _inside(root, _safe_relative(suite["raw_log"], "full_suite_log_invalid"))
    if _hash(log_path) != suite["raw_log_sha256"]:
        raise EvidenceError("full_suite_log_hash_mismatch")
    platforms = payload.get("platforms")
    if not isinstance(platforms, dict) or set(platforms) != {"linux", "windows", "macos"}:
        raise EvidenceError("platform_schema_missing")
    for value in platforms.values():
        if not isinstance(value, dict) or value.get("status") not in PLATFORM_STATUSES:
            raise EvidenceError("platform_status_invalid")
        if value.get("status") == "PASS" and not value.get("evidence"):
            raise EvidenceError("platform_pass_evidence_missing")


def verify_manifest(manifest_path: Path, *, repository_root: Path | None = None) -> dict[str, str]:
    if repository_root is None:
        repository_root = Path(_git(manifest_path.parent, "rev-parse", "--show-toplevel"))
    repository_root = repository_root.resolve()
    manifest_path = manifest_path.resolve()
    try:
        manifest_path.relative_to(repository_root)
    except ValueError as exc:
        raise EvidenceError("manifest_outside_repository") from exc
    if manifest_path.name != "manifest.json" or manifest_path.is_symlink() or not manifest_path.is_file():
        raise EvidenceError("manifest_missing")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError("manifest_invalid") from exc
    if not isinstance(payload, dict):
        raise EvidenceError("manifest_invalid")
    source_sha = payload.get("artifact_source_sha")
    if not isinstance(source_sha, str) or not SHA1.fullmatch(source_sha):
        raise EvidenceError("artifact_source_sha_invalid")
    current_head = _git(repository_root, "rev-parse", "HEAD")
    if not SHA1.fullmatch(current_head):
        raise EvidenceError("current_head_invalid")
    status = _git(repository_root, "status", "--porcelain", "--untracked-files=all")
    if status:
        raise EvidenceError("working_tree_not_clean")
    _verify_delta(repository_root, source_sha, current_head)
    logs = payload.get("logs")
    assets = payload.get("assets")
    if not isinstance(logs, list) or not logs:
        raise EvidenceError("raw_log_missing")
    if not isinstance(assets, list) or not assets:
        raise EvidenceError("asset_hash_missing")
    log_paths = {_verify_entry(manifest_path.parent, entry, "raw_log")[0] for entry in logs}
    asset_paths = {_verify_entry(manifest_path.parent, entry, "asset")[0] for entry in assets}
    _verify_sha256sums(manifest_path.parent)
    _verify_schema(payload, manifest_path.parent, source_sha)
    if not log_paths.issubset(log_paths | asset_paths):
        raise EvidenceError("log_set_invalid")
    return {"status": "PASS", "artifact_source_sha": source_sha, "current_head": current_head}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(verify_manifest(args.manifest), sort_keys=True))
    except EvidenceError as exc:
        print(json.dumps({"status": "REJECTED", "reason": str(exc)}, sort_keys=True))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
