"""Permanent PKG-2 offline installer/uninstaller acceptance tests."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from zero_mem.version import __version__ as VERSION

ROOT = Path(__file__).resolve().parents[2]
BUNDLE_BUILDER = ROOT / "release_helpers" / "build_bundle.py"

def _venv_python(venv: Path) -> Path:
    """R124-09: the venv layout is Scripts/python.exe on Windows, bin/python elsewhere."""
    return venv / "Scripts" / "python.exe" if os.name == "nt" else venv / "bin" / "python"


def _cli(bindir: Path) -> Path:
    """R124-09: the installed CLI shim is zero-mem.cmd on Windows."""
    return bindir / ("zero-mem.cmd" if os.name == "nt" else "zero-mem")


def _cli_invocation(cli: Path) -> list[str]:
    """R124-09: .cmd files must be executed through cmd.exe on Windows."""
    if os.name == "nt":
        return ["cmd", "/c", str(cli)]
    return [str(cli)]


def _is_directory_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    if os.name == "nt":
        try:
            attributes = path.stat(follow_symlinks=False).st_file_attributes
        except (FileNotFoundError, OSError, AttributeError):
            return False
        return bool(
            attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
            and attributes & stat.FILE_ATTRIBUTE_DIRECTORY
        )
    is_junction = getattr(path, "is_junction", None)
    return bool(callable(is_junction) and is_junction())


def _remove_directory_link(path: Path) -> None:
    is_junction = getattr(path, "is_junction", None)
    if _is_directory_link(path) and not path.is_symlink():
        path.rmdir()
    else:
        path.unlink()

INSTALLER = ROOT / "release_helpers" / "install.py"
UNINSTALLER = ROOT / "release_helpers" / "uninstall.py"


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
    result = subprocess.run(cmd, cwd=cwd, env=env, check=False, capture_output=True, text=True)
    if check and result.returncode:
        raise AssertionError(
            f"command failed with exit {result.returncode}: {cmd!r}\n"
            f"stdout:\n{result.stdout[-4000:]}\n"
            f"stderr:\n{result.stderr[-4000:]}"
        )
    return result


@contextmanager
def _pkg2_temp_root() -> Iterator[Path]:
    """Keep Windows venv paths below MAX_PATH while retaining space coverage."""
    with tempfile.TemporaryDirectory(prefix="zero-mem pkg2 ", ignore_cleanup_errors=True) as raw:
        yield Path(raw)


@pytest.fixture
def pkg2_root() -> Iterator[Path]:
    with _pkg2_temp_root() as root:
        yield root


def test_pkg2_temp_root_is_short_and_keeps_space_coverage() -> None:
    with _pkg2_temp_root() as root:
        assert " " in root.name
        if os.name == "nt":
            assert len(str(root)) < 100


def test_pkg2_run_failure_surfaces_captured_stderr(tmp_path: Path) -> None:
    with pytest.raises(AssertionError) as exc_info:
        _run(
            [sys.executable, "-c", "import sys; print('pkg2-inner-marker', file=sys.stderr); raise SystemExit(7)"],
            env=_env(tmp_path / "diagnostic home"),
        )
    assert "pkg2-inner-marker" in str(exc_info.value)


def test_installer_run_failure_preserves_inner_stderr(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    helper_dir = ROOT / "release_helpers"
    sys.path.insert(0, str(helper_dir))
    try:
        spec = importlib.util.spec_from_file_location("pkg2_installer_diagnostic", INSTALLER)
        assert spec is not None and spec.loader is not None
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
    finally:
        sys.path.remove(str(helper_dir))

    def fail_run(*args: object, **kwargs: object) -> None:
        raise subprocess.CalledProcessError(7, ["python"], stderr="pkg2-installer-inner-marker")

    monkeypatch.setattr(installer.subprocess, "run", fail_run)
    with pytest.raises(installer.ReleaseError) as exc_info:
        installer._run(["python"], cwd=tmp_path, env={}, message="outer failure")
    message = str(exc_info.value)
    assert "outer failure" in message
    assert "pkg2-installer-inner-marker" in message


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
def bundle() -> Iterator[Path]:
    with _pkg2_temp_root() as root:
        yield from _build_bundle_fixture(root)


def _build_bundle_fixture(root: Path) -> Iterator[Path]:
    builder = root / "build environment with spaces"
    build_home = root / "build home with spaces"
    build_env = _env(build_home)
    build_env["UV"] = str(root / "uv must not be used")
    _run([sys.executable, "-m", "venv", str(builder)], env=build_env)
    build_python = _venv_python(builder)
    # R124-09: Python 3.12+ venvs no longer bundle setuptools, and the
    # setuptools bundled with CPython 3.11 (68.x) cannot build a wheel without
    # the separate `wheel` package. The release build toolchain installs a
    # modern setuptools; mirror that here so the offline wheel build works on
    # every supported interpreter. `build`/`wheel` must STILL be absent so the
    # build is proven to use the pip+setuptools path only.
    installed = _run(
        [str(build_python), "-m", "pip", "install", "-q", "--upgrade", "setuptools"],
        env=build_env,
        cwd=builder,
        check=False,
    )
    if installed.returncode:
        raise AssertionError(f"setuptools install into build venv failed: {installed.stderr[-2000:]}")
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
    yield output


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
    assert manifest["version"] == VERSION
    assert set(manifest["payload_files"]) == {line.split("  ", 1)[1] for line in checksums.splitlines()}
    assert hashlib.sha256((bundle / "checksums.sha256").read_bytes()).hexdigest() == manifest["checksums_sha256"]
    assert not any(p.suffix in {".pdf", ".sqlite", ".jsonl", ".env"} for p in bundle.rglob("*"))


def test_fresh_offline_install_custom_xdg_and_cli(bundle: Path, pkg2_root: Path) -> None:
    result = _install(bundle, pkg2_root)
    assert result.returncode == 0
    home = pkg2_root / "home with spaces"
    runtime = home / "data root with spaces" / "zero-mem"
    bindir = home / "bin root with spaces"
    assert _is_directory_link(runtime / "current")
    assert (runtime / "runtimes" / VERSION / "venv").is_dir()
    cli = _cli(bindir)
    assert cli.is_file() and os.access(cli, os.X_OK)
    env = _env(home)
    assert _run(_cli_invocation(cli) + ["--help"], env=env, cwd=pkg2_root).returncode == 0
    assert _run(_cli_invocation(cli) + ["--version"], env=env, cwd=pkg2_root).stdout.strip() == f"zero-mem {VERSION}"
    imports = _run([str(_venv_python(runtime / "current" / "venv")), "-c", "import zero_mem, src; print(zero_mem.__version__)"], env=env, cwd=pkg2_root)
    assert imports.stdout.strip() == VERSION


def test_checksum_tampering_fails_before_activation(bundle: Path, pkg2_root: Path) -> None:
    payload = next((bundle / "wheels").glob("*.whl"))
    original = payload.read_bytes()
    try:
        payload.write_bytes(original + b"tamper")
        result = _install(bundle, pkg2_root, check=False)
    finally:
        payload.write_bytes(original)
    assert result.returncode != 0
    assert "checksum" in result.stderr.lower()
    runtime = pkg2_root / "home with spaces" / "data root with spaces" / "zero-mem"
    assert not (runtime / "current").exists()
    assert not (runtime / "current").is_symlink()


def test_interrupted_install_preserves_previous_active_runtime(bundle: Path, pkg2_root: Path) -> None:
    assert _install(bundle, pkg2_root).returncode == 0
    home = pkg2_root / "home with spaces"
    env = _env(home)
    runtime = home / "data root with spaces" / "zero-mem"
    before = (runtime / "current").resolve()
    result = _install(bundle, pkg2_root, extra_env={"ZERO_MEM_TEST_FAIL_BEFORE_ACTIVATION": "1"}, check=False)
    assert result.returncode != 0
    assert (runtime / "current").resolve() == before
    assert not list((runtime / "runtimes").glob(".staging-*"))
    assert _run([str(_venv_python(runtime / "current" / "venv")), "-m", "zero_mem.cli", "--version"], env=env, cwd=pkg2_root).stdout.strip() == f"zero-mem {VERSION}"


def test_same_version_reinstall_is_non_destructive(bundle: Path, pkg2_root: Path) -> None:
    _install(bundle, pkg2_root)
    home = pkg2_root / "home with spaces"
    runtime = home / "data root with spaces" / "zero-mem"
    sentinel = runtime / "user-data-sentinel"
    sentinel.write_text("preserve")
    before = (runtime / "current").resolve()
    assert _install(bundle, pkg2_root).returncode == 0
    assert (runtime / "current").resolve() == before
    assert sentinel.read_text() == "preserve"


def test_default_uninstall_preserves_user_data(bundle: Path, pkg2_root: Path) -> None:
    _install(bundle, pkg2_root)
    home = pkg2_root / "home with spaces"
    runtime = home / "data root with spaces" / "zero-mem"
    sentinel = runtime / "Memory" / "canonical.jsonl"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("synthetic canonical data")
    env = _env(home)
    result = _run([sys.executable, str(UNINSTALLER), "--non-interactive"], env=env, check=True)
    assert result.returncode == 0
    assert not (runtime / "current").exists()
    assert not _cli(home / "bin root with spaces").exists()
    assert sentinel.read_text() == "synthetic canonical data"


def test_uninstall_refuses_unsafe_active_symlink(bundle: Path, pkg2_root: Path) -> None:
    _install(bundle, pkg2_root)
    home = pkg2_root / "home with spaces"
    runtime = home / "data root with spaces" / "zero-mem"
    current = runtime / "current"
    _remove_directory_link(current)
    outside = pkg2_root / "outside"
    outside.mkdir()
    if os.name == "nt":
        _run(["cmd", "/c", "mklink", "/J", str(current), str(outside)], env=_env(home))
    else:
        current.symlink_to(outside, target_is_directory=True)
    result = _run([sys.executable, str(UNINSTALLER), "--non-interactive"], env=_env(home), check=False)
    assert result.returncode != 0
    assert "escapes" in result.stderr.lower()


def test_compatible_python_detection_and_rejection() -> None:
    from release_helpers.release_common import is_compatible_python

    assert is_compatible_python(sys.executable)
    assert not is_compatible_python("/definitely/missing/python")


def test_no_network_fallback_is_encoded_in_installer_source() -> None:
    text = INSTALLER.read_text()
    assert "--no-index" in text
    assert "--find-links" in text
    assert "pip install" not in text or "--no-index" in text
    assert "requests" not in text.lower()
    assert "input(" in text


def test_installer_has_no_repository_dependency(bundle: Path, pkg2_root: Path) -> None:
    result = _install(bundle, pkg2_root)
    assert result.returncode == 0
    home = pkg2_root / "home with spaces"
    venv = home / "data root with spaces" / "zero-mem" / "current" / "venv"
    env = _env(home)
    output = _run([str(_venv_python(venv)), "-c", "import zero_mem, src; print(zero_mem.__file__); print(src.__path__[0])"], env=env, cwd=pkg2_root).stdout
    assert str(ROOT) not in output


def test_pypdf_remains_optional(bundle: Path, pkg2_root: Path) -> None:
    _install(bundle, pkg2_root)
    home = pkg2_root / "home with spaces"
    python = _venv_python(home / "data root with spaces" / "zero-mem" / "current" / "venv")
    result = _run([str(python), "-c", "import importlib.util; print(importlib.util.find_spec('pypdf'))"], env=_env(home), cwd=pkg2_root)
    assert result.stdout.strip() == "None"


def test_installed_runtime_exposes_setup_doctor_and_wizard(bundle: Path, pkg2_root: Path) -> None:
    assert _install(bundle, pkg2_root).returncode == 0
    home = pkg2_root / "home with spaces"
    env = _env(home)
    cli = _cli(home / "bin root with spaces")
    setup = _run(_cli_invocation(cli) + ["setup"], env=env, cwd=pkg2_root)
    assert setup.stdout.strip() == "READY"
    doctor = _run(_cli_invocation(cli) + ["doctor", "--json"], env=env, cwd=pkg2_root)
    report = json.loads(doctor.stdout)
    assert report["overall"] == "READY"
    assert any(check["id"] == "hermes" and check["status"] == "WARN" for check in report["checks"])
    wizard = _run(
        _cli_invocation(cli) + ["wizard", "--non-interactive", "--skip-hermes", "--json"],
        env=env,
        cwd=pkg2_root,
    )
    wizard_report = json.loads(wizard.stdout)
    assert wizard_report["status"] == "READY"
    assert wizard_report["hermes"] == "SKIPPED"


def test_installed_runtime_upgrade_check_and_same_version_reinstall_preserve_state(bundle: Path, pkg2_root: Path) -> None:
    assert _install(bundle, pkg2_root).returncode == 0
    home = pkg2_root / "home with spaces"
    env = _env(home)
    cli = _cli(home / "bin root with spaces")
    assert _run(_cli_invocation(cli) + ["setup"], env=env, cwd=pkg2_root).returncode == 0
    data_root = home / "data root with spaces" / "zero-mem"
    canonical = data_root / "data" / "memory" / "traces" / "events-v1.jsonl"
    canonical.write_text('{"event_id":"pkg6-installed","event_type":"user_statement"}\n', encoding="utf-8")
    before = canonical.read_bytes()

    checked = json.loads(_run(_cli_invocation(cli) + ["upgrade", "--check", "--json"], env=env, cwd=pkg2_root).stdout)
    assert checked["status"] == "READY"
    assert checked["compatibility"] == "NO_MIGRATION_REQUIRED"
    assert canonical.read_bytes() == before
    upgraded = json.loads(_run(_cli_invocation(cli) + ["upgrade", "--json"], env=env, cwd=pkg2_root).stdout)
    assert upgraded["status"] == "SUCCESS"
    assert canonical.read_bytes() == before
    assert _install(bundle, pkg2_root).returncode == 0
    assert canonical.read_bytes() == before
    report = json.loads(_run([str(cli), "doctor", "--json"], env=env, cwd=pkg2_root).stdout)
    assert report["overall"] == "READY"
