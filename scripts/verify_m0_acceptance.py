"""Criterion-specific M0 acceptance verification.

This is not a product test and does not verify later milestones. It checks only
that the M0 architecture, contract/policy, and benchmark artifacts contain the
requirements named by the master specification.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def verify_m0_a() -> None:
    architecture = read("ARCHITECTURE.md")
    required = (
        "Hermes Agent",
        "Zero-Mem sidecar",
        "SQLite with WAL and FTS5",
        "JSONL",
        "Obsidian Knowledge Workspace",
        "observation-only",
        "Verified tool output",
        "Cross-profile writes require explicit authorization",
        "never persisted",
        "rebuildable",
    )
    architecture_folded = architecture.casefold()
    missing = [marker for marker in required if marker.casefold() not in architecture_folded]
    assert not missing, f"M0-A missing architecture decisions: {missing}"


def verify_m0_b() -> None:
    contracts = read("config/schemas/m0-contracts.yaml")
    security = read("config/policies/m0-security-retention.yaml")
    required_contracts = (
        "trace_taxonomy:",
        "provenance_required:",
        "lifecycle_states:",
        "sensitivity_classes:",
        "never_store:",
        "redaction_patterns:",
        "retention_classes:",
        "conflict_policy:",
    )
    missing_contracts = [marker for marker in required_contracts if marker not in contracts]
    assert not missing_contracts, f"M0-B missing contract sections: {missing_contracts}"
    required_security = (
        "redact_before_persist: true",
        "secret_policy: reject_or_redact_at_capture_boundary",
        "redaction_audit: record_event_without_original_value",
        "retention:",
        "delete_workflow:",
        "write_back:",
    )
    missing_security = [marker for marker in required_security if marker not in security]
    assert not missing_security, f"M0-B missing security/policy sections: {missing_security}"


def verify_m0_c() -> None:
    benchmark = json.loads(read("benchmark-plan.json"))
    scenarios = benchmark["scenarios"]
    assert 30 <= len(scenarios) <= 50, len(scenarios)
    assert len({scenario["id"] for scenario in scenarios}) == len(scenarios)
    classes = {scenario["class"] for scenario in scenarios}
    assert {"task_continuation", "stale_state"} <= classes
    assert benchmark["gold_fields"] == [
        "expected_route",
        "expected_trace_ids",
        "expected_state",
        "allowed_scopes",
    ]
    assert "Recall@K" in benchmark["evaluation"]
    assert "stale_state_rate" in benchmark["evaluation"]


def main() -> None:
    verify_m0_a()
    print("M0-A: PASS")
    verify_m0_b()
    print("M0-B: PASS")
    verify_m0_c()
    print("M0-C: PASS")


if __name__ == "__main__":
    main()

# Assertions used by this criterion-specific verifier:
# - M0-A: every required architecture decision marker must be present.
# - M0-B: every required schema/policy section and boundary policy must be present.
# - M0-C: there must be 30-50 unique scenarios, including task continuation and
#   stale-state classes, plus the specified gold fields and evaluation metrics.
