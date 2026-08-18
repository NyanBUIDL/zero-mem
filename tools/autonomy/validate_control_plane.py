"""Deterministic validation for the durable v1.1 control plane."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_HEAD = "78c4bb46b88b8ce9987c6882b24201e08b82a7f0"
EXPECTED_SPEC = "85b66cbfd380a756eba9266ec8021b331dfee232ab95bd030f287766ba628b9a"
EXPECTED_BRANCH = "NyanBUIDL-Zero-mem"


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def main() -> int:
    manifest = json.loads((ROOT / "artifacts/tasks/task-manifest.json").read_text())
    assert len(manifest["tasks"]) == 23
    assert {task["id"] for task in manifest["tasks"]} == {"WP-00", *{f"WP-{i:02d}" for i in range(1, 23)}}
    assert git("rev-parse", "--abbrev-ref", "HEAD") == EXPECTED_BRANCH
    assert git("cat-file", "-e", EXPECTED_HEAD + "^{commit}") == ""
    assert hashlib.sha256((ROOT / "Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx").read_bytes()).hexdigest() == EXPECTED_SPEC
    assert (ROOT / "artifacts/evidence/V11-DURABLE-RESTART-EVIDENCE.md").exists()
    assert (ROOT / "artifacts/evidence/V11-DURABLE-RESTART-RESULT.json").exists()
    assert (ROOT / "artifacts/handoffs/V11-DURABLE-RESTART-HANDOFF.md").exists()
    assert git("diff", "--check") == ""
    print("control_plane=PASS")
    print("tasks=23")
    print("branch=" + EXPECTED_BRANCH)
    print("baseline_head=" + EXPECTED_HEAD)
    print("canonical_sha256=" + EXPECTED_SPEC)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
