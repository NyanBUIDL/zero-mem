"""Regression pins for the confirmed post-v1.6.0 packaging audit findings."""

from __future__ import annotations

import tomllib
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_def041_license_is_shipped_by_explicit_packaging_contract() -> None:
    license_path = ROOT / "LICENSE"
    assert license_path.is_file()
    license_text = license_path.read_text(encoding="utf-8")
    assert "MIT License" in license_text
    assert "Permission is hereby granted, free of charge" in license_text
    assert 'THE SOFTWARE IS PROVIDED "AS IS"' in license_text

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["license"] == "MIT"
    assert project["project"]["license-files"] == ["LICENSE", "NOTICE"]
    assert project["project"]["authors"] == [{"name": "NyanBUIDL"}]
    assert project["build-system"]["requires"] == ["setuptools>=77"]


def test_def042_wheel_acceptance_uses_installed_artifact_version() -> None:
    acceptance = (ROOT / "tests" / "packaging" / "pkg1_wheel_acceptance.py").read_text(
        encoding="utf-8"
    )
    assert "1.2.2" not in acceptance
    assert 'm.version("zero-mem")' in acceptance
    assert "expected_version" in acceptance


def test_def044_wheel_acceptance_supports_windows_venvs() -> None:
    acceptance = (ROOT / "tests" / "packaging" / "pkg1_wheel_acceptance.py").read_text(
        encoding="utf-8"
    )
    assert '"Scripts"' in acceptance
    assert '"zero-mem.exe"' in acceptance


def test_def043_release_notes_record_post_publication_state() -> None:
    notes = (ROOT / "docs" / "releases" / "RELEASE-NOTES-v1.6.0.md").read_text(
        encoding="utf-8"
    )
    assert "chưa tạo tag/release" not in notes
    assert "Post-publication addendum" in notes
    assert "267fd9ae830eff41aeaf85cbfbd41f38c03849a6" in notes


def test_def047_machine_state_records_published_v160_and_v161_candidate() -> None:
    state = yaml.safe_load((ROOT / "project-state.yaml").read_text(encoding="utf-8"))
    assert state["v160_status"] == "RELEASED_PUBLISHED"
    assert state["v160_tag"] == "v1.6.0"
    assert state["v160_release_sha"] == "267fd9ae830eff41aeaf85cbfbd41f38c03849a6"
    assert state["v161_status"] == "RELEASE_CANDIDATE"
    assert state["v161_version"] == "1.6.1"
    assert state["v161_branch"] == "release/v1.6.1"


def test_v161_release_branch_has_nine_cell_qualification_workflow() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "v1.6.1-qualification.yml"
    workflow = yaml.load(workflow_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert workflow["on"]["push"]["branches"] == ["master", "release/v1.6.1"]
    assert workflow["on"]["push"]["tags"] == ["v1.6.1"]
    matrix = workflow["jobs"]["qualify"]["strategy"]["matrix"]
    assert matrix["os"] == ["ubuntu-latest", "windows-latest", "macos-latest"]
    assert matrix["python-version"] == ["3.11", "3.12", "3.13"]
    assert workflow["permissions"] == {"contents": "read"}
    runs = [step.get("run", "") for step in workflow["jobs"]["qualify"]["steps"]]
    assert any("check_release_artifacts.py" in run for run in runs)
