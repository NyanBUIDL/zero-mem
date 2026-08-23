"""V132-05 — Machine-state consolidation validator (D-02 Option A).

Policy: ``project-state.yaml`` is the SINGLE machine state for current and
future status. ``implementation-plan.json`` is a FROZEN HISTORICAL RECORD:
it must carry a machine-readable header declaring that role, and must not be
consumed as live state by tooling.

This script fail-closes when:
  * project-state.yaml is missing / unparseable / lacks required keys;
  * implementation-plan.json lacks the frozen-record header
    (``"record_role": "historical_record_frozen"`` +
    ``"superseded_by": "project-state.yaml"``);
  * either file was modified after the other's freeze marker in a way that
    breaks the single-source contract (header check above is the gate).

Usage:  .venv-v124/bin/python scripts/check_machine_state.py [--repo ROOT]
Exit 0 = consistent; exit 1 = violation (message on stderr, no secrets).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REQUIRED_PS_KEYS = ("schema_version", "project", "status")
FROZEN_ROLE = "historical_record_frozen"
SUPERSEDED_BY = "project-state.yaml"


def check_machine_state(repo_root: Path) -> list[str]:
    """Return a list of violations (empty == consistent)."""
    problems: list[str] = []
    ps_path = repo_root / "project-state.yaml"
    ip_path = repo_root / "implementation-plan.json"

    if not ps_path.is_file():
        problems.append(f"missing machine state file: {ps_path.name}")
        return problems
    try:
        import yaml
        with ps_path.open("r", encoding="utf-8") as fh:
            state = yaml.safe_load(fh)
    except Exception as exc:  # noqa: BLE001 - fail closed on any parse issue
        problems.append(f"project-state.yaml unparseable: {type(exc).__name__}")
        return problems
    if not isinstance(state, dict):
        problems.append("project-state.yaml is not a mapping")
        return problems
    for key in REQUIRED_PS_KEYS:
        if key not in state:
            problems.append(f"project-state.yaml missing required key: {key}")

    if not ip_path.is_file():
        # Absence is acceptable under D-02 A only once retired explicitly;
        # today it must exist as the historical record.
        problems.append("implementation-plan.json missing (historical record)")
        return problems
    try:
        with ip_path.open("r", encoding="utf-8") as fh:
            plan = json.load(fh)
    except Exception as exc:  # noqa: BLE001
        problems.append(f"implementation-plan.json unparseable: {type(exc).__name__}")
        return problems
    if not isinstance(plan, dict):
        problems.append("implementation-plan.json is not an object")
        return problems
    if plan.get("record_role") != FROZEN_ROLE:
        problems.append(
            "implementation-plan.json lacks frozen-record header "
            f'(expected record_role="{FROZEN_ROLE}")'
        )
    if plan.get("superseded_by") != SUPERSEDED_BY:
        problems.append(
            'implementation-plan.json lacks superseded_by="project-state.yaml"'
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args(argv)
    violations = check_machine_state(Path(args.repo))
    if violations:
        for v in violations:
            print(f"MACHINE_STATE_VIOLATION: {v}", file=sys.stderr)
        return 1
    print("machine state OK: project-state.yaml is the single source; "
          "implementation-plan.json is a frozen historical record")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
