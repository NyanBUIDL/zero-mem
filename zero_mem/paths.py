"""PKG-3 user-local paths and configuration contract."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .version import __version__

CONFIG_SCHEMA_VERSION = 1
CONFIG_FILENAME = "config.json"
MEMORY_STREAM_RELATIVE = Path("data/memory/traces/events-v1.jsonl")
DERIVED_DB_RELATIVE = Path("data/derived/memory.sqlite3")


class SetupError(RuntimeError):
    """Sanitized first-run setup failure."""


class ConfigurationError(RuntimeError):
    """Sanitized configuration failure."""


def _xdg_path(name: str, fallback: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else fallback


def data_root() -> Path:
    return _xdg_path("XDG_DATA_HOME", Path.home() / ".local" / "share") / "zero-mem"


def config_root() -> Path:
    return _xdg_path("XDG_CONFIG_HOME", Path.home() / ".config") / "zero-mem"


def state_root() -> Path:
    return _xdg_path("XDG_STATE_HOME", Path.home() / ".local" / "state") / "zero-mem"


def cache_root() -> Path:
    return _xdg_path("XDG_CACHE_HOME", Path.home() / ".cache") / "zero-mem"


def memory_root() -> Path:
    return data_root() / "data" / "memory"


def memory_stream() -> Path:
    return data_root() / MEMORY_STREAM_RELATIVE


def derived_root() -> Path:
    return data_root() / "data" / "derived"


def derived_db() -> Path:
    return data_root() / DERIVED_DB_RELATIVE


def config_path() -> Path:
    return config_root() / CONFIG_FILENAME


def expected_config() -> dict[str, Any]:
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "version": __version__,
        "capture_mode": "observation_only",
        "canonical_memory_root": str(memory_root()),
        "derived_store": str(derived_db()),
        "capture_stream": str(memory_stream()),
    }


def _reject_symlink(path: Path, label: str) -> None:
    current = Path(path.anchor) if path.is_absolute() else Path()
    parts = path.parts[1:] if path.is_absolute() else path.parts
    for part in parts:
        current /= part
        if current.is_symlink():
            raise SetupError(f"unsafe {label}")


def ensure_private_dir(path: Path, label: str) -> None:
    _reject_symlink(path, label)
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not path.is_dir():
            raise SetupError(f"invalid {label}")
        if os.name != "nt":
            os.chmod(path, 0o700)
    except SetupError:
        raise
    except OSError:
        raise SetupError(f"inaccessible {label}") from None


def _validate_config(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigurationError("configuration must be an object")
    if value.get("schema_version") != CONFIG_SCHEMA_VERSION:
        raise ConfigurationError("unsupported configuration")
    required = {
        "version",
        "capture_mode",
        "canonical_memory_root",
        "derived_store",
        "capture_stream",
    }
    if set(value) != required | {"schema_version"}:
        raise ConfigurationError("unsupported configuration fields")
    if value.get("version") != __version__ or value.get("capture_mode") != "observation_only":
        raise ConfigurationError("invalid configuration values")
    for key in ("canonical_memory_root", "derived_store", "capture_stream"):
        candidate = value.get(key)
        if not isinstance(candidate, str) or not Path(candidate).is_absolute():
            raise ConfigurationError("configuration path is not absolute")
    if value["canonical_memory_root"] != str(memory_root()):
        raise ConfigurationError("configuration memory path mismatch")
    if value["derived_store"] != str(derived_db()):
        raise ConfigurationError("configuration derived path mismatch")
    if value["capture_stream"] != str(memory_stream()):
        raise ConfigurationError("configuration capture path mismatch")
    return value


def load_config(*, required: bool = True) -> dict[str, Any] | None:
    path = config_path()
    if not path.exists():
        if required:
            raise ConfigurationError("configuration missing")
        return None
    _reject_symlink(path, "configuration")
    if not path.is_file():
        raise ConfigurationError("configuration is not a file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise ConfigurationError("configuration is malformed") from None
    return _validate_config(value)


def write_config() -> None:
    path = config_path()
    ensure_private_dir(path.parent, "configuration directory")
    if path.exists() or path.is_symlink():
        _reject_symlink(path, "configuration")
        _validate_config(json.loads(path.read_text(encoding="utf-8")))
        return
    payload = (json.dumps(expected_config(), indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{CONFIG_FILENAME}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except OSError:
        raise SetupError("unable to write configuration") from None
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def ensure_empty_memory_stream() -> None:
    path = memory_stream()
    _reject_symlink(path, "canonical memory stream")
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not path.exists():
            path.touch(mode=0o600)
        if not path.is_file():
            raise SetupError("invalid canonical memory stream")
        if os.name != "nt":
            os.chmod(path, 0o600)
    except SetupError:
        raise
    except OSError:
        raise SetupError("inaccessible canonical memory stream") from None
