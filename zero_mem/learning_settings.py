"""Owner-controlled settings of the learning harness (``settings.toml``; ADR-V170-03).

One TOML file under the zero-mem configuration directory (``paths.config_root()``; override with the environment
variable ``ZERO_MEM_SETTINGS``). It is parsed with :mod:`tomllib`, validated against a CLOSED schema (unknown tables,
keys or types are errors, never ignored) and every missing key has a safe default::

    [learning]
    mode = "suggest"              # off | suggest | auto_low_risk (accepted, but behaves as suggest: see TODO below)
    max_proposals_per_day = 20    # per proposing profile, UTC day
    allow_agent_proposals = true  # false: only source="user" proposals are accepted
    proposal_ttl_days = 30        # a pending proposal older than this is expired
    active_ttl_days = 0           # 0 = approved items never expire; otherwise they stop being returned (not deleted)

    [injection]                   # global default; precedence project > profile > global; kill switch beats all
    enabled = false
    max_chars = 2000              # 1..8000 (hard cap)
    types = ["rule", "decision", "gotcha"]   # subset of INJECTION_TYPES

    [injection.profiles."claude-code"]   # same keys, each optional (a missing key inherits)
    [injection.projects."my-project"]

    [safety]
    kill_switch = false           # true: no proposals, no approvals, no injection; reads of existing memory still work
    deny_patterns = []            # extra regexes; a proposal matching one is rejected

Fail SAFE: a file that cannot be read, is not valid TOML or violates the schema yields :meth:`Settings.failsafe` -
learning off, injection off, kill switch ON semantics for new proposals - and a doctor warning; it never raises into a
read path. TODO(auto_low_risk): the mode is reserved for a later phase; today it is validated and treated EXACTLY as
``suggest`` (nothing is ever auto-approved; see :attr:`Settings.effective_mode`).

Writes (``settings set/unset``) are atomic (temp file in the same directory + ``os.replace`` under the DEF-090
retry) and serialised across processes with a lock file. Zero dependencies, no network, no LLM.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping, NamedTuple, Optional, Sequence

from . import paths
from .provisioning import valid_id

SETTINGS_ENV = "ZERO_MEM_SETTINGS"
SETTINGS_FILENAME = "settings.toml"

LEARNING_MODES = ("off", "suggest", "auto_low_risk")
INJECTION_TYPES = ("rule", "decision", "gotcha", "workflow", "skill", "persona", "devlog")
DEFAULT_INJECTION_TYPES = ("rule", "decision", "gotcha")

DEFAULT_MAX_PROPOSALS_PER_DAY = 20
MAX_PROPOSALS_PER_DAY_LIMIT = 1000
DEFAULT_PROPOSAL_TTL_DAYS = 30
DEFAULT_INJECTION_MAX_CHARS = 2000
INJECTION_MAX_CHARS_HARD_CAP = 8000
TTL_DAYS_LIMIT = 3650
MAX_OVERRIDES = 200
MAX_DENY_PATTERNS = 50
MAX_DENY_PATTERN_CHARS = 200
MAX_DENY_SCAN_CHARS = 16384
MAX_SETTINGS_BYTES = 64 * 1024
_LOCK_TIMEOUT = 15.0

_OVERRIDE_KEYS = ("enabled", "max_chars", "types")
#: ``(group)+`` / ``(a*)*`` / ``(x{2,})+``: nested unbounded quantifiers, the classic catastrophic-backtracking shape.
_NESTED_QUANTIFIER = re.compile(r"\((?:[^()\\]|\\.)*(?:[+*]|\{\d+,\d*\})(?:[^()\\]|\\.)*\)\s*(?:[+*]|\{\d+,\d*\})")


class SettingsError(ValueError):
    """A settings value, key or file is invalid (the message is safe to show; it never echoes file content)."""


class InjectionPolicy(NamedTuple):
    """``resolve_injection`` result; unpacks as ``(enabled, max_chars, types)``."""

    enabled: bool
    max_chars: int
    types: tuple


@dataclass(frozen=True)
class InjectionOverride:
    enabled: Optional[bool] = None
    max_chars: Optional[int] = None
    types: Optional[tuple] = None

    def as_dict(self) -> dict:
        out: dict[str, Any] = {}
        if self.enabled is not None:
            out["enabled"] = self.enabled
        if self.max_chars is not None:
            out["max_chars"] = self.max_chars
        if self.types is not None:
            out["types"] = list(self.types)
        return out


@dataclass(frozen=True)
class Settings:
    mode: str = "suggest"
    max_proposals_per_day: int = DEFAULT_MAX_PROPOSALS_PER_DAY
    allow_agent_proposals: bool = True
    proposal_ttl_days: int = DEFAULT_PROPOSAL_TTL_DAYS
    active_ttl_days: int = 0
    injection_enabled: bool = False
    injection_max_chars: int = DEFAULT_INJECTION_MAX_CHARS
    injection_types: tuple = DEFAULT_INJECTION_TYPES
    profiles: Mapping[str, InjectionOverride] = field(default_factory=dict)
    projects: Mapping[str, InjectionOverride] = field(default_factory=dict)
    kill_switch: bool = False
    deny_patterns: tuple = ()
    #: False when the file could not be used: everything below is the fail-safe configuration.
    valid: bool = True
    error: Optional[str] = None

    # -- derived -----------------------------------------------------------------------------
    @property
    def effective_mode(self) -> str:
        """``auto_low_risk`` is reserved: it behaves as ``suggest`` (TODO: a later phase). Never auto-approves."""
        return "suggest" if self.mode == "auto_low_risk" else self.mode

    @property
    def learning_enabled(self) -> bool:
        """May new proposals be accepted at all (mode, kill switch and fail-safe)?"""
        return self.valid and not self.kill_switch and self.effective_mode != "off"

    @classmethod
    def failsafe(cls, error: str) -> "Settings":
        return cls(mode="off", injection_enabled=False, kill_switch=True, valid=False, error=error)

    def as_dict(self) -> dict:
        return {
            "learning": {
                "mode": self.mode,
                "max_proposals_per_day": self.max_proposals_per_day,
                "allow_agent_proposals": self.allow_agent_proposals,
                "proposal_ttl_days": self.proposal_ttl_days,
                "active_ttl_days": self.active_ttl_days,
            },
            "injection": {
                "enabled": self.injection_enabled,
                "max_chars": self.injection_max_chars,
                "types": list(self.injection_types),
                "profiles": {k: v.as_dict() for k, v in sorted(self.profiles.items())},
                "projects": {k: v.as_dict() for k, v in sorted(self.projects.items())},
            },
            "safety": {"kill_switch": self.kill_switch, "deny_patterns": list(self.deny_patterns)},
        }


# ---------------------------------------------------------------------------------------------
# location
# ---------------------------------------------------------------------------------------------
def settings_path() -> Path:
    """``$ZERO_MEM_SETTINGS`` or ``<config root>/settings.toml``."""
    explicit = (os.environ.get(SETTINGS_ENV) or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return paths.config_root() / SETTINGS_FILENAME


# ---------------------------------------------------------------------------------------------
# validation (closed schema)
# ---------------------------------------------------------------------------------------------
def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _int(value: Any, label: str, low: int, high: int) -> int:
    if not _is_int(value) or not low <= value <= high:
        raise SettingsError(f"{label} must be an integer between {low} and {high}")
    return value


def _bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise SettingsError(f"{label} must be true or false")
    return value


def _types(value: Any, label: str) -> tuple:
    if not isinstance(value, (list, tuple)) or len(value) > len(INJECTION_TYPES):
        raise SettingsError(f"{label} must be a list of memory types ({', '.join(INJECTION_TYPES)})")
    for item in value:
        if not isinstance(item, str) or item not in INJECTION_TYPES:
            raise SettingsError(f"{label} may only contain: {', '.join(INJECTION_TYPES)}")
    return tuple(dict.fromkeys(value))


def _closed(table: Any, label: str, allowed: Sequence[str]) -> dict:
    if not isinstance(table, dict):
        raise SettingsError(f"[{label}] must be a table")
    unknown = sorted(set(table) - set(allowed))
    if unknown:
        raise SettingsError(f"unknown key in [{label}]: {unknown[0]!r}")
    return table


def check_deny_pattern(pattern: Any) -> "re.Pattern[str]":
    """Compile one extra deny pattern safely (bounded length, no nested unbounded quantifiers)."""
    if not isinstance(pattern, str) or not pattern or len(pattern) > MAX_DENY_PATTERN_CHARS:
        raise SettingsError(f"a deny pattern must be a non-empty string of at most {MAX_DENY_PATTERN_CHARS} characters")
    if _NESTED_QUANTIFIER.search(pattern):
        raise SettingsError("a deny pattern with nested unbounded quantifiers is refused (catastrophic backtracking)")
    try:
        return re.compile(pattern, re.IGNORECASE | re.MULTILINE)
    except (re.error, RecursionError, OverflowError):
        raise SettingsError("a deny pattern is not a valid regular expression") from None


def _override(table: Any, label: str) -> InjectionOverride:
    table = _closed(table, label, _OVERRIDE_KEYS)
    return InjectionOverride(
        enabled=_bool(table["enabled"], f"{label}.enabled") if "enabled" in table else None,
        max_chars=_int(table["max_chars"], f"{label}.max_chars", 1, INJECTION_MAX_CHARS_HARD_CAP)
        if "max_chars" in table else None,
        types=_types(table["types"], f"{label}.types") if "types" in table else None,
    )


def _overrides(table: Any, label: str) -> dict:
    if not isinstance(table, dict):
        raise SettingsError(f"[{label}] must be a table")
    if len(table) > MAX_OVERRIDES:
        raise SettingsError(f"[{label}] has more than {MAX_OVERRIDES} entries")
    out = {}
    for name, body in table.items():
        if not valid_id(name):
            raise SettingsError(f"[{label}] names must match [A-Za-z0-9][A-Za-z0-9._-]{{0,63}}")
        out[name] = _override(body, f"{label}.{name}")
    return out


def parse_settings(raw: Mapping[str, Any]) -> Settings:
    """Validate a parsed TOML document (closed schema) and fill the defaults. Raises :class:`SettingsError`."""
    raw = _closed(dict(raw), "root", ("learning", "injection", "safety"))
    learning = _closed(raw.get("learning", {}), "learning", (
        "mode", "max_proposals_per_day", "allow_agent_proposals", "proposal_ttl_days", "active_ttl_days"))
    injection = _closed(raw.get("injection", {}), "injection", ("enabled", "max_chars", "types", "profiles", "projects"))
    safety = _closed(raw.get("safety", {}), "safety", ("kill_switch", "deny_patterns"))
    mode = learning.get("mode", "suggest")
    if not isinstance(mode, str) or mode not in LEARNING_MODES:
        raise SettingsError("learning.mode must be one of: " + ", ".join(LEARNING_MODES))
    patterns = safety.get("deny_patterns", [])
    if not isinstance(patterns, list) or len(patterns) > MAX_DENY_PATTERNS:
        raise SettingsError(f"safety.deny_patterns must be a list of at most {MAX_DENY_PATTERNS} patterns")
    for pattern in patterns:
        check_deny_pattern(pattern)
    return Settings(
        mode=mode,
        max_proposals_per_day=_int(learning.get("max_proposals_per_day", DEFAULT_MAX_PROPOSALS_PER_DAY),
                                   "learning.max_proposals_per_day", 0, MAX_PROPOSALS_PER_DAY_LIMIT),
        allow_agent_proposals=_bool(learning.get("allow_agent_proposals", True), "learning.allow_agent_proposals"),
        proposal_ttl_days=_int(learning.get("proposal_ttl_days", DEFAULT_PROPOSAL_TTL_DAYS),
                               "learning.proposal_ttl_days", 1, TTL_DAYS_LIMIT),
        active_ttl_days=_int(learning.get("active_ttl_days", 0), "learning.active_ttl_days", 0, TTL_DAYS_LIMIT),
        injection_enabled=_bool(injection.get("enabled", False), "injection.enabled"),
        injection_max_chars=_int(injection.get("max_chars", DEFAULT_INJECTION_MAX_CHARS), "injection.max_chars",
                                 1, INJECTION_MAX_CHARS_HARD_CAP),
        injection_types=_types(injection.get("types", list(DEFAULT_INJECTION_TYPES)), "injection.types"),
        profiles=_overrides(injection.get("profiles", {}), "injection.profiles"),
        projects=_overrides(injection.get("projects", {}), "injection.projects"),
        kill_switch=_bool(safety.get("kill_switch", False), "safety.kill_switch"),
        deny_patterns=tuple(patterns),
    )


# ---------------------------------------------------------------------------------------------
# reading (never raises: invalid -> fail-safe)
# ---------------------------------------------------------------------------------------------
def read_raw(path: Path) -> Optional[dict]:
    """The parsed document, ``None`` when the file does not exist. Raises :class:`SettingsError` when unusable."""
    try:
        if not path.exists():
            return None
        if not path.is_file():
            raise SettingsError("settings path is not a regular file")
        with open(path, "rb") as handle:
            data = handle.read(MAX_SETTINGS_BYTES + 1)
    except SettingsError:
        raise
    except OSError:
        raise SettingsError("settings file is unreadable") from None
    if len(data) > MAX_SETTINGS_BYTES:
        raise SettingsError("settings file is too large")
    try:
        return tomllib.loads(data.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError):
        raise SettingsError("settings file is not valid TOML (UTF-8)") from None


_CACHE: dict[Path, tuple[tuple, Settings]] = {}


def _fingerprint(path: Path) -> Optional[tuple]:
    try:
        info = os.stat(path)
    except OSError:
        return None
    return info.st_mtime_ns, info.st_size, getattr(info, "st_ino", 0)


def load_settings(path: Optional[Path] = None) -> Settings:
    """Effective settings; a missing file gives the defaults, an unusable one the fail-safe configuration."""
    target = Path(path) if path is not None else settings_path()
    fingerprint = _fingerprint(target)
    if fingerprint is not None:
        cached = _CACHE.get(target)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]
    try:
        raw = read_raw(target)
        result = Settings() if raw is None else parse_settings(raw)
    except SettingsError as exc:
        result = Settings.failsafe(str(exc))
    except Exception:  # noqa: BLE001 - a read path must never crash on a settings problem
        result = Settings.failsafe("settings could not be loaded")
    if fingerprint is not None and fingerprint == _fingerprint(target):
        if len(_CACHE) > 16:
            _CACHE.clear()
        _CACHE[target] = (fingerprint, result)
    return result


def compile_deny_patterns(settings: Settings) -> list:
    out = []
    for pattern in settings.deny_patterns:
        try:
            out.append(check_deny_pattern(pattern))
        except SettingsError:
            continue
    return out


def matches_deny_pattern(settings: Settings, *texts: str) -> bool:
    """True when any (bounded) text matches an extra deny pattern."""
    compiled = compile_deny_patterns(settings)
    if not compiled:
        return False
    for text in texts:
        if not text:
            continue
        bounded = text[:MAX_DENY_SCAN_CHARS]
        if any(p.search(bounded) for p in compiled):
            return True
    return False


# ---------------------------------------------------------------------------------------------
# precedence
# ---------------------------------------------------------------------------------------------
def resolve_injection(profile: Optional[str] = None, project: Optional[str] = None,
                      settings: Optional[Settings] = None) -> InjectionPolicy:
    """``(enabled, max_chars, types)`` that applies to ``profile`` working on ``project``.

    Precedence, evaluated per field: ``[injection.projects.<project>]`` > ``[injection.profiles.<profile>]`` >
    ``[injection]`` (global) > built-in defaults (disabled, 2000 chars, rule/decision/gotcha). A field a more specific
    table does not set is inherited. ``[safety] kill_switch`` and the fail-safe (unusable settings file) override
    everything: ``(False, 0, ())``. ``max_chars`` never exceeds the hard cap of 8000.
    """
    cfg = settings if settings is not None else load_settings()
    if cfg.kill_switch or not cfg.valid:
        return InjectionPolicy(False, 0, ())
    enabled, max_chars, types = cfg.injection_enabled, cfg.injection_max_chars, cfg.injection_types
    layers = []
    if profile is not None and profile in cfg.profiles:
        layers.append(cfg.profiles[profile])
    if project is not None and project in cfg.projects:
        layers.append(cfg.projects[project])  # applied last: the most specific wins
    for layer in layers:
        if layer.enabled is not None:
            enabled = layer.enabled
        if layer.max_chars is not None:
            max_chars = layer.max_chars
        if layer.types is not None:
            types = layer.types
    return InjectionPolicy(bool(enabled), min(int(max_chars), INJECTION_MAX_CHARS_HARD_CAP), tuple(types))


# ---------------------------------------------------------------------------------------------
# dotted keys (settings set / unset)
# ---------------------------------------------------------------------------------------------
_SCALAR_KEYS = {
    "learning.mode": "mode", "learning.max_proposals_per_day": "int", "learning.allow_agent_proposals": "bool",
    "learning.proposal_ttl_days": "int", "learning.active_ttl_days": "int",
    "injection.enabled": "bool", "injection.max_chars": "int", "injection.types": "types",
    "safety.kill_switch": "bool", "safety.deny_patterns": "patterns",
}
KNOWN_KEYS = tuple(_SCALAR_KEYS) + (
    "injection.profiles.<name>.<enabled|max_chars|types>", "injection.projects.<name>.<enabled|max_chars|types>")


def _split_key(key: str) -> tuple:
    """``("learning", "mode")`` or ``("injection", "profiles", name, field)`` (names may contain dots)."""
    if not isinstance(key, str) or not key.strip():
        raise SettingsError("key must not be empty")
    key = key.strip()
    if key in _SCALAR_KEYS:
        return tuple(key.split("."))
    for table in ("profiles", "projects"):
        prefix = f"injection.{table}."
        if key.startswith(prefix):
            rest = key[len(prefix):]
            name, dot, last = rest.rpartition(".")
            if dot and last in _OVERRIDE_KEYS and name:
                return ("injection", table, name, last)
            if rest and not dot:
                return ("injection", table, rest)  # a whole override (unset only)
            if rest and last not in _OVERRIDE_KEYS:
                return ("injection", table, rest)
    raise SettingsError("unknown key; known keys: " + ", ".join(KNOWN_KEYS))


def _parse_value(kind: str, text: str) -> Any:
    if kind == "bool":
        lowered = text.strip().lower()
        if lowered in ("true", "1", "yes", "on"):
            return True
        if lowered in ("false", "0", "no", "off"):
            return False
        raise SettingsError("value must be true or false")
    if kind == "int":
        try:
            return int(text.strip())
        except ValueError:
            raise SettingsError("value must be an integer") from None
    if kind == "mode":
        return text.strip()
    if kind == "types":
        stripped = text.strip()
        if stripped.startswith("["):
            try:
                value = json.loads(stripped)
            except ValueError:
                raise SettingsError("value must be a JSON list or comma-separated types") from None
            if not isinstance(value, list):
                raise SettingsError("value must be a JSON list or comma-separated types")
            return value
        return [part.strip() for part in stripped.split(",") if part.strip()]
    if kind == "patterns":
        try:
            value = json.loads(text)
        except ValueError:
            raise SettingsError('value must be a JSON list of strings, e.g. ["internal-host-\\\\d+"]') from None
        if not isinstance(value, list):
            raise SettingsError("value must be a JSON list of strings")
        return value
    raise SettingsError("unsupported key")  # pragma: no cover


def apply_set(raw: Optional[Mapping[str, Any]], key: str, value_text: str) -> dict:
    """A copy of ``raw`` with ``key`` set to the parsed ``value_text`` (validated by the caller via parse_settings)."""
    parts = _split_key(key)
    doc = json.loads(json.dumps(raw or {}))
    if len(parts) == 2:
        kind = _SCALAR_KEYS[".".join(parts)]
        doc.setdefault(parts[0], {})[parts[1]] = _parse_value(kind, value_text)
    elif len(parts) == 4:
        kind = {"enabled": "bool", "max_chars": "int", "types": "types"}[parts[3]]
        doc.setdefault("injection", {}).setdefault(parts[1], {}).setdefault(parts[2], {})[parts[3]] = \
            _parse_value(kind, value_text)
    else:
        raise SettingsError("set a field: injection.%s.<name>.<enabled|max_chars|types>" % parts[1])
    return doc


def apply_unset(raw: Optional[Mapping[str, Any]], key: str) -> tuple:
    """``(new document, removed?)``; empty tables are dropped."""
    parts = _split_key(key)
    doc = json.loads(json.dumps(raw or {}))
    node = doc
    for part in parts[:-1]:
        node = node.get(part)
        if not isinstance(node, dict):
            return doc, False
    if parts[-1] not in node:
        return doc, False
    del node[parts[-1]]
    for depth in range(len(parts) - 1, 0, -1):  # prune empty parents bottom-up
        parent = doc
        for part in parts[: depth - 1]:
            parent = parent[part]
        if isinstance(parent.get(parts[depth - 1]), dict) and not parent[parts[depth - 1]]:
            del parent[parts[depth - 1]]
    return doc, True


# ---------------------------------------------------------------------------------------------
# writing (atomic)
# ---------------------------------------------------------------------------------------------
def _toml_string(value: str) -> str:
    out = ['"']
    for ch in value:
        code = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif code < 0x20 or code == 0x7F:
            out.append(f"\\u{code:04X}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise SettingsError("unsupported value")  # pragma: no cover - the schema only has bool/int/str/list


def render_toml(doc: Mapping[str, Any]) -> str:
    """Deterministic TOML for the closed schema (table names are always quoted: profile ids may contain dots)."""
    lines: list[str] = [
        "# zero-mem learning-harness settings (see docs/runbooks/learning-harness.md).",
        "# Managed by `zero-mem settings`; comments you add by hand are not preserved when it rewrites the file.",
    ]

    def emit(header: str, table: Mapping[str, Any]) -> None:
        scalars = {k: v for k, v in table.items() if not isinstance(v, dict)}
        if scalars or not any(isinstance(v, dict) for v in table.values()):
            lines.append("")
            lines.append(f"[{header}]")
            for k in sorted(scalars):
                lines.append(f"{k} = {_toml_value(scalars[k])}")

    for section in ("learning", "injection", "safety"):
        table = doc.get(section)
        if not isinstance(table, dict):
            continue
        emit(section, table)
        if section == "injection":
            for group in ("profiles", "projects"):
                members = table.get(group)
                if isinstance(members, dict):
                    for name in sorted(members):
                        emit(f"injection.{group}.{_toml_string(name)}", members[name])
    return "\n".join(lines) + "\n"


@contextlib.contextmanager
def _settings_lock(path: Path) -> Iterator[None]:
    from src.storage.coordination import locked

    try:
        paths.ensure_private_dir(path.parent, "configuration directory")
    except (paths.SetupError, paths.ConfigurationError):
        raise SettingsError("configuration directory is unusable") from None
    try:
        with locked(path.with_name(path.name + ".lock"), mode="exclusive", timeout=_LOCK_TIMEOUT):
            yield
    except SettingsError:
        raise
    except OSError:
        raise SettingsError("settings file is locked by another process") from None


def write_settings(path: Path, doc: Mapping[str, Any]) -> None:
    """Validate ``doc`` then write it atomically (temp file in the same directory, fsync, retrying replace)."""
    from src.corpus._fsretry import retry_transient

    parse_settings(doc)  # never persist something the reader would reject
    payload = render_toml(doc).encode("utf-8")
    tomllib.loads(payload.decode("utf-8"))  # the serializer's own output must round-trip
    path = Path(path)
    try:
        paths.ensure_private_dir(path.parent, "configuration directory")
    except (paths.SetupError, paths.ConfigurationError):
        raise SettingsError("configuration directory is unusable") from None
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        retry_transient(lambda: os.replace(temporary, path))
    except OSError:
        raise SettingsError("cannot write the settings file") from None
    finally:
        with contextlib.suppress(OSError):
            os.unlink(temporary)


def set_value(key: str, value_text: str, path: Optional[Path] = None) -> Settings:
    """Set one dotted key (validated as a whole); returns the new effective settings."""
    target = Path(path) if path is not None else settings_path()
    with _settings_lock(target):
        doc = apply_set(read_raw(target), key, value_text)
        write_settings(target, doc)
    return load_settings(target)


def unset_value(key: str, path: Optional[Path] = None) -> tuple:
    """Remove one dotted key. Returns ``(settings, removed)``."""
    target = Path(path) if path is not None else settings_path()
    with _settings_lock(target):
        doc, removed = apply_unset(read_raw(target), key)
        if removed:
            write_settings(target, doc)
    return load_settings(target), removed


__all__ = [
    "DEFAULT_INJECTION_TYPES", "INJECTION_MAX_CHARS_HARD_CAP", "INJECTION_TYPES", "InjectionOverride",
    "InjectionPolicy", "KNOWN_KEYS", "LEARNING_MODES", "SETTINGS_ENV", "SETTINGS_FILENAME", "Settings", "SettingsError",
    "apply_set", "apply_unset", "check_deny_pattern", "load_settings", "matches_deny_pattern", "parse_settings",
    "read_raw", "render_toml", "resolve_injection", "set_value", "settings_path", "unset_value", "write_settings",
]
