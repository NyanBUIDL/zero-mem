"""Baseline contract tests for planning artifacts.

These tests intentionally verify only the planning/state contract. They must not
be interpreted as implementation acceptance tests for any future milestone.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]

#: M9 state-binding keys whose EFFECTIVE parsed value gates milestone progress.
#: Each must appear exactly once at the top level of ``project-state.yaml``.
#:
#: Duplicate-key shadowing is why this list exists. YAML resolves a repeated key
#: last-wins, so a later block can silently invert an earlier one while BOTH
#: textual forms remain present in the file — which makes a substring assertion
#: like ``'m9_overall_status: "in_progress"' in state`` pass against a document
#: that actually parses to ``verified``. That exact defect shipped in the M9.5
#: state binding and was invisible to the substring gate. Structural key counting
#: plus effective-value assertions is the only form that catches it.
#:
#: Scope is deliberately limited to the M9 binding: a repository-wide duplicate
#: gate would pull unrelated, separately-tracked historical duplicates
#: (``m2_current_version`` and the ``m1_*`` pairs) into this contract.
M9_STATE_BINDING_KEYS: tuple[str, ...] = (
    "m9_plan_status",
    "m9_overall_status",
    "m9_status",
    "m9_current_increment",
    "m9_next_incomplete_increment",
    "m9_schema",
    "m9_increment_1_status",
    "m9_increment_2_status",
    "m9_increment_3_status",
    "m9_increment_4_status",
    "m9_increment_5_status",
)


def _state_text() -> str:
    return (ROOT / "project-state.yaml").read_text(encoding="utf-8")


def _top_level_key_counts(text: str) -> dict[str, int]:
    """Count top-level mapping keys STRUCTURALLY, before last-wins collapses them.

    ``yaml.safe_load`` cannot answer this question: by the time it returns a
    dict, a duplicated key has already been silently reduced to one entry. The
    composed node graph still carries every key node, so it is the only place a
    duplicate is observable without hand-rolling a parser or adding a
    dependency.
    """
    root = yaml.compose(text)
    if root is None:
        return {}
    counts: dict[str, int] = {}
    for key_node, _value_node in getattr(root, "value", []):
        key = getattr(key_node, "value", None)
        if isinstance(key, str):
            counts[key] = counts.get(key, 0) + 1
    return counts


def test_master_spec_and_derived_agents_exist() -> None:
    assert (ROOT / "Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx").is_file()
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "SQLite + JSONL" in agents
    assert "Redact or reject secrets before persistence" in agents


def test_implementation_plan_is_machine_readable_and_gated() -> None:
    plan = json.loads((ROOT / "implementation-plan.json").read_text(encoding="utf-8"))
    # M0-M8 VERIFIED; M9 IN PROGRESS (M9.1-M9.5 VERIFIED; M9.6 / M10 NOT STARTED).
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
    # M9.1-M9.5 state binding.
    assert plan["m9_plan_status"] == "approved"
    assert plan["m9_overall_status"] == "in_progress"
    assert plan["m9_increment_1_status"] == "verified"
    assert plan["m9_increment_2_status"] == "verified"
    assert plan["m9_increment_2_evidence"] == "acceptance-m9.2.md"
    assert plan["m9_increment_3_status"] == "verified"
    assert plan["m9_increment_4_status"] == "verified"
    assert plan["m9_increment_5_status"] == "verified"
    assert plan["m9_increment_5_evidence"] == "acceptance-m9.5.md"
    assert plan["m9_increment_6_status"] == "not_started"
    assert plan["m9_next_incomplete_increment"] == "M9.6"
    assert plan["m9_schema_version"] == 9
    assert plan["m10_status"] == "not_started"
    assert plan["next_incomplete_milestone"] == "M9.6"
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
    # M9.5 state binding: M9 IN PROGRESS, M9.1-M9.5 VERIFIED,
    # M9.6 / M10 NOT STARTED. Schema remains v9.
    assert "m9_plan_status: \"approved\"" in state
    assert "m9_overall_status: \"in_progress\"" in state
    assert "m9_increment_1_status: \"verified\"" in state
    assert "m9_increment_2_status: \"verified\"" in state
    assert "m9_increment_3_status: \"verified\"" in state
    assert "m9_increment_4_status: \"verified\"" in state
    assert "m9_increment_5_status: \"verified\"" in state
    assert "m9_next_incomplete_increment: \"M9.6\"" in state
    assert "m9_schema: \"v9\"" in state
    assert "m9_increment_1_evidence: acceptance-m9.1.md" in state
    assert "m9_increment_2_evidence: acceptance-m9.2.md" in state
    assert "m9_increment_5_evidence: acceptance-m9.5.md" in state
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


# ---------------------------------------------------------------------------
# M9 state-binding gate — structural, not substring
# ---------------------------------------------------------------------------


def test_m9_state_binding_keys_are_not_duplicated() -> None:
    """No M9 state-binding key may appear twice at the top level.

    A duplicated key is rejected even when one of its occurrences carries the
    expected value: last-wins means the *other* occurrence is what the file
    actually means, and a reader that trusts the first one is simply wrong.
    """
    counts = _top_level_key_counts(_state_text())
    duplicated = {
        key: counts[key]
        for key in M9_STATE_BINDING_KEYS
        if counts.get(key, 0) > 1
    }
    assert duplicated == {}, f"duplicated M9 state-binding keys: {duplicated}"


def test_m9_state_binding_keys_are_each_present_exactly_once() -> None:
    counts = _top_level_key_counts(_state_text())
    missing = [key for key in M9_STATE_BINDING_KEYS if counts.get(key, 0) == 0]
    assert missing == [], f"missing M9 state-binding keys: {missing}"


def test_m9_effective_parsed_state_is_m9_in_progress() -> None:
    """Assert the EFFECTIVE (parsed) M9 binding, not its textual appearance.

    M9 overall stays ``in_progress`` until M9.6 is verified; M9.1-M9.5 are
    verified; M10 has not started.
    """
    state = yaml.safe_load(_state_text())
    assert state["m9_plan_status"] == "approved"
    assert state["m9_overall_status"] == "in_progress"
    assert state["m9_status"] == "in_progress"
    assert state["m9_increment_1_status"] == "verified"
    assert state["m9_increment_2_status"] == "verified"
    assert state["m9_increment_3_status"] == "verified"
    assert state["m9_increment_4_status"] == "verified"
    assert state["m9_increment_5_status"] == "verified"
    assert state["m9_next_incomplete_increment"] == "M9.6"
    assert state["m9_schema"] == "v9"
    assert state["m10_status"] == "not_started"


def test_m9_duplicate_key_shadowing_is_detected() -> None:
    """NON-VACUITY: the gate must FAIL on the exact defect it exists to catch.

    Reproduces the M9.5 state-binding defect against a SELF-CONTAINED synthetic
    document — an appended block that re-declares M9 keys with inverted values —
    and proves three things:

    1. the substring form the gate previously relied on still passes, so the
       old assertion genuinely could not detect this;
    2. the effective parsed value is the *later* one (silent inversion);
    3. the structural duplicate check rejects it.

    Synthetic rather than derived from the real file, so the control proves the
    GATE works regardless of the repository file's current cleanliness, and
    cannot itself be broken by an unrelated future edit to that file.

    Without this control, the duplicate check above could pass simply because
    the file happens to be clean, and would never be proven to work at all.
    """
    clean = 'm9_overall_status: "in_progress"\nm9_status: "in_progress"\n'
    shadowed = clean + 'm9_overall_status: "verified"\nm9_status: "verified"\n'

    # Control: the clean form is accepted by the structural gate.
    assert _top_level_key_counts(clean)["m9_overall_status"] == 1

    # 1. the OLD substring gate is fooled: the expected text is still present.
    assert 'm9_overall_status: "in_progress"' in shadowed

    # 2. but the document now MEANS the opposite.
    assert yaml.safe_load(shadowed)["m9_overall_status"] == "verified"

    # 3. the structural gate catches it.
    counts = _top_level_key_counts(shadowed)
    assert counts["m9_overall_status"] > 1
    assert counts["m9_status"] > 1
    duplicated = {
        key: counts[key]
        for key in M9_STATE_BINDING_KEYS
        if counts.get(key, 0) > 1
    }
    assert duplicated, "duplicate-key gate failed to detect a shadowed M9 key"
