"""Baseline contract tests for planning artifacts.

These tests intentionally verify only the planning/state contract. They must not
be interpreted as implementation acceptance tests for any future milestone.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

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
#: The M9 binding has its own required-key set. AUD-007 has a dedicated target-key
#: assertion so unrelated historical state entries remain outside R9's scope.
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

# Historical duplicate top-level entries that predate AUD-007 and are retained
# as governance history. The whole-file gate below makes this inventory closed:
# any new duplicate or changed historical value is a structural regression.
KNOWN_HISTORICAL_DUPLICATES: dict[str, list[str]] = {
    "m1_increment_4_2_status": ["verified", "verified"],
    "m1_increment_4_3_status": ["verified", "verified"],
    "m1_increment_4_4_status": ["verified", "verified"],
    "m1_increment_4_4_evidence": [
        "acceptance-m1-increment-4-4.md",
        "acceptance-m1-increment-4-4.md",
    ],
    "m1_increment_4_status": ["in_progress", "verified"],
    "m3_increment_1_plan_commit": ["46be195", "46be195"],
    "m1_increment_4_4_plan": [
        ".hermes/plans/2026-08-05_000000-m1-increment-4-4-verified-hook-registration.md",
        ".hermes/plans/2026-08-05_000000-m1-increment-4-4-verified-hook-registration.md",
    ],
}


def _state_text() -> str:
    return (ROOT / "project-state.yaml").read_text(encoding="utf-8")


_TOP_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$", re.MULTILINE)


def _strip_scalar(raw: str) -> str:
    """Normalize a single-line scalar: drop one layer of surrounding double
    quotes and collapse internal whitespace, matching the simple representation
    used by project-state.yaml's top-level M9 bindings.
    """
    s = raw.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    return re.sub(r"\s+", " ", s).strip()


def _top_level_key_counts(text: str) -> dict[str, int]:
    """Count top-level mapping keys STRUCTURALLY, before last-wins collapses them.

    A duplicated top-level key is invisible to a standard parse (last-wins
    reduces it to one entry). We therefore scan the raw text for column-0
    ``key:`` lines with a dependency-free regex, preserving every occurrence so
    a duplicate is observable without a third-party YAML library.
    """
    counts: dict[str, int] = {}
    for m in _TOP_KEY_RE.finditer(text):
        key = m.group(1)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _effective_state(text: str) -> dict[str, str]:
    """Parse top-level scalar bindings, LAST-WINS (mirrors YAML resolution).

    Narrowly scoped to the simple top-level scalar syntax used by
    project-state.yaml. Block scalars and nested maps are intentionally out of
    scope: the guarded M9 keys are all single-line scalars. Dependency-free.
    """
    eff: dict[str, str] = {}
    for m in _TOP_KEY_RE.finditer(text):
        eff[m.group(1)] = _strip_scalar(m.group(2))
    return eff


def _top_level_key_values(text: str) -> dict[str, list[str]]:
    """Collect every top-level scalar value before YAML last-wins parsing."""
    values: dict[str, list[str]] = {}
    for m in _TOP_KEY_RE.finditer(text):
        values.setdefault(m.group(1), []).append(_strip_scalar(m.group(2)))
    return values


def test_master_spec_and_derived_agents_exist() -> None:
    assert (ROOT / "Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx").is_file()
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "SQLite + JSONL" in agents
    assert "Redact or reject secrets before persistence" in agents


def test_tracked_tests_reject_audited_checkout_root() -> None:
    """Test sources must not embed the audited operator checkout root."""
    audited_root = "/" + "/".join(
        ("home", "brian-nguyen", "Hermes Workplace", "Zero-mem")
    )
    listed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--", "tests"],
        check=True,
        capture_output=True,
        text=True,
    )
    offenders = []
    for relative in listed.stdout.splitlines():
        path = ROOT / relative
        if path.suffix == ".py" and audited_root in path.read_text(encoding="utf-8"):
            offenders.append(relative)
    assert offenders == [], f"audited checkout root found in tracked tests: {offenders}"


def test_implementation_plan_is_machine_readable_and_gated() -> None:
    plan = json.loads((ROOT / "implementation-plan.json").read_text(encoding="utf-8"))
    # M0-M10 VERIFIED; M10.7 is the final verified increment.
    assert plan["status"] == "verified"
    assert plan["current_milestone_status"] == "m10_verified"
    assert plan["current_milestone_verification"] == "m10_7_verified"
    assert plan["m8_increment_1_status"] == "verified"
    assert plan["m8_increment_2_status"] == "verified"
    assert plan["m8_increment_3_status"] == "verified"
    assert plan["m8_increment_4_status"] == "verified"
    assert plan["m8_increment_5_status"] == "verified"
    assert plan["m8_increment_6_status"] == "verified"
    assert plan["m8_next_incomplete_increment"] == "none"
    assert plan["m8_schema_version"] == 9
    # M9.1-M9.6 state binding; M9 is complete.
    assert plan["m9_plan_status"] == "approved"
    assert plan["m9_overall_status"] == "verified"
    assert plan["m9_increment_1_status"] == "verified"
    assert plan["m9_increment_2_status"] == "verified"
    assert plan["m9_increment_2_evidence"] == "acceptance-m9.2.md"
    assert plan["m9_increment_3_status"] == "verified"
    assert plan["m9_increment_4_status"] == "verified"
    assert plan["m9_increment_5_status"] == "verified"
    assert plan["m9_increment_5_evidence"] == "acceptance-m9.5.md"
    assert plan["m9_increment_6_status"] == "verified"
    assert plan["m9_next_incomplete_increment"] == "none"
    assert plan["m9_schema_version"] == 9
    assert plan["m10_status"] == "verified"
    for increment in range(1, 8):
        assert plan[f"m10_increment_{increment}_status"] == "verified"
    assert plan["m10_increment_count"] == 7
    assert plan["next_incomplete_milestone"] == "none"
    assert plan["next_milestone_status"] == "feature_freeze_active"
    assert plan["feature_freeze_status"] == "active"
    assert plan["post_m10_audit_status"] == "not_started"
    assert plan["packaging_status"] == "not_started"
    assert not any(key.startswith("m10_8") for key in plan)
    assert not any(key.startswith("m11") for key in plan)
    assert plan["milestones"][0]["verification"]["status"] == "fully_verified"
    assert [milestone["id"] for milestone in plan["milestones"]] == [
        f"M{i}" for i in range(11)
    ]
    assert "No milestone implementation" in plan["approval_gate"]
    assert len(plan["open_questions_and_conflicts"]) >= 1


def test_project_state_reflects_verified_m9_binding() -> None:
    state = (ROOT / "project-state.yaml").read_text(encoding="utf-8")
    # M0-M8 VERIFIED; M8.1-M8.6 all verified, M8 complete.
    assert "status: verified" in state
    assert "current_milestone: M10" in state
    # M8.6 state binding: M8 VERIFIED, M8.1-M8.6 VERIFIED.
    assert "m8_plan_status: \"approved\"" in state
    assert "m8_overall_status: \"verified\"" in state
    assert "m8_increment_1_status: \"verified\"" in state
    assert "m8_increment_2_status: \"verified\"" in state
    assert "m8_increment_3_status: \"verified\"" in state
    assert "m8_increment_4_status: \"verified\"" in state
    assert "m8_increment_5_status: \"verified\"" in state
    assert "m8_increment_6_status: \"verified\"" in state
    # M9.6 final state binding: M9 VERIFIED, M9.1-M9.6 VERIFIED.
    assert "m9_plan_status: \"approved\"" in state
    assert "m9_overall_status: \"verified\"" in state
    assert "m9_increment_1_status: \"verified\"" in state
    assert "m9_increment_2_status: \"verified\"" in state
    assert "m9_increment_3_status: \"verified\"" in state
    assert "m9_increment_4_status: \"verified\"" in state
    assert "m9_increment_5_status: \"verified\"" in state
    assert "m9_increment_6_status: \"verified\"" in state
    assert "m9_next_incomplete_increment: \"none\"" in state
    assert "m9_schema: \"v9\"" in state
    assert "m9_increment_1_evidence: acceptance-m9.1.md" in state
    assert "m9_increment_2_evidence: acceptance-m9.2.md" in state
    assert "m9_increment_5_evidence: acceptance-m9.5.md" in state
    assert "m9_increment_6_evidence: acceptance-m9.6.md" in state
    assert "next_incomplete_milestone: none" in state
    assert "next_milestone_status: feature_freeze_active" in state
    assert "feature_freeze_status: active" in state
    assert "post_m10_audit_status: not_started" in state
    assert "packaging_status: not_started" in state
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


def test_m9_effective_parsed_state_is_verified() -> None:
    """Assert the EFFECTIVE (parsed) M9 binding, not its textual appearance.

    M9 overall is VERIFIED; M9.1-M9.6 are verified. The M10 plan is APPROVED and
    M10.1 (Corpus Source Registry + Authorization Boundary), M10.2
    (Multi-format Ingestion + Structural Extraction), M10.3
    (Normalization + Deduplication + Versioning), M10.4
    (Derived Corpus Storage + Indexing, migrate_10 -> schema v10), M10.5
    (Hybrid Retrieval + EvidenceSet Integration), M10.6
    (Derived authorization-safe corpus graph + optional enrichment boundary),
    and M10.7 (Large-Corpus Rollout + Benchmark + Final M10 Acceptance) are
    VERIFIED -- so M10 overall is VERIFIED.
    This baseline reflects the genuine post-M10.7 state.
    """
    state = _effective_state(_state_text())
    assert state["m9_plan_status"] == "approved"
    assert state["m9_overall_status"] == "verified"
    assert state["m9_status"] == "verified"
    assert state["m9_increment_1_status"] == "verified"
    assert state["m9_increment_2_status"] == "verified"
    assert state["m9_increment_3_status"] == "verified"
    assert state["m9_increment_4_status"] == "verified"
    assert state["m9_increment_5_status"] == "verified"
    assert state["m9_increment_6_status"] == "verified"
    assert state["m9_next_incomplete_increment"] == "none"
    assert state["m9_schema"] == "v9"
    # M10 plan APPROVED; M10.1-M10.7 verified; M10 COMPLETE.
    assert state["m10_plan_status"] == "approved"
    assert state["m10_status"] == "verified"
    assert state["m10_current_increment"] == (
        "m10_7_large_corpus_rollout_benchmark_final_acceptance"
    )
    assert state["m10_current_increment_status"] == "verified"
    assert state["feature_freeze_status"] == "active"
    assert state["post_m10_audit_status"] == "not_started"
    assert state["packaging_status"] == "not_started"
    # M10 is the final approved milestone: no M10.8 and no M11 may be invented.
    # _effective_state yields raw scalar STRINGS, so compare as text.
    assert state["m10_increment_count"] == "7"
    assert "m10_8" not in _state_text()
    assert "m11_" not in _state_text()


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

    # 2. but the document now MEANS the opposite (last-wins resolution).
    assert _effective_state(shadowed)["m9_overall_status"] == "verified"

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


def test_project_state_has_one_m2_current_version() -> None:
    """Reject AUD-007 shadowing without broadening R9 to other history entries."""
    state = _state_text()
    counts = _top_level_key_counts(state)
    values = _top_level_key_values(state)
    assert counts["m2_current_version"] == 1
    assert values["m2_current_version"] == ["6"]
    assert _effective_state(state)["m2_current_version"] == "6"


def test_project_state_has_no_unexpected_top_level_duplicate_keys() -> None:
    """Scan the whole artifact while preserving classified legacy entries."""
    values = _top_level_key_values(_state_text())
    duplicates = {key: entries for key, entries in values.items() if len(entries) > 1}
    assert duplicates == KNOWN_HISTORICAL_DUPLICATES
