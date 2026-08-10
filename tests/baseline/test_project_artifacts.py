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
    # M0-M8 VERIFIED; M9 IN PROGRESS (M9.1 VERIFIED; M9.2-M9.6 / M10 NOT STARTED).
    assert plan["status"] == "m9_in_progress"
    assert plan["current_milestone_status"] == "m9_in_progress"
    assert plan["m8_increment_1_status"] == "verified"
    assert plan["m8_increment_2_status"] == "verified"
    assert plan["m8_increment_3_status"] == "verified"
    assert plan["m8_increment_4_status"] == "verified"
    assert plan["m8_increment_5_status"] == "verified"
    assert plan["m8_increment_6_status"] == "verified"
    assert plan["m8_next_incomplete_increment"] == "none"
    assert plan["m8_schema_version"] == 9
    # M9.1 state binding.
    assert plan["m9_plan_status"] == "approved"
    assert plan["m9_overall_status"] == "in_progress"
    assert plan["m9_increment_1_status"] == "verified"
    assert plan["m9_increment_2_status"] == "not_started"
    assert plan["m9_increment_3_status"] == "not_started"
    assert plan["m9_increment_4_status"] == "not_started"
    assert plan["m9_increment_5_status"] == "not_started"
    assert plan["m9_increment_6_status"] == "not_started"
    assert plan["m9_next_incomplete_increment"] == "M9.2"
    assert plan["m9_schema_version"] == 9
    assert plan["m10_status"] == "not_started"
    assert plan["next_incomplete_milestone"] == "M9"
    assert plan["milestones"][0]["verification"]["status"] == "fully_verified"
    assert [milestone["id"] for milestone in plan["milestones"]] == [
        f"M{i}" for i in range(11)
    ]
    assert "No milestone implementation" in plan["approval_gate"]
    assert len(plan["open_questions_and_conflicts"]) >= 1


def test_project_state_is_explicitly_unverified() -> None:
    state = (ROOT / "project-state.yaml").read_text(encoding="utf-8")
    # M0-M8 VERIFIED; M8.1-M8.6 all verified, M8 complete.
    assert "status: verified" in state
    assert "current_milestone: M8" in state
    # M8.6 state binding: M8 VERIFIED, M8.1-M8.6 VERIFIED, M9/M10 NOT STARTED.
    assert "m8_plan_status: \"approved\"" in state
    assert "m8_overall_status: \"verified\"" in state
    assert "m8_increment_1_status: \"verified\"" in state
    assert "m8_increment_2_status: \"verified\"" in state
    assert "m8_increment_3_status: \"verified\"" in state
    assert "m8_increment_4_status: \"verified\"" in state
    assert "m8_increment_5_status: \"verified\"" in state
    assert "m8_increment_6_status: \"verified\"" in state
    # M9 advanced by M9.1 state binding: M9 IN PROGRESS, M9.1 VERIFIED,
    # M9.2-M9.6 / M10 NOT STARTED. Schema remains v9.
    assert "m9_plan_status: \"approved\"" in state
    assert "m9_overall_status: \"in_progress\"" in state
    assert "m9_increment_1_status: \"verified\"" in state
    assert "m9_next_incomplete_increment: \"M9.2\"" in state
    assert "m9_schema: \"v9\"" in state
    assert "m9_increment_1_evidence: acceptance-m9.1.md" in state
    assert "m10_status: \"not_started\"" in state
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
