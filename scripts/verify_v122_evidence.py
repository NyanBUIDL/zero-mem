#!/usr/bin/env python3
"""Fail-closed verifier for V122-00 evidence manifests.

The manifest is package evidence, not product state. It binds every assertion to
an exact source SHA and to the bytes of recorded logs/assets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHA1 = re.compile(r"^[0-9a-f]{40}$")


class EvidenceError(ValueError):
    """A manifest or referenced evidence file is invalid."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except (OSError, ValueError) as exc:
        raise EvidenceError("evidence_file_unreadable") from exc
    return digest.hexdigest()


def _required_string(value: Any, reason: str) -> str:
    if not isinstance(value, str) or not value:
        raise EvidenceError(reason)
    return value


def _verify_file_entry(root: Path, entry: Any, kind: str) -> None:
    if not isinstance(entry, dict):
        raise EvidenceError(f"{kind}_entry_invalid")
    relative = _required_string(entry.get("path"), f"{kind}_path_missing")
    expected = entry.get("sha256")
    if not isinstance(expected, str) or not _SHA256.fullmatch(expected):
        raise EvidenceError(f"{kind}_hash_missing_or_invalid")
    candidate_raw = root / relative
    if candidate_raw.is_symlink():
        raise EvidenceError(f"{kind}_symlink")
    candidate = candidate_raw.resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise EvidenceError(f"{kind}_path_escapes_root") from exc
    if not candidate.is_file():
        raise EvidenceError(f"{kind}_missing")
    if _sha256(candidate) != expected:
        raise EvidenceError(f"{kind}_hash_mismatch")


def _verify_evidence_schema(root: Path, *, source_sha: str, logs: list[Any]) -> None:
    required = (
        "manifest.md",
        "commands.txt",
        "environment.txt",
        "sbom.txt",
        "independent-audit.md",
        "hashes/SHA256SUMS.txt",
    )
    for relative in required:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise EvidenceError("evidence_schema_file_missing")

    manifest_text = (root / "manifest.md").read_text(encoding="utf-8")
    required_markers = (
        "Parent SHA:",
        "Branch/ref:",
        "Baseline timestamp:",
        "Evidence refresh timestamp:",
        "Operator:",
        "OS/architecture:",
        "Python/SQLite/FTS5:",
        "Build command:",
        "Collection count:",
        "Focused test count:",
        "Changed files:",
        "Reviewer:",
    )
    if any(marker not in manifest_text for marker in required_markers):
        raise EvidenceError("evidence_manifest_metadata_missing")

    commands_text = (root / "commands.txt").read_text(encoding="utf-8")
    if f"source SHA {source_sha}" not in commands_text:
        raise EvidenceError("command_source_sha_missing")
    required_command_fields = (
        "- Command:",
        "- Working directory:",
        "- Environment:",
        "- Result:",
        "- Elapsed:",
        "- Raw log:",
        "- Raw log SHA-256:",
    )
    command_sections = [section for section in commands_text.split("\n## ")[1:] if section.strip()]
    if not command_sections or any(
        any(field not in section for field in required_command_fields)
        for section in command_sections
    ):
        raise EvidenceError("command_record_field_missing")

    declared_logs = {
        entry["path"]: entry["sha256"]
        for entry in logs
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    referenced = re.findall(r"- Raw log: `([^`]+)`", commands_text)
    referenced_hashes = re.findall(r"- Raw log SHA-256: `([0-9a-f]{64})`", commands_text)
    if not referenced or len(referenced) != len(referenced_hashes):
        raise EvidenceError("command_log_linkage_missing")
    for relative, recorded_hash in zip(referenced, referenced_hashes):
        if declared_logs.get(relative) != recorded_hash:
            raise EvidenceError("command_log_hash_not_bound")
    for line in (root / "hashes/SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or not _SHA256.fullmatch(parts[0]):
            raise EvidenceError("evidence_hash_record_invalid")
        relative = parts[1]
        if relative.startswith(("/", "\\")) or ".." in Path(relative).parts or "\\" in relative:
            raise EvidenceError("evidence_hash_path_unsafe")


def verify_manifest(manifest_path: Path, *, expected_source_sha: str) -> dict[str, Any]:
    """Verify a V122-00 manifest and all byte-bound evidence references."""
    if not _SHA1.fullmatch(expected_source_sha):
        raise EvidenceError("expected_source_sha_invalid")
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise EvidenceError("manifest_missing")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError("manifest_invalid") from exc
    if not isinstance(payload, dict):
        raise EvidenceError("manifest_invalid")
    if payload.get("source_sha") != expected_source_sha:
        raise EvidenceError("source_sha_mismatch")
    logs = payload.get("logs")
    assets = payload.get("assets")
    if not isinstance(logs, list) or not logs:
        raise EvidenceError("raw_log_missing")
    if not isinstance(assets, list) or not assets:
        raise EvidenceError("asset_hash_missing")
    for entry in logs:
        _verify_file_entry(manifest_path.parent, entry, "raw_log")
    for entry in assets:
        _verify_file_entry(manifest_path.parent, entry, "asset")
    _verify_evidence_schema(manifest_path.parent, source_sha=expected_source_sha, logs=logs)

    collection = payload.get("collection")
    if not isinstance(collection, dict):
        raise EvidenceError("collection_result_missing")
    collection_count = collection.get("collected")
    if type(collection_count) is not int or collection_count < 0:
        raise EvidenceError("collection_count_missing_or_invalid")
    collection_errors = collection.get("errors")
    if type(collection_errors) is not int or collection_errors != 0:
        raise EvidenceError("collection_not_pass")
    if collection.get("status") != "PASS":
        raise EvidenceError("collection_not_pass")
    if payload.get("suite_status") == "PASS" and collection_errors != 0:
        raise EvidenceError("collection_failure_claimed_as_full_pass")
    collection_log = collection.get("collection_log")
    if not isinstance(collection_log, str) or not collection_log:
        raise EvidenceError("collection_log_missing")
    declared_logs = {
        entry["path"]: entry["sha256"]
        for entry in logs
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    if collection_log not in declared_logs:
        raise EvidenceError("collection_log_not_bound")
    collection_text = (manifest_path.parent / collection_log).read_text(encoding="utf-8")
    matches = re.findall(r"(?m)^(\d+) tests collected(?: in|$)", collection_text)
    if len(matches) != 1 or int(matches[0]) != collection_count:
        raise EvidenceError("collection_count_mismatch")
    if re.search(r"(?m)^\d+ errors during collection$", collection_text):
        raise EvidenceError("collection_errors_inconsistent")
    return {"status": "PASS", "source_sha": expected_source_sha}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args(argv)
    try:
        result = verify_manifest(args.manifest, expected_source_sha=args.source_sha)
    except EvidenceError as exc:
        print(json.dumps({"status": "REJECTED", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
