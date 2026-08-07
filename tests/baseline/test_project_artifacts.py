"""Baseline contract tests for planning artifacts.

These tests intentionally verify only the planning/state contract. They must not
be interpreted as implementation acceptance tests for any future milestone.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_master_spec_and_derived_agents_exist() -> None:
    assert (ROOT / "Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx").is_file()
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "SQLite + JSONL" in agents
    assert "Redact or reject secrets before persistence" in agents


def test_implementation_plan_is_machine_readable_and_gated() -> None:
    plan = json.loads((ROOT / "implementation-plan.json").read_text(encoding="utf-8"))
    assert plan["status"] == "in_progress"
    assert plan["current_milestone_status"] == "m3_in_progress"
    assert plan["milestones"][0]["verification"]["status"] == "fully_verified"
    assert [milestone["id"] for milestone in plan["milestones"]] == [
        f"M{i}" for i in range(11)
    ]
    assert "No milestone implementation" in plan["approval_gate"]
    assert len(plan["open_questions_and_conflicts"]) >= 1


def test_project_state_is_explicitly_unverified() -> None:
    state = (ROOT / "project-state.yaml").read_text(encoding="utf-8")
    assert "status: m3_in_progress" in state
    assert "current_milestone: M3" in state
    assert "m1_production_code_started: true" in state
    assert "m1_increment_4_6_status: verified" in state
    assert "m1_status: verified" in state
    assert "m1_increment_2_status: verified" in state
    assert "m1_increment_3_status: verified" in state
    assert "m1_increment_4_1_status: verified" in state
    assert "m1_increment_4_2_status: verified" in state
    assert "m1_increment_4_3_status: verified" in state
    assert "m1_increment_4_4_status: verified" in state
    assert "m1_increment_4_status: verified" in state
    assert "m1_increment_4_5_status: verified" in state
    assert "m2_status: verified" in state
    assert "m3_increment_1_status: verified" in state
    assert "completed_milestones:" in state
    assert "  - M0" in state
    assert "git_initialized: true" in state
    assert "Do not mark a milestone complete" in state
