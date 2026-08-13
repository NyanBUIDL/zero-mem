"""PKG-3 first-run setup and doctor acceptance tests."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _env(root: Path) -> dict[str, str]:
    home = root / "HOME with spaces"
    env = dict(os.environ)
    env.update(
        {
            "HOME": str(home),
            "XDG_DATA_HOME": str(root / "data root with spaces"),
            "XDG_CONFIG_HOME": str(root / "config root with spaces"),
            "XDG_STATE_HOME": str(root / "state root with spaces"),
            "XDG_CACHE_HOME": str(root / "cache root with spaces"),
            "PYTHONNOUSERSITE": "1",
        }
    )
    for name in ("ZERO_MEM_CORPUS_ROOT", "ZERO_MEM_OBSIDIAN_VAULT", "AI_API_KEY"):
        env.pop(name, None)
    env.pop("PYTHONPATH", None)
    return env


def _run(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "zero_mem.cli", *args],
        cwd=ROOT,
        env=_env(root),
        check=check,
        capture_output=True,
        text=True,
    )


def _paths(root: Path) -> tuple[Path, Path, Path]:
    data = root / "data root with spaces" / "zero-mem"
    config = root / "config root with spaces" / "zero-mem"
    return data, config, data / "data" / "memory" / "traces" / "events-v1.jsonl"


def test_setup_reaches_ready_without_optional_integrations(tmp_path: Path) -> None:
    result = _run(tmp_path, "setup")
    assert result.returncode == 0
    assert result.stdout.strip() == "READY"

    data, config, memory_stream = _paths(tmp_path)
    assert (config / "config.json").is_file()
    assert memory_stream.is_file()
    assert (data / "data" / "derived" / "memory.sqlite3").is_file()
    assert not (data / "corpus").exists()
    assert not (data / "obsidian").exists()


def test_doctor_reports_optional_absence_as_warnings_and_is_json(tmp_path: Path) -> None:
    assert _run(tmp_path, "setup").returncode == 0
    before = sorted(
        (path.relative_to(tmp_path), path.stat().st_mtime_ns, path.stat().st_size)
        for path in tmp_path.rglob("*")
        if path.is_file()
    )
    result = _run(tmp_path, "doctor", "--json")
    after = sorted(
        (path.relative_to(tmp_path), path.stat().st_mtime_ns, path.stat().st_size)
        for path in tmp_path.rglob("*")
        if path.is_file()
    )
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["overall"] == "READY"
    assert all(check["status"] in {"PASS", "WARN", "OPTIONAL"} for check in report["checks"])
    assert any(check["id"] == "hermes" and check["status"] == "WARN" for check in report["checks"])
    assert any(check["id"] == "corpus" and check["status"] == "WARN" for check in report["checks"])
    assert before == after
    assert str(tmp_path) not in result.stdout


def test_setup_rejects_malformed_configuration_without_mutation(tmp_path: Path) -> None:
    _, config, _ = _paths(tmp_path)
    config.mkdir(parents=True)
    config_file = config / "config.json"
    config_file.write_text("{not-json", encoding="utf-8")
    before = config_file.read_bytes()

    result = _run(tmp_path, "setup", check=False)
    assert result.returncode != 0
    assert "configuration" in result.stderr.lower()
    assert str(tmp_path) not in result.stderr
    assert config_file.read_bytes() == before


def test_doctor_fails_closed_on_malformed_configuration(tmp_path: Path) -> None:
    _, config, _ = _paths(tmp_path)
    config.mkdir(parents=True)
    (config / "config.json").write_text("[]", encoding="utf-8")

    result = _run(tmp_path, "doctor", "--json", check=False)
    assert result.returncode != 0
    report = json.loads(result.stdout)
    assert report["overall"] == "NOT_READY"
    assert any(check["id"] == "configuration" and check["status"] == "FAIL" for check in report["checks"])
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


def test_setup_doctor_commands_are_exposed_but_later_commands_are_not(tmp_path: Path) -> None:
    help_result = _run(tmp_path, "--help")
    assert " setup" in help_result.stdout
    assert " doctor" in help_result.stdout
    assert " status" not in help_result.stdout
    assert " rebuild" not in help_result.stdout
    assert " backup" in help_result.stdout
    assert " integrate" in help_result.stdout
    assert " upgrade" not in help_result.stdout
    assert " start" not in help_result.stdout
