"""Permanent PKG-2 offline installer/uninstaller acceptance tests."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUNDLE_BUILDER = ROOT / "packaging" / "build_bundle.py"
INSTALLER = ROOT / "packaging" / "install.py"
UNINSTALLER = ROOT / "packaging" / "uninstall.py"


def _env(home: Path) -> dict[str, str]:
    home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(
        {
            "HOME": str(home),
            "XDG_DATA_HOME": str(home / "data root with spaces"),
            "XDG_CONFIG_HOME": str(home / "config root with spaces"),
            "XDG_STATE_HOME": str(home / "state root with spaces"),
            "XDG_CACHE_HOME": str(home / "cache root with spaces"),
            "XDG_BIN_HOME": str(home / "bin root with spaces"),
            "PYTHONNOUSERSITE": "1",
            # A release wheel must have stable ZIP timestamps as well as a
            # stable payload.  The build backend honors this standard
            # reproducible-build input without requiring a new dependency.
            "SOURCE_DATE_EPOCH": "315532800",
        }
    )
    env.pop("PYTHONPATH", None)
    return env


def _run(cmd: list[str], *, env: dict[str, str], cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, check=check, capture_output=True, text=True)


def _build_wheel(
    build_python: Path,
    wheel_dir: Path,
    *,
    env: dict[str, str],
) -> Path:
    wheel_dir.mkdir(parents=True, exist_ok=True)
    result = _run(
        [
            str(build_python),
            "-m",
            "pip",
            "wheel",
            "--no-index",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
            str(ROOT),
        ],
        env=env,
        check=False,
    )
    if result.returncode:
        raise AssertionError(f"wheel build failed: {result.stderr[-2000:]}")
    wheels = sorted(wheel_dir.glob("zero_mem-*.whl"))
    assert len(wheels) == 1
    return wheels[0]


@pytest.fixture(scope="session")
def bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("pkg2-bundle-build")
    builder = root / "build environment with spaces"
    build_home = root / "build home with spaces"
    build_env = _env(build_home)
    build_env["UV"] = str(root / "uv must not be used")
    _run([sys.executable, "-m", "venv", str(builder)], env=build_env)
    build_python = builder / "bin" / "python"
    tooling = _run(
        [
            str(build_python),
            "-c",
            "import importlib.util; "
            "assert importlib.util.find_spec('pip') is not None; "
            "assert importlib.util.find_spec('setuptools') is not None; "
            "assert importlib.util.find_spec('build') is None; "
            "assert importlib.util.find_spec('wheel') is None",
        ],
        env=build_env,
        cwd=builder,
    )
    assert tooling.returncode == 0
    build = _build_wheel(build_python, root / "first wheel", env=build_env)
    assert (ROOT / "build").is_dir()
    repeated = _build_wheel(build_python, root / "second wheel", env=build_env)
    assert repeated.name == build.name
    with zipfile.ZipFile(build) as first, zipfile.ZipFile(repeated) as second:
        assert first.namelist() == second.namelist()
    assert hashlib.sha256(build.read_bytes()).digest() == hashlib.sha256(repeated.read_bytes()).digest()
    output = root / "bundle with spaces"
    _run([sys.executable, str(BUNDLE_BUILDER), str(repeated), str(output)], env=dict(os.environ))
    return output


def _install(bundle: Path, root: Path, *, extra_env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    home = root / "home with spaces"
    home.mkdir(parents=True, exist_ok=True)
    env = _env(home)
    if extra_env:
        env.update(extra_env)
    return _run(
        [sys.executable, str(INSTALLER), "--bundle", str(bundle), "--non-interactive"],
        env=env,
        check=check,
    )


def test_bundle_manifest_and_checksums_cover_release_payload(bundle: Path) -> None:
    manifest = json.loads((bundle / "manifest.json").read_text())
    checksums = (bundle / "checksums.sha256").read_text()
    assert manifest["bundle_status"] == "PKG-2 INSTALLER ACCEPTANCE BUNDLE"
    assert set(manifest["payload_files"]) == {line.split("  ", 1)[1] for line in checksums.splitlines()}
    assert hashlib.sha256((bundle / "checksums.sha256").read_bytes()).hexdigest() == manifest["checksums_sha256"]
    assert not any(p.suffix in {".pdf", ".sqlite", ".jsonl", ".env"} for p in bundle.rglob("*"))


def test_fresh_offline_install_custom_xdg_and_cli(bundle: Path, tmp_path: Path) -> None:
    result = _install(bundle, tmp_path)
    assert result.returncode == 0
    home = tmp_path / "home with spaces"
    runtime = home / "data root with spaces" / "zero-mem"
    bindir = home / "bin root with spaces"
    assert (runtime / "current").is_symlink()
    assert (runtime / "runtimes" / "1.1.0" / "venv").is_dir()
    cli = bindir / "zero-mem"
    assert cli.is_file() and os.access(cli, os.X_OK)
    env = _env(home)
    assert _run([str(cli), "--help"], env=env, cwd=tmp_path).returncode == 0
    assert _run([str(cli), "--version"], env=env, cwd=tmp_path).stdout.strip() == "zero-mem 1.1.0"
    imports = _run([str(runtime / "current" / "venv" / "bin" / "python"), "-c", "import zero_mem, src; print(zero_mem.__version__)"], env=env, cwd=tmp_path)
    assert imports.stdout.strip() == "1.1.0"


def test_checksum_tampering_fails_before_activation(bundle: Path, tmp_path: Path) -> None:
    payload = next((bundle / "wheels").glob("*.whl"))
    original = payload.read_bytes()
    try:
        payload.write_bytes(original + b"tamper")
        result = _install(bundle, tmp_path, check=False)
    finally:
        payload.write_bytes(original)
    assert result.returncode != 0
    assert "checksum" in result.stderr.lower()
    runtime = tmp_path / "home with spaces" / "data root with spaces" / "zero-mem"
    assert not (runtime / "current").exists()
    assert not (runtime / "current").is_symlink()


def test_interrupted_install_preserves_previous_active_runtime(bundle: Path, tmp_path: Path) -> None:
    assert _install(bundle, tmp_path).returncode == 0
    home = tmp_path / "home with spaces"
    env = _env(home)
    runtime = home / "data root with spaces" / "zero-mem"
    before = (runtime / "current").resolve()
    result = _install(bundle, tmp_path, extra_env={"ZERO_MEM_TEST_FAIL_BEFORE_ACTIVATION": "1"}, check=False)
    assert result.returncode != 0
    assert (runtime / "current").resolve() == before
    assert not list((runtime / "runtimes").glob(".staging-*"))
    assert _run([str(runtime / "current" / "venv" / "bin" / "python"), "-m", "zero_mem.cli", "--version"], env=env, cwd=tmp_path).stdout.strip() == "zero-mem 1.1.0"


def test_same_version_reinstall_is_non_destructive(bundle: Path, tmp_path: Path) -> None:
    _install(bundle, tmp_path)
    home = tmp_path / "home with spaces"
    runtime = home / "data root with spaces" / "zero-mem"
    sentinel = runtime / "user-data-sentinel"
    sentinel.write_text("preserve")
    before = (runtime / "current").resolve()
    assert _install(bundle, tmp_path).returncode == 0
    assert (runtime / "current").resolve() == before
    assert sentinel.read_text() == "preserve"


def test_default_uninstall_preserves_user_data(bundle: Path, tmp_path: Path) -> None:
    _install(bundle, tmp_path)
    home = tmp_path / "home with spaces"
    runtime = home / "data root with spaces" / "zero-mem"
    sentinel = runtime / "Memory" / "canonical.jsonl"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("synthetic canonical data")
    env = _env(home)
    result = _run([sys.executable, str(UNINSTALLER), "--non-interactive"], env=env, check=True)
    assert result.returncode == 0
    assert not (runtime / "current").exists()
    assert not (home / "bin root with spaces" / "zero-mem").exists()
    assert sentinel.read_text() == "synthetic canonical data"


def test_uninstall_refuses_unsafe_active_symlink(bundle: Path, tmp_path: Path) -> None:
    _install(bundle, tmp_path)
    home = tmp_path / "home with spaces"
    runtime = home / "data root with spaces" / "zero-mem"
    current = runtime / "current"
    current.unlink()
    current.symlink_to(tmp_path / "outside")
    result = _run([sys.executable, str(UNINSTALLER), "--non-interactive"], env=_env(home), check=False)
    assert result.returncode != 0
    assert "escapes" in result.stderr.lower()


def test_compatible_python_detection_and_rejection() -> None:
    from packaging.release_common import is_compatible_python

    assert is_compatible_python(sys.executable)
    assert not is_compatible_python("/definitely/missing/python")


def test_no_network_fallback_is_encoded_in_installer_source() -> None:
    text = INSTALLER.read_text()
    assert "--no-index" in text
    assert "--find-links" in text
    assert "pip install" not in text or "--no-index" in text
    assert "requests" not in text.lower()
    assert "input(" in text


def test_installer_has_no_repository_dependency(bundle: Path, tmp_path: Path) -> None:
    result = _install(bundle, tmp_path)
    assert result.returncode == 0
    home = tmp_path / "home with spaces"
    venv = home / "data root with spaces" / "zero-mem" / "current" / "venv"
    env = _env(home)
    output = _run([str(venv / "bin" / "python"), "-c", "import zero_mem, src; print(zero_mem.__file__); print(src.__path__[0])"], env=env, cwd=tmp_path).stdout
    assert str(ROOT) not in output


def test_pypdf_remains_optional(bundle: Path, tmp_path: Path) -> None:
    _install(bundle, tmp_path)
    home = tmp_path / "home with spaces"
    python = home / "data root with spaces" / "zero-mem" / "current" / "venv" / "bin" / "python"
    result = _run([str(python), "-c", "import importlib.util; print(importlib.util.find_spec('pypdf'))"], env=_env(home), cwd=tmp_path)
    assert result.stdout.strip() == "None"


def test_installed_runtime_exposes_pkg3_setup_and_doctor(bundle: Path, tmp_path: Path) -> None:
    assert _install(bundle, tmp_path).returncode == 0
    home = tmp_path / "home with spaces"
    env = _env(home)
    cli = home / "bin root with spaces" / "zero-mem"
    setup = _run([str(cli), "setup"], env=env, cwd=tmp_path)
    assert setup.stdout.strip() == "READY"
    doctor = _run([str(cli), "doctor", "--json"], env=env, cwd=tmp_path)
    report = json.loads(doctor.stdout)
    assert report["overall"] == "READY"
    assert any(check["id"] == "hermes" and check["status"] == "WARN" for check in report["checks"])


def test_installed_runtime_upgrade_check_and_same_version_reinstall_preserve_state(bundle: Path, tmp_path: Path) -> None:
    assert _install(bundle, tmp_path).returncode == 0
    home = tmp_path / "home with spaces"
    env = _env(home)
    cli = home / "bin root with spaces" / "zero-mem"
    assert _run([str(cli), "setup"], env=env, cwd=tmp_path).returncode == 0
    data_root = home / "data root with spaces" / "zero-mem"
    canonical = data_root / "data" / "memory" / "traces" / "events-v1.jsonl"
    canonical.write_text('{"event_id":"pkg6-installed","event_type":"user_statement"}\n', encoding="utf-8")
    before = canonical.read_bytes()

    checked = json.loads(_run([str(cli), "upgrade", "--check", "--json"], env=env, cwd=tmp_path).stdout)
    assert checked["status"] == "READY"
    assert checked["compatibility"] == "NO_MIGRATION_REQUIRED"
    assert canonical.read_bytes() == before
    upgraded = json.loads(_run([str(cli), "upgrade", "--json"], env=env, cwd=tmp_path).stdout)
    assert upgraded["status"] == "SUCCESS"
    assert canonical.read_bytes() == before
    assert _install(bundle, tmp_path).returncode == 0
    assert canonical.read_bytes() == before
    report = json.loads(_run([str(cli), "doctor", "--json"], env=env, cwd=tmp_path).stdout)
    assert report["overall"] == "READY"
