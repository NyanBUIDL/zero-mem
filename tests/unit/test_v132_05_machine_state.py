"""V132-05 — machine-state consolidation (D-02 Option A) unit tests.

Contract:
  * scripts/check_machine_state.py passes on the real repo tree
    (project-state.yaml = single source; implementation-plan.json carries
    the frozen-record header);
  * the validator fail-closes on tampered fixtures: missing header,
    wrong superseded_by, unparseable yaml, missing required keys.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

_SPEC = importlib.util.spec_from_file_location(
    "check_machine_state",
    REPO_ROOT / "scripts" / "check_machine_state.py",
)
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)


class TestV132Wp5MachineStateSingleSource:
    def test_real_repo_is_consistent(self):
        assert mod.check_machine_state(REPO_ROOT) == []

    def test_missing_frozen_header_fails_closed(self, tmp_path):
        plan = {"schema_version": 1}
        (tmp_path / "implementation-plan.json").write_text(json.dumps(plan))
        problems = mod.check_machine_state(tmp_path)
        # project-state.yaml missing is reported first; craft full fixture below.
        assert any("missing machine state" in p for p in problems)

    def test_full_fixture_with_stale_plan_fails(self, tmp_path):
        (tmp_path / "project-state.yaml").write_text(
            "schema_version: 1\nproject: x\nstatus: verified\n"
        )
        (tmp_path / "implementation-plan.json").write_text(
            json.dumps({"schema_version": 1})
        )
        problems = mod.check_machine_state(tmp_path)
        assert any("record_role" in p for p in problems)
        assert any("superseded_by" in p for p in problems)

    def test_full_fixture_consistent_passes(self, tmp_path):
        (tmp_path / "project-state.yaml").write_text(
            "schema_version: 1\nproject: x\nstatus: verified\n"
        )
        (tmp_path / "implementation-plan.json").write_text(json.dumps({
            "record_role": mod.FROZEN_ROLE,
            "superseded_by": mod.SUPERSEDED_BY,
        }))
        assert mod.check_machine_state(tmp_path) == []

    def test_unparseable_yaml_fails_closed(self, tmp_path):
        (tmp_path / "project-state.yaml").write_text(": : :\nbroken\t[")
        problems = mod.check_machine_state(tmp_path)
        assert any("unparseable" in p for p in problems)

    def test_yaml_missing_required_key_reported(self, tmp_path):
        (tmp_path / "project-state.yaml").write_text("status: verified\n")
        (tmp_path / "implementation-plan.json").write_text(json.dumps({
            "record_role": mod.FROZEN_ROLE,
            "superseded_by": mod.SUPERSEDED_BY,
        }))
        problems = mod.check_machine_state(tmp_path)
        assert any("required key" in p for p in problems)

    def test_no_src_runtime_imports_this_module(self):
        # D-02 constraint: governance tooling only; src/ must not depend on it.
        hits = list((REPO_ROOT / "src").rglob("*.py"))
        offenders = [
            f.relative_to(REPO_ROOT)
            for f in hits
            if "check_machine_state" in f.read_text(encoding="utf-8", errors="ignore")
        ]
        assert offenders == []
