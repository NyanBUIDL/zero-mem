"""Stdlib-only safety helpers for the PKG-2 release layer."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

MANIFEST_NAME = "manifest.json"
CHECKSUMS_NAME = "checksums.sha256"


class ReleaseError(RuntimeError):
    """Sanitized release-layer failure."""


def fail(message: str) -> ReleaseError:
    return ReleaseError(message)


def _interpreter_info(executable: str | Path) -> tuple[str, tuple[int, int]] | None:
    import subprocess

    probe = [str(executable), "-c", "import sys; print(sys.implementation.name); print(sys.version_info[:2])"]
    try:
        result = subprocess.run(probe, check=True, capture_output=True, text=True, timeout=10)
        lines = result.stdout.strip().splitlines()
        implementation = lines[0]
        major, minor = ast.literal_eval(lines[1])
        return implementation, (int(major), int(minor))
    except Exception:
        return None


def is_compatible_python(executable: str | Path | None = None) -> bool:
    if executable is None:
        return sys.implementation.name == "cpython" and (3, 11) <= sys.version_info[:2] < (3, 14)
    info = _interpreter_info(executable)
    if info is None:
        return False
    implementation, version = info
    return implementation == "cpython" and (3, 11) <= version < (3, 14)


def require_compatible_python(executable: str | Path | None = None) -> None:
    if not is_compatible_python(executable):
        raise fail("compatible CPython required: CPython >=3.11,<3.14")


def absolute_path(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() or path == Path("/"):
        raise fail(f"unsafe {label}")
    return path


def reject_home_or_root(path: Path, home: Path, label: str) -> None:
    if path == Path("/") or path.resolve() == home.resolve():
        raise fail(f"unsafe {label}")


def check_no_symlink_components(path: Path, *, label: str) -> None:
    current = Path(path.anchor) if path.is_absolute() else Path()
    for part in path.parts[1:] if path.is_absolute() else path.parts:
        current /= part
        if current.is_symlink():
            raise fail(f"unsafe symlink in {label}")


def ensure_managed_root(path: Path, *, home: Path, label: str) -> Path:
    path = absolute_path(path, label)
    reject_home_or_root(path, home, label)
    check_no_symlink_components(path, label=label)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise fail(f"unsafe {label}")
    return path


def contained(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def managed_child(root: Path, relative: str, *, label: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or not rel.parts or any(part in {"", ".", ".."} for part in rel.parts):
        raise fail(f"unsafe managed {label}")
    result = root.joinpath(*rel.parts)
    if not contained(root, result):
        raise fail(f"unsafe managed {label}")
    check_no_symlink_components(result, label=label)
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise fail(f"invalid {label}") from exc
    if not isinstance(value, dict):
        raise fail(f"invalid {label}")
    return value


def verify_bundle(bundle: Path) -> tuple[dict, dict[str, Path]]:
    bundle = bundle.resolve()
    if not bundle.is_dir() or bundle.is_symlink():
        raise fail("invalid release bundle")
    manifest_path = bundle / MANIFEST_NAME
    checksums_path = bundle / CHECKSUMS_NAME
    manifest = load_json(manifest_path, "release manifest")
    if manifest.get("schema_version") != 1 or manifest.get("version") != "1.2.4":
        raise fail("unsupported release manifest")
    if manifest.get("platform") != "linux-x86_64":
        raise fail("unsupported release bundle platform")
    try:
        if sha256_file(checksums_path) != manifest["checksums_sha256"]:
            raise fail("release checksum inventory mismatch")
    except (KeyError, OSError) as exc:
        raise fail("invalid release checksum inventory") from exc
    entries = manifest.get("payload_files")
    if not isinstance(entries, list) or not entries:
        raise fail("release manifest has no payload")
    inventory: dict[str, str] = {}
    try:
        lines = checksums_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise fail("invalid release checksum inventory") from exc
    for line in lines:
        fields = line.split("  ", 1)
        if len(fields) != 2 or len(fields[0]) != 64 or any(c not in "0123456789abcdef" for c in fields[0]):
            raise fail("invalid release checksum inventory")
        inventory[fields[1]] = fields[0]
    parsed: dict[str, Path] = {}
    for name in entries:
        relative = Path(name) if isinstance(name, str) else Path("/")
        if (
            not isinstance(name, str)
            or relative.is_absolute()
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
            or relative.as_posix() != name
            or (len(relative.parts) == 2 and relative.parts[0] != "wheels")
            or (len(relative.parts) not in {1, 2})
        ):
            raise fail("unsafe release payload path")
        payload = bundle / name
        if payload.is_symlink() or not payload.is_file() or not contained(bundle, payload):
            raise fail("invalid release payload")
        if inventory.get(name) != sha256_file(payload):
            raise fail("release payload checksum mismatch")
        parsed[name] = payload
    wheel = manifest.get("wheel")
    if not isinstance(wheel, str) or wheel not in parsed or not wheel.endswith(".whl"):
        raise fail("release wheel missing")
    return manifest, parsed


def atomic_write(path: Path, data: bytes, mode: int = 0o700) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def env_path(name: str, fallback: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else fallback


def default_paths() -> tuple[Path, Path]:
    home = Path.home().resolve()
    return (
        env_path("XDG_DATA_HOME", home / ".local" / "share") / "zero-mem",
        env_path("XDG_BIN_HOME", home / ".local" / "bin"),
    )


def script_bytes(runtime_root: Path) -> bytes:
    python = runtime_root / "current" / "venv" / "bin" / "python"
    quoted = "'" + str(python).replace("'", "'\\''") + "'"
    return ("#!/bin/sh\nset -eu\nexec " + quoted + " -m zero_mem.cli \"$@\"\n").encode("utf-8")
