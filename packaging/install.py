#!/usr/bin/env python3
"""PKG-2 user-local offline installer."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from release_common import (
    absolute_path,
    atomic_write,
    contained,
    default_paths,
    ensure_managed_root,
    fail,
    managed_child,
    reject_home_or_root,
    require_compatible_python,
    script_bytes,
    sha256_file,
    verify_bundle,
    ReleaseError,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install Zero-Mem from local bundle files only.")
    parser.add_argument("--bundle", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--bin-dir", type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--non-interactive", action="store_true")
    return parser


def _run(command: list[str], *, cwd: Path, env: dict[str, str], message: str) -> None:
    try:
        subprocess.run(command, cwd=cwd, env=env, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise fail(message) from exc


def _runtime_python(venv: Path) -> Path:
    return venv / "bin" / "python"


def _paths(args: argparse.Namespace) -> tuple[Path, Path]:
    default_runtime, default_bin = default_paths()
    runtime = absolute_path(args.runtime_root or default_runtime, "runtime root")
    bindir = absolute_path(args.bin_dir or default_bin, "binary root")
    home = Path.home().resolve()
    reject_home_or_root(runtime, home, "runtime root")
    reject_home_or_root(bindir, home, "binary root")
    return runtime, bindir


def _verify_runtime(venv: Path, version: str, cwd: Path) -> None:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    code = (
        "import importlib.metadata as m, zero_mem, src; "
        f"assert zero_mem.__version__ == {version!r}; "
        f"assert m.version('zero-mem') == {version!r}"
    )
    _run([str(_runtime_python(venv)), "-c", code], cwd=cwd, env=env, message="installed runtime verification failed")
    _run([str(venv / "bin" / "zero-mem"), "--version"], cwd=cwd, env=env, message="installed CLI verification failed")


def _check_active_pointer(runtime_root: Path) -> None:
    current = runtime_root / "current"
    if not current.exists() and not current.is_symlink():
        return
    if not current.is_symlink():
        raise fail("active runtime pointer is not a symlink")
    target = (current.parent / os.readlink(current)).resolve()
    if not contained(runtime_root / "runtimes", target):
        raise fail("active runtime pointer escapes managed root")


def install(args: argparse.Namespace) -> int:
    bundle = absolute_path(args.bundle, "release bundle").resolve()
    manifest, payloads = verify_bundle(bundle)
    version = manifest["version"]
    wheel = payloads[manifest["wheel"]]
    require_compatible_python(args.python or sys.executable)
    runtime_root, bin_dir = _paths(args)
    home = Path.home().resolve()
    runtime_root = ensure_managed_root(runtime_root, home=home, label="runtime root")
    runtimes = managed_child(runtime_root, "runtimes", label="runtime directory")
    runtimes.mkdir(parents=True, exist_ok=True, mode=0o700)
    if runtimes.is_symlink():
        raise fail("unsafe runtime directory")
    version_root = managed_child(runtimes, version, label="version runtime")
    _check_active_pointer(runtime_root)
    current = runtime_root / "current"
    controlled_failure = os.environ.get("ZERO_MEM_TEST_FAIL_BEFORE_ACTIVATION") == "1"
    active_same = current.is_symlink() and current.resolve() == version_root.resolve() and version_root.is_dir()
    for candidate in runtimes.iterdir():
        if candidate.name.startswith(".staging-"):
            if candidate.is_symlink():
                raise fail("unsafe staging symlink")
            shutil.rmtree(candidate)
    if active_same and not controlled_failure:
        return 0
    if (version_root.exists() or version_root.is_symlink()) and not active_same:
        raise fail("same-version runtime exists but is not active; refusing overwrite")

    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=str(runtimes)))
    previous_current = os.readlink(current) if current.is_symlink() else None
    previous_shim = None
    previous_metadata = None
    shim = None
    metadata_path = None
    pointer_changed = False
    runtime_moved = False
    try:
        staged_venv = staging / "venv"
        python = Path(args.python).resolve() if args.python else Path(sys.executable).resolve()
        _run([str(python), "-m", "venv", str(staged_venv)], cwd=bundle, env=dict(os.environ), message="unable to create managed virtual environment")
        pip = [str(_runtime_python(staged_venv)), "-m", "pip"]
        _run(
            pip + ["install", "--no-index", "--no-deps", "--find-links", str(bundle / "wheels"), str(wheel)],
            cwd=bundle,
            env={**os.environ, "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"},
            message="offline wheel installation failed",
        )
        _verify_runtime(staged_venv, version, bundle)
        if controlled_failure:
            raise fail("controlled pre-activation failure")
        bin_dir = ensure_managed_root(bin_dir, home=home, label="binary root")
        shim = managed_child(bin_dir, "zero-mem", label="CLI shim")
        shim_data = script_bytes(runtime_root)
        if shim.exists() or shim.is_symlink():
            if shim.is_symlink() or shim.read_bytes() != shim_data:
                raise fail("existing zero-mem command is not owned by Zero-Mem")
            previous_shim = shim.read_bytes()
        metadata_path = managed_child(runtime_root, "install.json", label="installation metadata")
        if metadata_path.exists():
            if metadata_path.is_symlink() or not metadata_path.is_file():
                raise fail("unsafe installation metadata")
            previous_metadata = metadata_path.read_bytes()
        metadata = {"schema_version": 1, "version": version, "runtime": f"runtimes/{version}", "wheel_sha256": sha256_file(wheel)}
        metadata_data = (json.dumps(metadata, sort_keys=True) + "\n").encode("utf-8")

        # Prepare every fallible artifact before changing the active pointer.
        shim_tmp = bin_dir / ".zero-mem.tmp"
        metadata_tmp = runtime_root / ".install.json.tmp"
        if shim_tmp.exists() or shim_tmp.is_symlink() or metadata_tmp.exists() or metadata_tmp.is_symlink():
            raise fail("stale installer temporary file")
        atomic_write(shim_tmp, shim_data, mode=0o755)
        atomic_write(metadata_tmp, metadata_data, mode=0o600)
        os.replace(staging, version_root)
        runtime_moved = True

        pointer_tmp = runtime_root / ".current.tmp"
        if pointer_tmp.exists() or pointer_tmp.is_symlink():
            raise fail("stale activation pointer")
        os.symlink(Path("runtimes") / version, pointer_tmp)
        os.replace(pointer_tmp, current)
        pointer_changed = True
        os.replace(shim_tmp, shim)
        os.replace(metadata_tmp, metadata_path)
        return 0
    except Exception:
        if pointer_changed:
            if current.exists() or current.is_symlink():
                current.unlink()
            if previous_current is not None:
                os.symlink(previous_current, current)
        if shim is not None:
            if previous_shim is None and (shim.exists() or shim.is_symlink()):
                shim.unlink()
            elif previous_shim is not None:
                atomic_write(shim, previous_shim, mode=0o755)
        if metadata_path is not None:
            if previous_metadata is None and (metadata_path.exists() or metadata_path.is_symlink()):
                metadata_path.unlink()
            elif previous_metadata is not None:
                atomic_write(metadata_path, previous_metadata, mode=0o600)
        if staging.exists() or staging.is_symlink():
            shutil.rmtree(staging, ignore_errors=True)
        if runtime_moved and (version_root.exists() or version_root.is_symlink()):
            shutil.rmtree(version_root, ignore_errors=True)
        for temporary in (bin_dir / ".zero-mem.tmp", runtime_root / ".install.json.tmp", runtime_root / ".current.tmp"):
            if temporary.exists() or temporary.is_symlink():
                temporary.unlink()
        raise


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if not args.non_interactive and sys.stdin.isatty():
            print("Zero-Mem PKG-2 installer: local offline bundle")
            print(f"Bundle: {Path(args.bundle).resolve()}")
            answer = input("Install the managed user-local runtime? [y/N] ").strip().lower()
            if answer not in {"y", "yes"}:
                print("Installation cancelled.")
                return 0
        return install(args)
    except ReleaseError as exc:
        print(f"zero-mem: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
