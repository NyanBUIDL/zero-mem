"""V1.6.0 DX wizard/onboarding acceptance."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from zero_mem import commands_wizard
from zero_mem import hermes_integration as hi


ROOT = Path(__file__).resolve().parents[2]


def _env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "HOME": str(root / "home with spaces"),
            "XDG_DATA_HOME": str(root / "data with spaces"),
            "XDG_CONFIG_HOME": str(root / "config with spaces"),
            "XDG_STATE_HOME": str(root / "state with spaces"),
            "XDG_CACHE_HOME": str(root / "cache with spaces"),
            "PYTHONNOUSERSITE": "1",
        }
    )
    env.pop("PYTHONPATH", None)
    return env


def _isolate(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    for name, value in _env(root).items():
        monkeypatch.setenv(name, value)


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "zero_mem.cli", "wizard", *args],
        cwd=ROOT,
        env=_env(root),
        capture_output=True,
        text=True,
        check=False,
    )


def test_noninteractive_standalone_onboarding_reaches_ready(tmp_path: Path) -> None:
    result = _run(tmp_path, "--non-interactive", "--skip-hermes", "--json")

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report == {
        "doctor": "READY",
        "hermes": "SKIPPED",
        "next_steps": ["zero-mem doctor"],
        "schema_version": 1,
        "setup": "READY",
        "status": "READY",
    }
    assert (tmp_path / "config with spaces" / "zero-mem" / "config.json").is_file()
    assert not (tmp_path / "config with spaces" / "zero-mem" / "hermes-integration.json").exists()
    assert str(tmp_path) not in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        ("--non-interactive",),
        ("--non-interactive", "--project-id", "project-only"),
        ("--non-interactive", "--profile-id", "profile-only"),
        ("--non-interactive", "--skip-hermes", "--project-id", "p", "--profile-id", "r"),
        ("--skip-hermes", "--json"),
    ],
)
def test_invalid_wizard_request_fails_before_mutation(tmp_path: Path, args: tuple[str, ...]) -> None:
    result = _run(tmp_path, *args)

    assert result.returncode == 2
    assert "wizard" in result.stderr.lower()
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "data with spaces").exists()
    assert not (tmp_path / "config with spaces").exists()


def test_interactive_standalone_does_not_prompt_for_ids_when_hermes_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(hi, "_hermes_executable", lambda: None)
    messages: list[str] = []

    code, report = commands_wizard.run(
        input_fn=lambda _prompt: pytest.fail("standalone onboarding must not request identity"),
        output_fn=messages.append,
    )

    assert code == 0
    assert report["status"] == "READY"
    assert report["hermes"] == "NOT_FOUND"
    assert any("standalone" in message.lower() for message in messages)


def test_interactive_hermes_onboarding_configures_explicit_identity_without_echo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(hi, "_hermes_executable", lambda: "/synthetic/hermes")
    monkeypatch.setattr(hi, "_boundary_modules_available", lambda: True)
    answers = iter(["yes", "project-private", "profile-private"])
    messages: list[str] = []

    code, report = commands_wizard.run(
        input_fn=lambda _prompt: next(answers),
        output_fn=messages.append,
    )

    assert code == 0
    assert report["hermes"] == "CONFIGURED"
    saved = hi.load_integration_config()
    assert saved.project_id == "project-private"
    assert saved.profile_id == "profile-private"
    rendered = "\n".join(messages) + json.dumps(report)
    assert "project-private" not in rendered
    assert "profile-private" not in rendered
    assert str(tmp_path) not in rendered


def test_wizard_rerun_preserves_existing_integration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(hi, "_hermes_executable", lambda: "/synthetic/hermes")
    monkeypatch.setattr(hi, "_boundary_modules_available", lambda: True)
    from zero_mem.commands_setup import run as setup

    setup()
    hi.configure_integration(project_id="project-one", profile_id="profile-one")
    before = hi.integration_config_path().read_bytes()

    code, report = commands_wizard.run(
        input_fn=lambda _prompt: pytest.fail("configured integration must be preserved"),
        output_fn=lambda _message: None,
    )

    assert code == 0
    assert report["hermes"] == "PRESERVED"
    assert hi.integration_config_path().read_bytes() == before


def test_wizard_help_explains_identity_and_modes(tmp_path: Path) -> None:
    result = _run(tmp_path, "--help")

    assert result.returncode == 0
    assert "--project-id" in result.stdout
    assert "--profile-id" in result.stdout
    assert "--skip-hermes" in result.stdout
    assert "--non-interactive" in result.stdout
    assert "--json" in result.stdout
