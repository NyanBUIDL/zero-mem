"""PKG-4 optional Hermes integration release layer.

This module owns only the explicit, application-owned integration descriptor and
its boundary checks.  The existing ``src.integration`` adapters remain the
runtime authority; this layer never edits Hermes core, reads Hermes secrets, or
infers project/profile identity.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import tempfile
import threading
from functools import wraps
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.integration.zero_mem_runtime import RuntimeMode

from .paths import config_root, derived_db, load_config, memory_stream
from .version import __version__

CONFIG_SCHEMA_VERSION = 1
CONFIG_FILENAME = "hermes-integration.json"
OWNER_MARKER = "zero-mem"
BOUNDARY_ID = "hermes-plugin-context-v1"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_BOUNDARY_DISABLED_RUNTIME = None


def _lifecycle_guard(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self._lifecycle_lock:
            return method(self, *args, **kwargs)
    return guarded


class HermesIntegrationError(RuntimeError):
    """Sanitized integration configuration or readiness failure."""


@dataclass(frozen=True)
class IntegrationConfig:
    """Explicit, application-owned Hermes integration state."""

    project_id: str
    profile_id: str
    enabled: bool = True

    def __post_init__(self) -> None:
        _validate_id(self.project_id, "project_id")
        _validate_id(self.profile_id, "profile_id")
        if not isinstance(self.enabled, bool):
            raise HermesIntegrationError("invalid integration enabled value")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "owner": OWNER_MARKER,
            "package_version": __version__,
            "boundary": BOUNDARY_ID,
            "enabled": self.enabled,
            "project_id": self.project_id,
            "profile_id": self.profile_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> "IntegrationConfig":
        if not isinstance(value, dict):
            raise HermesIntegrationError("integration configuration must be an object")
        required = {
            "schema_version", "owner", "package_version", "boundary", "enabled",
            "project_id", "profile_id",
        }
        if set(value) != required:
            raise HermesIntegrationError("unsupported integration configuration")
        if value["schema_version"] != CONFIG_SCHEMA_VERSION or value["owner"] != OWNER_MARKER:
            raise HermesIntegrationError("invalid integration configuration owner")
        if value["package_version"] != __version__ or value["boundary"] != BOUNDARY_ID:
            raise HermesIntegrationError("incompatible integration configuration")
        if not isinstance(value["enabled"], bool):
            raise HermesIntegrationError("invalid integration enabled value")
        if not isinstance(value["project_id"], str) or not isinstance(value["profile_id"], str):
            raise HermesIntegrationError("explicit project_id and profile_id are required")
        return cls(
            project_id=value["project_id"],
            profile_id=value["profile_id"],
            enabled=value["enabled"],
        )


def _validate_id(value: object, field: str) -> None:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or _ID_RE.fullmatch(value) is None
    ):
        raise HermesIntegrationError(f"explicit {field} is required")


def integration_config_path() -> Path:
    """Return the Zero-Mem-owned descriptor path; never a guessed Hermes path."""
    return config_root() / CONFIG_FILENAME


def _reject_symlink(path: Path) -> None:
    if path.is_symlink():
        raise HermesIntegrationError("integration configuration is unsafe")


def load_integration_config(*, required: bool = True) -> IntegrationConfig | None:
    path = integration_config_path()
    if not path.exists():
        if required:
            raise HermesIntegrationError("Hermes integration is not configured")
        return None
    _reject_symlink(path)
    if not path.is_file():
        raise HermesIntegrationError("integration configuration is not a file")
    try:
        return IntegrationConfig.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except HermesIntegrationError:
        raise
    except (OSError, UnicodeError, ValueError):
        raise HermesIntegrationError("invalid integration configuration") from None


def _write_integration_config(value: IntegrationConfig) -> None:
    path = integration_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink(path)
    payload = (json.dumps(value.to_dict(), indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{CONFIG_FILENAME}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except OSError:
        raise HermesIntegrationError("unable to write integration configuration") from None
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _hermes_executable() -> str | None:
    """Use the operator's supported executable discovery, without path guessing."""
    return shutil.which("hermes")


def _boundary_modules_available() -> bool:
    modules = (
        "src.integration.hermes_registration",
        "src.integration.hermes_read_adapter",
        "src.integration.m7.injection_adapter",
    )
    return all(importlib.util.find_spec(module) is not None for module in modules)


def _master_switch() -> tuple[bool, str | None]:
    """Read the existing ZERO_MEM_ENABLED contract; absent retains its true default."""
    from src.integration.zero_mem_runtime import parse_zero_mem_enabled

    raw = os.environ.get("ZERO_MEM_ENABLED")
    try:
        return parse_zero_mem_enabled(raw), None
    except Exception:
        return False, "invalid ZERO_MEM_ENABLED configuration"


def _configured_capture_mode() -> tuple[str | None, str | None]:
    """Read the canonical Zero-Mem config ``capture_mode``, if configured.

    R124-01. The canonical setup configuration is authority for the default mode.
    A missing/unreadable configuration is NOT an error here: it simply provides no
    canonical default, and the caller then fails closed rather than self-elevating.
    """
    try:
        config = load_config(required=False)
    except Exception:
        return None, "invalid canonical configuration"
    if not isinstance(config, dict):
        return None, None
    value = config.get("capture_mode")
    return (value if isinstance(value, str) else None), None


def _runtime_mode() -> tuple["RuntimeMode", str | None]:  # type: ignore[name-defined]
    """Resolve the effective runtime mode from canonical config + environment.

    R124-01 resolution order (fail closed, never self-elevating):

    1. ``ZERO_MEM_ENABLED`` false/invalid  -> ``off``.
    2. ``ZERO_MEM_MODE`` present           -> that explicit mode; invalid -> ``off``.
    3. canonical config ``capture_mode``   -> mapped mode
       (``observation_only`` -> ``observe``).
    4. nothing configured                  -> ``observe`` (least-privilege default).

    A missing ``ZERO_MEM_MODE`` must never raise the effective mode above the
    canonical configuration, so an absent environment variable can no longer
    promote a setup written as ``capture_mode=observation_only`` into ``assist``.
    """
    from src.integration.zero_mem_runtime import parse_runtime_mode, RuntimeMode

    enabled, error = _master_switch()
    if error:
        return RuntimeMode.OFF, error
    if not enabled:
        return RuntimeMode.OFF, None
    raw = os.environ.get("ZERO_MEM_MODE")
    if raw is not None:
        try:
            return parse_runtime_mode(raw), None
        except Exception:
            # Sanitized diagnostic: never echo the rejected operator-supplied value.
            return RuntimeMode.OFF, "invalid ZERO_MEM_MODE configuration"
    capture_mode, config_error = _configured_capture_mode()
    if config_error:
        return RuntimeMode.OFF, config_error
    if capture_mode is not None:
        if capture_mode == "observation_only":
            return RuntimeMode.OBSERVE, None
        try:
            return parse_runtime_mode(capture_mode), None
        except Exception:
            return RuntimeMode.OFF, "invalid canonical capture_mode configuration"
    # No explicit mode and no canonical capture_mode: least privilege.
    return RuntimeMode.OBSERVE, None


def zero_mem_ready() -> bool:
    try:
        load_config()
        return memory_stream().is_file() and derived_db().is_file()
    except Exception:
        return False


def inspect_integration() -> dict[str, Any]:
    """Return bounded, content-free inspection data."""
    found = _hermes_executable() is not None
    try:
        configured = load_integration_config(required=False)
        config_error = None
    except HermesIntegrationError as exc:
        configured = None
        config_error = str(exc)
    master, master_error = _master_switch()
    return {
        "hermes_found": found,
        "boundary_available": _boundary_modules_available(),
        "configured": configured is not None and config_error is None,
        "config_error": config_error,
        "project_id_configured": configured is not None and bool(configured.project_id),
        "profile_id_configured": configured is not None and bool(configured.profile_id),
        "zero_mem_ready": zero_mem_ready(),
        "zero_mem_enabled": master,
        "master_error": master_error,
        "change_required": found and configured is None,
    }


def configure_integration(*, project_id: str | None, profile_id: str | None) -> IntegrationConfig:
    """Validate explicit identity and write only Zero-Mem-owned state."""
    _validate_id(project_id, "project_id")
    _validate_id(profile_id, "profile_id")
    master_enabled, master_error = _master_switch()
    if master_error:
        raise HermesIntegrationError(master_error)
    if not master_enabled:
        raise HermesIntegrationError("Zero-Mem integration is disabled by ZERO_MEM_ENABLED")
    existing_path = integration_config_path()
    if existing_path.exists():
        load_integration_config(required=True)
    if not zero_mem_ready():
        raise HermesIntegrationError("Zero-Mem is not READY; run zero-mem setup first")
    if _hermes_executable() is None:
        raise HermesIntegrationError("Hermes is optional and was not found")
    if not _boundary_modules_available():
        raise HermesIntegrationError("Hermes boundary is unavailable in this installation")
    value = IntegrationConfig(project_id=project_id, profile_id=profile_id)
    _write_integration_config(value)
    return value


def open_hermes_boundary(
    *,
    project_id: str,
    profile_id: str,
    capture_root: Path,
    store_path: Path | None = None,
    enabled: bool = True,
) -> HermesBoundary:
    """Create the full external Hermes host composition boundary."""
    return HermesBoundary(
        IntegrationConfig(project_id=project_id, profile_id=profile_id, enabled=enabled),
        capture_root=Path(capture_root),
        store_path=Path(store_path) if store_path is not None else None,
    )

def remove_integration() -> None:
    """Remove only a valid Zero-Mem-owned descriptor."""
    path = integration_config_path()
    if not path.exists():
        return
    load_integration_config(required=True)
    try:
        path.unlink()
    except OSError:
        raise HermesIntegrationError("unable to remove integration configuration") from None


def _diagnostic(code: str, status: str, message: str, remediation: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "code": code,
        "status": status,
        "component": "hermes",
        "message": message,
    }
    if remediation:
        result["remediation"] = remediation
    return result


def command(*, project_id: str | None, profile_id: str | None, check: bool = False, remove: bool = False) -> tuple[int, dict[str, Any]]:
    """Run the explicit release-layer workflow and return a sanitized result."""
    if remove:
        try:
            remove_integration()
        except HermesIntegrationError as exc:
            return 2, _diagnostic("INTEGRATION_CONFIG_INVALID", "FAIL", str(exc), "Repair the Zero-Mem-owned descriptor before removing it.")
        return 0, _diagnostic("INTEGRATION_REMOVED", "PASS", "Zero-Mem Hermes integration removed")

    info = inspect_integration()
    if not info["hermes_found"]:
        return 0, _diagnostic("HERMES_NOT_FOUND", "OPTIONAL", "Hermes not found; Zero-Mem remains READY without Hermes")
    if info["master_error"]:
        return 2, _diagnostic("ZERO_MEM_ENABLED_INVALID", "FAIL", info["master_error"], "Use true/false or 1/0 and retry.")
    if check:
        if info["config_error"]:
            return 2, _diagnostic("INTEGRATION_CONFIG_INVALID", "FAIL", info["config_error"])
        details = {
            "hermes_found": info["hermes_found"],
            "boundary_available": info["boundary_available"],
            "project_id_configured": info["project_id_configured"],
            "profile_id_configured": info["profile_id_configured"],
            "zero_mem_ready": info["zero_mem_ready"],
            "zero_mem_enabled": info["zero_mem_enabled"],
            "change_required": info["change_required"],
        }
        if not info["zero_mem_enabled"]:
            result = _diagnostic("ZERO_MEM_DISABLED", "OPTIONAL", "Zero-Mem integration is disabled by ZERO_MEM_ENABLED")
            result["details"] = details
            return 0, result
        if not info["boundary_available"]:
            result = _diagnostic("HERMES_BOUNDARY_UNAVAILABLE", "FAIL", "supported Hermes boundary is unavailable")
            result["details"] = details
            return 2, result
        if not info["configured"]:
            result = _diagnostic("INTEGRATION_NOT_CONFIGURED", "WARN", "Hermes found; explicit project_id and profile_id are not configured", "Run zero-mem integrate hermes --project-id ID --profile-id ID.")
            result["details"] = details
            return 1, result
        status = "PASS" if info["zero_mem_ready"] else "FAIL"
        code = "HERMES_INTEGRATION_READY" if status == "PASS" else "ZERO_MEM_NOT_READY"
        result = _diagnostic(code, status, "Hermes boundary configured and available" if status == "PASS" else "Zero-Mem is not READY")
        result["details"] = details
        return (0 if status == "PASS" else 2), result
    if project_id is None or profile_id is None:
        return 2, _diagnostic("EXPLICIT_IDENTITY_REQUIRED", "FAIL", "explicit project_id and profile_id are required", "Pass --project-id and --profile-id; identity is never inferred.")
    try:
        configure_integration(project_id=project_id, profile_id=profile_id)
    except HermesIntegrationError as exc:
        if str(exc) == "Zero-Mem integration is disabled by ZERO_MEM_ENABLED":
            return 0, _diagnostic("ZERO_MEM_DISABLED", "OPTIONAL", "Zero-Mem integration is disabled by ZERO_MEM_ENABLED")
        return 2, _diagnostic("INTEGRATION_REFUSED", "FAIL", str(exc))
    return 0, _diagnostic("HERMES_INTEGRATION_CONFIGURED", "PASS", "Hermes integration configured through the supported plugin boundary")


def _derived_store_path(capture_root: Path) -> Path:
    """The one runtime-owned derived store identity, derived from capture_root.

    R124-02. ``ZeroMemRuntime.open`` creates exactly this file via
    ``RuntimeStorageRoot.derived``; nothing else may be treated as the read store.
    """
    return Path(capture_root).expanduser().resolve() / "derived" / "events.sqlite"


def _same_store_identity(candidate: Path, runtime_owned: Path) -> bool:
    """Return True only when ``candidate`` is the runtime-owned derived store.

    Compares the normalized path, then the resolved real path (alias/symlink), then
    the concrete filesystem identity when both exist. Any error is a mismatch.
    """
    try:
        left = Path(candidate).expanduser()
        right = Path(runtime_owned).expanduser()
        if os.path.normcase(str(left)) == os.path.normcase(str(right)):
            return True
        if os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right)):
            return True
        if left.exists() and right.exists():
            left_stat, right_stat = left.stat(), right.stat()
            return (left_stat.st_dev, left_stat.st_ino) == (right_stat.st_dev, right_stat.st_ino)
    except OSError:
        return False
    return False


class HermesBoundary:
    """Small runtime composition helper for a supported external PluginContext.

    It consumes only explicit integration identity and caller-owned paths. Each
    existing adapter retains its own authorization, read-only, redaction, and
    failure-isolation behavior.

    R124-01/R124-02: this class is the single production composition root. The
    effective runtime mode is resolved BEFORE any adapter, writer, derived store,
    or projection worker is constructed, and every adapter is bound to the one
    runtime-owned storage identity derived from ``capture_root``.
    """

    def __init__(self, config: IntegrationConfig, *, capture_root: Path | None = None, store_path: Path | None = None) -> None:
        self.config = config
        self.capture_root = capture_root
        self.store_path = store_path
        self.diagnostics: list[dict[str, str]] = []
        self._registered_context: Any | None = None
        self._registration_result: dict[str, tuple[str, ...]] | None = None
        self._registered_mode: Any | None = None
        self._capture_adapter: Any | None = None
        self._read_adapter: Any | None = None
        self._injection_adapter: Any | None = None
        self._resolved_store_path: Path | None = None
        self._lifecycle_lock = threading.RLock()

    @property
    def storage_identity(self) -> str | None:
        """Sanitized single-topology store identity, or None when nothing is open."""
        return str(self._resolved_store_path) if self._resolved_store_path is not None else None

    @property
    def runtime(self) -> Any | None:
        """The one ZeroMemRuntime owned by this boundary, when composed."""
        return getattr(self._capture_adapter, "runtime", None)

    def _drop_authority(self) -> dict[str, tuple[str, ...]]:
        """Fail closed: stop adapters and discard all cached callback authority."""
        self.shutdown()
        self._registered_context = None
        self._registration_result = None
        self._registered_mode = None
        self._capture_adapter = None
        self._read_adapter = None
        self._injection_adapter = None
        self._resolved_store_path = None
        return {"hooks": (), "tools": (), "injection": ()}

    @_lifecycle_guard
    def register(self, context: Any) -> dict[str, tuple[str, ...]]:
        global _BOUNDARY_DISABLED_RUNTIME
        from src.integration.zero_mem_runtime import (
            RuntimeMode,
            configure,
            get_runtime,
            mode_injection_enabled,
            mode_read_enabled,
        )

        enabled, error = _master_switch()
        # R124-01: resolve the effective mode BEFORE composing anything at all.
        mode, mode_error = _runtime_mode()
        if mode_error:
            self.diagnostics.append({"component": "mode", "code": "invalid_runtime_mode"})

        # OFF gate. No capture hook, no read tool, no injection hook, no writer,
        # no canonical JSONL, no SQLite, no projection worker. An invalid mode
        # fails closed to exactly this path with a sanitized diagnostic.
        if error or not enabled or not self.config.enabled or mode_error or mode is RuntimeMode.OFF:
            # Stop previously registered adapters before revoking the process gate so
            # registration never leaves stale callback authority live.
            result = self._drop_authority()
            configure(enabled=False, source="boundary")
            _BOUNDARY_DISABLED_RUNTIME = get_runtime()
            return result

        # A boundary-local registration must never re-enable an already
        # resolved process-global disabled/closed runtime. Only initialize the
        # compatibility gate when no global runtime exists yet.
        try:
            global_runtime = get_runtime()
        except RuntimeError:
            configure(enabled=True, source="boundary")
        else:
            if not global_runtime.is_enabled():
                if global_runtime.source != "boundary" or global_runtime is not _BOUNDARY_DISABLED_RUNTIME:
                    result = self._drop_authority()
                    configure(enabled=False)
                    _BOUNDARY_DISABLED_RUNTIME = get_runtime()
                    return result
                configure(enabled=True, source="boundary")
                _BOUNDARY_DISABLED_RUNTIME = None
            else:
                _BOUNDARY_DISABLED_RUNTIME = None

        # Reuse an existing callback set only when the resolved mode is unchanged;
        # a mode change must never reuse a registration made under other authority.
        if (
            self._registered_context is context
            and self._registration_result is not None
            and self._registered_mode is mode
        ):
            for adapter in (self._capture_adapter, self._read_adapter, self._injection_adapter):
                restart = getattr(adapter, "restart", None)
                if callable(restart):
                    restart()
            return {key: tuple(value) for key, value in self._registration_result.items()}
        if self._registered_context is not None:
            self.shutdown()

        from src.integration.bridge_config import BridgeConfig
        from src.integration.hermes_registration import RegistrationAdapter
        from src.integration.hermes_read_adapter import HermesReadAdapter
        from src.integration.m7.injection_adapter import InjectionAdapter

        read_enabled = mode_read_enabled(mode)
        injection_enabled = mode_injection_enabled(mode)

        # R124-02: one composition root requires one runtime-owned storage root.
        if self.capture_root is None:
            self.diagnostics.append({"component": "topology", "code": "capture_root_required"})
            return self._drop_authority()
        runtime_store_path = _derived_store_path(self.capture_root)
        # A retained store_path is a compatibility input only: it must resolve to the
        # runtime-owned derived store. A split topology fails closed.
        if self.store_path is not None and not _same_store_identity(self.store_path, runtime_store_path):
            self.diagnostics.append({"component": "topology", "code": "store_identity_mismatch"})
            return self._drop_authority()

        result: dict[str, tuple[str, ...]] = {"hooks": (), "tools": (), "injection": ()}
        # The capture adapter owns THE ZeroMemRuntime: one canonical writer, one
        # derived SQLite store, one bounded ProjectionCoordinator. It is composed
        # first so the runtime-owned derived store exists before any reader binds.
        try:
            self._capture_adapter = RegistrationAdapter(
                BridgeConfig(
                    enabled=True,
                    project_id=self.config.project_id,
                    profile_id=self.config.profile_id,
                    capture_root=self.capture_root,
                ),
                mode=mode,
            )
            result["hooks"] = self._capture_adapter.register(context)
        except Exception:
            self.diagnostics.append({"component": "capture", "code": "registration_failed"})
            return self._drop_authority()
        self._resolved_store_path = runtime_store_path

        # V124-02/R124-01: read tools are registered only when the mode permits.
        # R124-02: the reader binds to the runtime-owned derived store, never to a
        # separately supplied path.
        if read_enabled:
            try:
                tool_context = _ToolContextAdapter(context)
                self._read_adapter = HermesReadAdapter(
                    BridgeConfig(
                        enabled=True,
                        project_id=self.config.project_id,
                        profile_id=self.config.profile_id,
                        capture_root=self.capture_root,
                    ),
                    store_path=runtime_store_path,
                )
                result["tools"] = self._read_adapter.register(tool_context)
            except Exception:
                self.diagnostics.append({"component": "read", "code": "registration_failed"})
        try:
            # V124-02: injection hook is registered ONLY in inject mode (controlled).
            # observe/assist must never construct or register an InjectionAdapter.
            if not injection_enabled:
                self._injection_adapter = None
                result["injection"] = ()
            else:
                self._injection_adapter = InjectionAdapter(
                    requesting_profile_id=self.config.profile_id,
                    project_id=self.config.project_id,
                    store_path=runtime_store_path,
                )
                result["injection"] = self._injection_adapter.register(context)
        except Exception:
            self.diagnostics.append({"component": "injection", "code": "registration_failed"})
        self._registered_context = context
        self._registered_mode = mode
        self._registration_result = {key: tuple(value) for key, value in result.items()}
        return result


    @_lifecycle_guard
    def shutdown(self) -> None:
        """Close all adapters owned by this boundary; safe to call repeatedly."""
        for adapter in (self._read_adapter, self._capture_adapter, self._injection_adapter):
            close = getattr(adapter, "shutdown", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    self.diagnostics.append({"component": "lifecycle", "code": "shutdown_failed"})
        # Keep adapter references and registration result so an existing Hermes
        # callback set can be rebound on the next lifecycle restart without
        # registering duplicate callbacks. Authority is revoked separately by
        # ``_drop_authority`` whenever the mode gate closes.

    def health(self) -> dict[str, object]:
        """R124-03: truthful production health across all four modes.

        Delegates to the ONE runtime-owned topology. When the boundary is in OFF or
        has dropped authority, reports the fail-closed CLOSED/OFF contract with no
        side effects and no invented freshness.
        """
        runtime = self.runtime
        if runtime is None:
            return {
                "status": "CLOSED",
                "mode": "off",
                "capture_enabled": False,
                "read_enabled": False,
                "injection_enabled": False,
                "writer_open": False,
                "canonical_store_identity": None,
                "derived_store_identity": None,
                "last_canonical_sequence": None,
                "last_projected_sequence": None,
                "lag": None,
                "projection_status": None,
                "last_projection_error": None,
                "readiness": "OFF",
                "reason_code": "BOUNDARY_DISABLED",
            }
        h = runtime.health()
        return {
            "status": h.status,
            "mode": h.mode,
            "capture_enabled": h.capture_enabled,
            "read_enabled": h.read_enabled,
            "injection_enabled": h.injection_enabled,
            "writer_open": h.writer_open,
            "canonical_store_identity": h.canonical_store_identity,
            "derived_store_identity": h.read_store_identity,
            "last_canonical_sequence": h.last_canonical_sequence,
            "last_projected_sequence": h.last_projected_sequence,
            "lag": h.lag,
            "projection_status": h.projection_status,
            "last_projection_error": h.last_projection_error,
            "readiness": h.readiness,
            "reason_code": h.reason_code,
        }

    def sync(self) -> str:
        """R124-03: truthful production sync state; never self-greens to CURRENT."""
        runtime = self.runtime
        if runtime is None:
            return "OFF"
        return runtime.sync()


class _ToolContextAdapter:
    """Adapt the verified Zero-Mem tool surface to Hermes' public signature."""

    def __init__(self, context: Any) -> None:
        self._context = context

    def register_tool(self, name: str, schema: dict[str, Any], handler: Any) -> None:
        register = getattr(self._context, "register_tool", None)
        if not callable(register):
            raise HermesIntegrationError("Hermes tool registration unavailable")
        try:
            register(
                name,
                "zero_mem",
                schema,
                handler,
                description="Authorized Zero-Mem read surface",
            )
        except TypeError:
            # Synthetic contexts may implement the narrower accepted adapter
            # contract; no host-specific fallback or raw tool is introduced.
            register(name, schema, handler)



__all__ = [
    "BOUNDARY_ID",
    "CONFIG_FILENAME",
    "HermesBoundary",
    "HermesIntegrationError",
    "IntegrationConfig",
    "command",
    "configure_integration",
    "inspect_integration",
    "integration_config_path",
    "load_integration_config",
    "open_hermes_boundary",
    "remove_integration",
]

# No Hermes package is imported by the Zero-Mem release layer. Hermes remains
# optional; the external PluginContext is the only host boundary.
# No network, daemon, service, raw store, SQL, JSONL, or policy mutation lives here.
# End of file.
