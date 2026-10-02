"""Named memories on one machine: the registry (``memories.toml``), the data-root selection and the operations.

A *memory* is one zero-mem data root. The registry maps ``NAME -> absolute data root`` so an owner can keep several
memories (work, personal, one per client) and point each agent at exactly one of them. The implicit memory ``default``
is whatever ``ZERO_MEM_DATA_ROOT`` / the XDG default says today; it always exists and is never stored in the registry.

Registry file: ``memories.toml`` in :func:`zero_mem.paths.config_root` (override: ``ZERO_MEM_MEMORIES``)::

    schema_version = 1
    default = "work"            # optional: the memory `zero-mem memory use` selected

    [memories.work]
    path = "/home/me/mem/work"  # absolute, always written with "/"
    description = "client work" # optional
    created_at = "2026-10-02T09:00:00Z"

The schema is closed (unknown keys are an error). Writes are atomic (temp file + fsync + retrying ``os.replace``) under
an exclusive cross-process lock, and the previous valid version is kept as ``memories.toml.bak``. A corrupt or unknown
file is never overwritten: every mutation refuses until the owner fixes it or restores the ``.bak``.

Selection precedence (first match wins): ``ZERO_MEM_DATA_ROOT`` in the environment > ``--memory NAME`` >
``ZERO_MEM_MEMORY`` > the registry default (``memory use``) > the XDG default.

A selected NAMED memory is applied by overlaying the environment of the process: ``ZERO_MEM_DATA_ROOT`` = its root,
``ZERO_MEM_CONFIG_PATH`` = ``<root>/config.json`` (``config.json`` records absolute data paths, so two data roots cannot
share one) and ``ZERO_MEM_CORPUS_ROOT`` removed (an inherited corpus override would break isolation). Zero dependencies,
no network, no LLM.
"""
from __future__ import annotations

import contextlib
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional

from . import paths

REGISTRY_ENV = "ZERO_MEM_MEMORIES"
MEMORY_ENV = "ZERO_MEM_MEMORY"
CONFIG_PATH_ENV = paths.CONFIG_PATH_ENV
REGISTRY_FILENAME = "memories.toml"
SCHEMA_VERSION = 1
DEFAULT_NAME = "default"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
CREATED_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MAX_DESCRIPTION = 200
MAX_PATH = 4096
MAX_FILE_BYTES = 1 << 20
LOCK_TIMEOUT = 30.0
#: Commands that resolve the registry themselves (they must work when the registry is damaged) ...
SELF_MANAGED_COMMANDS = frozenset({"memory", "link"})
#: ... and commands that must still run (and report) when the selection cannot be resolved.
LENIENT_COMMANDS = frozenset({"doctor", "version"})


class WorkspaceError(Exception):
    """A sanitized, operator-facing failure; ``kind`` is ``usage`` / ``not_found`` / ``registry``."""

    def __init__(self, message: str, kind: str = "usage") -> None:
        super().__init__(message)
        self.message = message
        self.kind = kind


@dataclass(frozen=True)
class MemoryEntry:
    name: str
    path: str  # absolute, "/" separators
    description: str = ""
    created_at: str = ""

    @property
    def root(self) -> Path:
        return Path(self.path)


@dataclass
class Registry:
    memories: Dict[str, MemoryEntry] = field(default_factory=dict)
    default: Optional[str] = None  # a registered name, "default" or None (= "default")


def valid_name(name: Any) -> bool:
    return isinstance(name, str) and NAME_RE.fullmatch(name) is not None


def check_name(name: Any, *, allow_default: bool = False) -> str:
    if not valid_name(name):
        raise WorkspaceError("invalid memory name (lowercase letters, digits, - and _; start with a letter or digit; "
                             "at most 40 characters)")
    if name == DEFAULT_NAME and not allow_default:
        raise WorkspaceError(f"'{DEFAULT_NAME}' is the built-in memory and cannot be created, replaced or renamed")
    return name


# ---------------------------------------------------------------------------------------------
# location, parsing, rendering
# ---------------------------------------------------------------------------------------------
def registry_path() -> Path:
    explicit = (os.environ.get(REGISTRY_ENV) or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return paths.config_root() / REGISTRY_FILENAME


def backup_path(path: Optional[Path] = None) -> Path:
    path = path or registry_path()
    return path.with_name(path.name + ".bak")


def _closed(table: Any, label: str, allowed: set, required: set = frozenset()) -> dict:
    if not isinstance(table, dict):
        raise WorkspaceError(f"{label} must be a table", "registry")
    extra = set(table) - allowed
    if extra:
        raise WorkspaceError(f"unknown key(s) in {label}: {', '.join(sorted(map(str, extra)))}", "registry")
    missing = required - set(table)
    if missing:
        raise WorkspaceError(f"{label} is missing: {', '.join(sorted(missing))}", "registry")
    return table


def _abs_posix(value: Any, label: str) -> str:
    if (not isinstance(value, str) or not value or len(value) > MAX_PATH or "\x00" in value
            or any(ord(c) < 0x20 for c in value)):
        raise WorkspaceError(f"{label} must be a path string", "registry")
    if not Path(value).is_absolute():
        raise WorkspaceError(f"{label} must be an absolute path", "registry")
    return value.replace("\\", "/")


def parse_registry(raw: Mapping[str, Any]) -> Registry:
    """Validate the parsed TOML against the closed schema."""
    top = _closed(dict(raw), "the registry", {"schema_version", "default", "memories"}, {"schema_version"})
    version = top["schema_version"]
    if isinstance(version, bool) or version != SCHEMA_VERSION:
        raise WorkspaceError(f"unsupported registry schema_version (this install reads {SCHEMA_VERSION})", "registry")
    memories: Dict[str, MemoryEntry] = {}
    table = top.get("memories", {})
    if not isinstance(table, dict):
        raise WorkspaceError("'memories' must be a table", "registry")
    for name, body in table.items():
        if not valid_name(name) or name == DEFAULT_NAME:
            raise WorkspaceError(f"invalid memory name in the registry: {str(name)[:48]!r}", "registry")
        body = _closed(body, f"memories.{name}", {"path", "description", "created_at"}, {"path"})
        description = body.get("description", "")
        if (not isinstance(description, str) or len(description) > MAX_DESCRIPTION
                or any(ord(c) < 0x20 for c in description)):
            raise WorkspaceError(f"memories.{name}.description is invalid", "registry")
        created = body.get("created_at", "")
        if not isinstance(created, str) or (created and not CREATED_RE.fullmatch(created)):
            raise WorkspaceError(f"memories.{name}.created_at is invalid", "registry")
        memories[name] = MemoryEntry(name, _abs_posix(body["path"], f"memories.{name}.path"), description, created)
    default = top.get("default")
    if default is not None:
        if not isinstance(default, str) or (default != DEFAULT_NAME and default not in memories):
            raise WorkspaceError("'default' must name a registered memory", "registry")
    return Registry(memories, default)


def _toml_string(value: str) -> str:
    from .learning_settings import _toml_string as render

    return render(value)


def render_registry(reg: Registry) -> str:
    lines = ["# zero-mem named memories (see docs/runbooks/memories-and-link.md).",
             "# Managed by `zero-mem memory ...`; a copy of the previous version is kept as memories.toml.bak.",
             f"schema_version = {SCHEMA_VERSION}"]
    if reg.default and reg.default != DEFAULT_NAME:
        lines.append(f"default = {_toml_string(reg.default)}")
    for name in sorted(reg.memories):
        entry = reg.memories[name]
        lines += ["", f"[memories.{name}]", f"path = {_toml_string(entry.path)}"]
        if entry.description:
            lines.append(f"description = {_toml_string(entry.description)}")
        if entry.created_at:
            lines.append(f"created_at = {_toml_string(entry.created_at)}")
    return "\n".join(lines) + "\n"


def read_registry(path: Optional[Path] = None) -> Registry:
    """The registry (empty when the file does not exist). A damaged file raises ``WorkspaceError(kind='registry')``."""
    path = Path(path) if path is not None else registry_path()
    hint = f"fix it by hand or restore {backup_path(path).name}"
    try:
        if not os.path.lexists(path):
            return Registry()
        if path.is_symlink() or not path.is_file():
            raise WorkspaceError(f"the registry is not a regular file ({hint})", "registry")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise WorkspaceError(f"the registry is too large ({hint})", "registry")
        text = path.read_text(encoding="utf-8")
        raw = tomllib.loads(text)
    except WorkspaceError:
        raise
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        raise WorkspaceError(f"the registry is unreadable or not valid TOML ({hint})", "registry") from None
    try:
        return parse_registry(raw)
    except WorkspaceError as exc:
        raise WorkspaceError(f"{exc.message} ({hint})", "registry") from None


# ---------------------------------------------------------------------------------------------
# atomic write + lock
# ---------------------------------------------------------------------------------------------
@contextlib.contextmanager
def _registry_lock(path: Path) -> Iterator[None]:
    from src.storage.coordination import locked

    try:
        paths.ensure_private_dir(path.parent, "configuration directory")
    except (paths.SetupError, paths.ConfigurationError):
        raise WorkspaceError("the configuration directory is unusable", "registry") from None
    try:
        with locked(path.with_name(path.name + ".lock"), mode="exclusive", timeout=LOCK_TIMEOUT):
            yield
    except WorkspaceError:
        raise
    except OSError:
        raise WorkspaceError("the registry is locked by another process", "registry") from None


def _atomic_write(path: Path, payload: bytes) -> None:
    from src.corpus._fsretry import retry_transient

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
        raise WorkspaceError("cannot write the registry", "registry") from None
    finally:
        with contextlib.suppress(OSError):
            os.unlink(temporary)


def write_registry(path: Path, reg: Registry) -> None:
    """Validate, keep the previous VALID file as ``.bak``, then replace the registry atomically."""
    path = Path(path)
    text = render_registry(reg)
    parse_registry(tomllib.loads(text))  # never persist something the reader would reject
    if os.path.lexists(path):
        try:
            previous = read_registry(path)  # a damaged file is never overwritten, nor copied over a good .bak
            del previous
            _atomic_write(backup_path(path), path.read_bytes())
        except OSError:
            raise WorkspaceError("cannot back up the registry", "registry") from None
    _atomic_write(path, text.encode("utf-8"))


def mutate(fn: Callable[[Registry], Any], path: Optional[Path] = None) -> Any:
    """Read-modify-write the registry under the exclusive lock; returns ``fn``'s result."""
    path = Path(path) if path is not None else registry_path()
    with _registry_lock(path):
        reg = read_registry(path)
        result = fn(reg)
        write_registry(path, reg)
        return result


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Selection:
    name: str
    root: Path
    source: str  # env-data-root | --memory | env-memory | registry-default | xdg-default
    named: bool  # True: apply the environment overlay of a registered memory


def default_root() -> Path:
    """The root of the implicit memory ``default``: ``ZERO_MEM_DATA_ROOT`` / the XDG default."""
    return paths.data_root()


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def select(memory_arg: Optional[str] = None, environ: Optional[Mapping[str, str]] = None,
           registry: Optional[Registry] = None) -> Selection:
    """Resolve the active memory (precedence in the module docstring). Raises :class:`WorkspaceError`."""
    environ = os.environ if environ is None else environ
    explicit = (environ.get(paths.DATA_ROOT_ENV) or "").strip()
    if explicit:
        root = default_root()
        reg = registry
        name: Optional[str] = DEFAULT_NAME
        try:
            reg = reg or read_registry()
            for entry in reg.memories.values():
                if _same(entry.root, root):
                    name = entry.name
                    break
        except WorkspaceError:
            pass
        return Selection(name, root, "env-data-root", False)
    wanted, source = None, "xdg-default"
    if memory_arg:
        wanted, source = memory_arg, "--memory"
    elif (environ.get(MEMORY_ENV) or "").strip():
        wanted, source = environ[MEMORY_ENV].strip(), "env-memory"
    if wanted is not None:
        check_name(wanted, allow_default=True)
    if wanted is None or wanted != DEFAULT_NAME:
        reg = registry or read_registry()
        if wanted is None:
            wanted = reg.default
            source = "registry-default" if wanted else "xdg-default"
        if wanted and wanted != DEFAULT_NAME:
            entry = reg.memories.get(wanted)
            if entry is None:
                raise WorkspaceError(f"no memory named '{wanted}' (zero-mem memory list)", "not_found")
            return Selection(wanted, entry.root, source, True)
    return Selection(DEFAULT_NAME, default_root(), source, False)


def env_overlay(root: Path, named: bool) -> Dict[str, Optional[str]]:
    """Environment changes that make this process use ``root`` (``None`` = remove the variable)."""
    overlay: Dict[str, Optional[str]] = {paths.DATA_ROOT_ENV: str(root)}
    if named:
        overlay[CONFIG_PATH_ENV] = str(Path(root) / paths.CONFIG_FILENAME)
        overlay[paths.CORPUS_ROOT_ENV] = None
    else:
        overlay[CONFIG_PATH_ENV] = None
    return overlay


@contextlib.contextmanager
def patched_environ(overlay: Mapping[str, Optional[str]]) -> Iterator[None]:
    saved = {key: os.environ.get(key) for key in overlay}
    try:
        for key, value in overlay.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextlib.contextmanager
def using_memory(root: Path, named: bool) -> Iterator[None]:
    """Run a block with the process environment pointing at one memory (restored afterwards)."""
    with patched_environ(env_overlay(root, named)):
        yield


_ACTIVE: Dict[str, Any] = {"selection": None, "error": None}


def active_selection() -> Optional[Selection]:
    """The selection ``main`` applied for this command (or a fresh one); ``None`` if it cannot be resolved."""
    if _ACTIVE["selection"] is not None:
        return _ACTIVE["selection"]
    try:
        return select(None)
    except WorkspaceError:
        return None


@contextlib.contextmanager
def memory_scope(args) -> Iterator[Optional[int]]:
    """Apply the selection for one CLI invocation. Yields an exit code when the command must not run, else ``None``."""
    import sys

    command = getattr(args, "command", None)
    if command in SELF_MANAGED_COMMANDS:
        yield None
        return
    memory_arg = getattr(args, "memory_name", None)
    try:
        selection = select(memory_arg)
    except WorkspaceError as exc:
        if command in LENIENT_COMMANDS:
            _ACTIVE.update(selection=None, error=exc.message)
            yield None
            _ACTIVE.update(selection=None, error=None)
            return
        print(f"zero-mem: {exc.message}", file=sys.stderr)
        yield 5 if exc.kind == "not_found" else 2
        return
    if selection.source == "env-data-root" and memory_arg:
        print("zero-mem: note: ZERO_MEM_DATA_ROOT is set and takes precedence over --memory", file=sys.stderr)
    _ACTIVE.update(selection=selection, error=None)
    try:
        if selection.named:
            with patched_environ(env_overlay(selection.root, True)):
                yield None
        else:
            yield None
    finally:
        _ACTIVE.update(selection=None, error=None)


def active_summary() -> Dict[str, Any]:
    """Name / source / registry health for ``doctor`` and ``memory-status`` (never raises, no content)."""
    out: Dict[str, Any] = {"memory": None, "source": None, "registry": "ok", "registry_error": None, "named": 0}
    try:
        reg = read_registry()
        out["named"] = len(reg.memories)
        if os.path.lexists(registry_path()) is False:
            out["registry"] = "absent"
    except WorkspaceError as exc:
        out["registry"], out["registry_error"] = "damaged", exc.message
    selection = active_selection()
    if selection is not None:
        out["memory"], out["source"] = selection.name, selection.source
    return out


# ---------------------------------------------------------------------------------------------
# path safety
# ---------------------------------------------------------------------------------------------
def _real(path: Path) -> str:
    return os.path.normcase(os.path.realpath(path))


def _inside(inner: str, outer: str) -> bool:
    try:
        return os.path.commonpath([inner, outer]) == outer
    except ValueError:  # different drives
        return False


def _all_roots(reg: Registry, exclude: Optional[str] = None) -> Dict[str, Path]:
    roots = {DEFAULT_NAME: default_root()}
    roots.update({n: e.root for n, e in reg.memories.items() if n != exclude})
    return roots


def check_new_root(root: Path, reg: Registry, exclude: Optional[str] = None) -> None:
    """Refuse a symlink, a path that crosses one, or a root equal to / nested with any other memory's root."""
    try:
        paths._reject_symlink(root, "memory path")
    except paths.SetupError:
        raise WorkspaceError("the memory path is, or lies under, a symbolic link; use a real directory") from None
    if root.parent == root:
        raise WorkspaceError("the file system root cannot be a memory")
    mine = _real(root)
    for name, other in _all_roots(reg, exclude).items():
        theirs = _real(other)
        if mine == theirs:
            raise WorkspaceError(f"that path is already the data root of the memory '{name}'")
        if _inside(mine, theirs):
            raise WorkspaceError(f"that path is inside the data root of the memory '{name}'")
        if _inside(theirs, mine):
            raise WorkspaceError(f"that path contains the data root of the memory '{name}'")


def looks_like_memory(root: Path) -> bool:
    return (Path(root) / paths.MEMORY_STREAM_RELATIVE).is_file()


def default_new_path(name: str) -> Path:
    return default_root().parent / "zero-mem-memories" / name


# ---------------------------------------------------------------------------------------------
# operations
# ---------------------------------------------------------------------------------------------
def ensure_memory(root: Path, named: bool) -> None:
    """Create/validate the layout of one memory with exactly what ``zero-mem setup`` runs."""
    from .memory_layout import Layout, LayoutError

    with using_memory(root, named):
        try:
            Layout.resolve(None).ensure()
        except LayoutError as exc:
            raise WorkspaceError(f"setup failed: {exc}") from None


def create_memory(name: str, path: Optional[str] = None, description: str = "") -> MemoryEntry:
    check_name(name)
    if description and (len(description) > MAX_DESCRIPTION or any(ord(c) < 0x20 for c in description)):
        raise WorkspaceError(f"the description must be one line of at most {MAX_DESCRIPTION} characters")
    if path is not None and not str(path).strip():
        raise WorkspaceError("--path is empty")

    def op(reg: Registry) -> MemoryEntry:
        if name in reg.memories:
            raise WorkspaceError(f"a memory named '{name}' already exists")
        root = Path(os.path.abspath(os.path.expanduser(path))) if path else default_new_path(name)
        check_new_root(root, reg)
        if root.exists():
            if not root.is_dir():
                raise WorkspaceError("the memory path exists and is not a directory")
            if any(root.iterdir()) and not looks_like_memory(root):
                raise WorkspaceError("the directory is not empty and is not a zero-mem data root; "
                                     "pick a new or empty directory")
        ensure_memory(root, True)
        entry = MemoryEntry(name, root.as_posix(), description, utc_now())
        reg.memories[name] = entry
        return entry

    return mutate(op)


def get_entry(name: str, reg: Optional[Registry] = None) -> MemoryEntry:
    check_name(name, allow_default=True)
    if name == DEFAULT_NAME:
        return MemoryEntry(DEFAULT_NAME, default_root().as_posix(), "the built-in memory (ZERO_MEM_DATA_ROOT / XDG)")
    reg = reg or read_registry()
    if name not in reg.memories:
        raise WorkspaceError(f"no memory named '{name}' (zero-mem memory list)", "not_found")
    return reg.memories[name]


def use_memory(name: str) -> MemoryEntry:
    def op(reg: Registry) -> MemoryEntry:
        entry = get_entry(name, reg)
        reg.default = None if name == DEFAULT_NAME else name
        return entry

    return mutate(op)


def rename_memory(old: str, new: str) -> MemoryEntry:
    check_name(old, allow_default=True)
    check_name(new)
    if old == DEFAULT_NAME:
        raise WorkspaceError(f"'{DEFAULT_NAME}' is the built-in memory and cannot be renamed")

    def op(reg: Registry) -> MemoryEntry:
        if old not in reg.memories:
            raise WorkspaceError(f"no memory named '{old}' (zero-mem memory list)", "not_found")
        if new in reg.memories:
            raise WorkspaceError(f"a memory named '{new}' already exists")
        entry = reg.memories.pop(old)
        renamed = MemoryEntry(new, entry.path, entry.description, entry.created_at)
        reg.memories[new] = renamed
        if reg.default == old:
            reg.default = new
        return renamed

    return mutate(op)


def remove_memory(name: str, *, delete_data: bool = False, yes: bool = False) -> Dict[str, Any]:
    """Unregister ``name``; the data stays unless ``delete_data`` and ``yes`` (never for ``default``)."""
    import shutil

    check_name(name, allow_default=True)
    if name == DEFAULT_NAME:
        raise WorkspaceError(f"'{DEFAULT_NAME}' is the built-in memory: it cannot be removed or deleted")
    if delete_data and not yes:
        raise WorkspaceError("--delete-data destroys the memory's files: re-run with --delete-data --yes")

    def op(reg: Registry) -> Dict[str, Any]:
        if name not in reg.memories:
            raise WorkspaceError(f"no memory named '{name}' (zero-mem memory list)", "not_found")
        entry = reg.memories[name]
        if delete_data:
            root = entry.root
            if os.path.islink(root) or not root.is_dir() or not looks_like_memory(root):
                raise WorkspaceError("refusing to delete: the path is not a real zero-mem data root")
            mine = _real(root)
            for other, other_root in _all_roots(reg, name).items():
                if _inside(_real(other_root), mine):
                    raise WorkspaceError(f"refusing to delete: it contains the data root of '{other}'")
            if mine == _real(Path.home()) or root.parent == root:
                raise WorkspaceError("refusing to delete: that path is not a dedicated memory directory")
        del reg.memories[name]
        if reg.default == name:
            reg.default = None
        return {"name": name, "path": entry.path, "deleted": False}

    result = mutate(op)
    if delete_data:
        try:
            shutil.rmtree(result["path"])
        except OSError:
            raise WorkspaceError("the memory was unregistered but its files could not all be deleted") from None
        result["deleted"] = True
    return result


def memory_facts(entry: MemoryEntry, *, is_default: bool) -> Dict[str, Any]:
    """Counts for ``memory list`` (read-only; nothing from inside the memory but numbers and one timestamp)."""
    from .memory_health import snapshot

    root = entry.root
    facts: Dict[str, Any] = {"status": "missing", "sources": None, "agents": None, "last_write": None}
    if not root.is_dir():
        return facts
    try:
        with using_memory(root, not is_default):
            snap = snapshot()
    except Exception:  # noqa: BLE001 - listing never crashes
        facts["status"] = "unreadable"
        return facts
    if not snap["initialised"]:
        facts["status"] = "uninitialised"
        return facts
    facts.update(status="ok", sources=snap["sources"]["live"], last_write=snap["last_write"],
                 agents=(snap["grants"] or {}).get("agents"))
    return facts


def list_memories(selection: Optional[Selection] = None) -> List[Dict[str, Any]]:
    reg = read_registry()
    selection = selection or select(None)
    default_flag = reg.default or DEFAULT_NAME
    rows = []
    entries = [get_entry(DEFAULT_NAME)] + [reg.memories[n] for n in sorted(reg.memories)]
    for entry in entries:
        is_default = entry.name == DEFAULT_NAME
        row = {"name": entry.name, "path": entry.path, "description": entry.description,
               "created_at": entry.created_at or None,
               "current": selection.name == entry.name, "default": entry.name == default_flag,
               **memory_facts(entry, is_default=is_default)}
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------------------------
# link support: agents of one memory
# ---------------------------------------------------------------------------------------------
@contextlib.contextmanager
def provisioner_for(entry: MemoryEntry, *, create: bool) -> Iterator[Any]:
    """A :class:`Provisioner` bound to exactly one memory (environment pinned for the duration)."""
    from .memory_layout import Layout, LayoutError
    from .provisioning import Provisioner

    named = entry.name != DEFAULT_NAME
    with using_memory(entry.root, named):
        try:
            layout = Layout.resolve(None)
            if create:
                layout.ensure()
        except LayoutError as exc:
            raise WorkspaceError(f"setup failed: {exc}") from None
        yield Provisioner(layout)


def link_server_name(memory: str) -> str:
    if memory == DEFAULT_NAME:
        return "zero-mem"
    return f"zero-mem-{memory}"[:40].rstrip("-")


__all__ = [
    "DEFAULT_NAME", "MemoryEntry", "NAME_RE", "Registry", "Selection", "WorkspaceError", "active_selection",
    "active_summary", "check_name", "create_memory", "env_overlay", "get_entry", "link_server_name", "list_memories",
    "memory_scope", "mutate", "parse_registry", "provisioner_for", "read_registry", "registry_path", "remove_memory",
    "rename_memory", "render_registry", "select", "use_memory", "using_memory", "valid_name", "write_registry",
]
