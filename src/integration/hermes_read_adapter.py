"""M6.5 - thin Hermes READ-tool registration/adapter for Zero-Mem v0.19.1.

Project-local, opt-in adapter that exposes the VERIFIED M6 read-only tool
surface to Hermes through the supported external plugin-context registration
surface. It does NOT modify Hermes core.

It reuses M6.1-M6.4:
* tool schemas come from ``m6.mcp_wrapper.tool_schemas``;
* every call is forwarded through ``m6.mcp_wrapper.handle_call`` -> Dispatcher
  -> M5 AuthorizedReadService -> M3/M4 TRUE READ-ONLY.

Adapter responsibilities are limited to:
* tool discovery/registration (forwarding M6 tool schemas);
* request forwarding (delegating to the M6 MCP wrapper);
* response serialization (already sanitized by M6);
* lifecycle (startup/shutdown/restart);
* local transport connection state (stdio/loopback owned by the host).

The adapter contains NO SQL, NO JSONL logic, NO policy/grant/M3/M4/relation
logic, NO ranking/selection/injection, NO LLM, NO network. It forwards and
serializes only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from .bridge_config import BridgeConfig
from .m6 import configure as _configure_m6
from .m6.mcp_wrapper import tool_schemas
from .sidecar import SidecarConfig, ZeroMemSidecar
from .zero_mem_runtime import configure as configure_zero_mem_runtime, get_runtime

# Exactly the approved M6 read tools (no extra/hidden tools).
ALL_READ_TOOLS: Final[tuple[str, ...]] = (
    "memory_query",
    "memory_search",
    "memory_get_event",
    "memory_get_related",
    "project_get_charter",
    "project_list_requirements",
    "project_list_decisions",
    "project_get_state",
    "project_list_verifications",
    "project_list_artifacts",
    "corpus_search",  # M6.5: derived corpus knowledge-base read (authorization-safe)
)

# Forbidden convenience/write/admin tool names that must NEVER be registered.
FORBIDDEN_TOOL_NAMES: Final[tuple[str, ...]] = (
    "execute_sql",
    "sqlite_query",
    "raw_sql",
    "database_query",
    "read_jsonl",
    "raw_jsonl",
    "write_memory",
    "create_memory",
    "update_memory",
    "delete_memory",
    "project_set_state",
    "project_create_requirement",
    "project_create_decision",
    "create_grant",
    "revoke_grant",
    "supersede_grant",
    "grant_admin",
)


class RegistrationFailure(RuntimeError):
    """Sanitized registration failure (never carries internals)."""


@dataclass(frozen=True)
class RegistrationDiagnostic:
    code: str
    tool: str | None = None


class HermesReadAdapter:
    """Register the M6 read tools against a plugin context-like API.

    The adapter is transport/policy-agnostic: it forwards calls to the verified
    M6 dispatcher and returns the already-sanitized M6 envelope.
    """

    def __init__(self, config: BridgeConfig, *, store_path: str | Path | None = None) -> None:
        self.config = config
        self.enabled = bool(config.enabled)
        # M7.1 master runtime gate: resolve the single shared authority from the
        # canonical config value. Master OFF dominates adapter-local enabled state.
        try:
            current_runtime = get_runtime()
        except RuntimeError:
            configure_zero_mem_runtime(enabled=bool(config.zero_mem_enabled), source="adapter")
        else:
            if current_runtime.is_enabled() or current_runtime.source == "adapter":
                configure_zero_mem_runtime(enabled=bool(config.zero_mem_enabled), source="adapter")
        self._zero_mem = get_runtime()
        # Store path resolved explicitly; no cwd/home inference.
        self.store_path = Path(store_path).expanduser().resolve() if store_path is not None else None
        self.metrics: dict[str, int] = {}
        self._registered: tuple[str, ...] = ()
        self._runtime_started = False
        self.last_diagnostic: RegistrationDiagnostic | None = None
        self._sidecar: ZeroMemSidecar | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def startup(self) -> None:
        """Deterministic, safe startup: validate config + confirm readable DB.

        Performs NO migration, NO rebuild, NO mutation of M3/M4/M5 tables or
        canonical JSONL. Raises a sanitized RegistrationFailure if the store is
        unusable so Hermes can remain alive.

        M7.1 master gate: when Zero-Mem is disabled, startup is a clean no-op.
        The DB is NOT opened merely to know the system is disabled.
        """
        if not self._zero_mem.is_enabled():
            return
        if not self.enabled:
            return
        if self.store_path is None:
            self.last_diagnostic = RegistrationDiagnostic("config_missing_store_path")
            raise RegistrationFailure("config_missing_store_path")
        from src.retrieval.db import open_readonly

        try:
            ro = open_readonly(self.store_path)
        except Exception:
            self.last_diagnostic = RegistrationDiagnostic("store_unavailable")
            raise RegistrationFailure("store_unavailable")
        try:
            # Read-only presence check only (TRUE READ-ONLY).
            ro.conn.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
        except Exception:
            ro.close()
            self.last_diagnostic = RegistrationDiagnostic("store_unreadable")
            raise RegistrationFailure("store_unreadable")
        ro.close()
        # Initialize the read-only M6 runtime (no writes).
        _configure_m6(self.store_path)
        self._sidecar = ZeroMemSidecar(SidecarConfig())
        self._runtime_started = True

    def register(self, context: Any) -> tuple[str, ...]:
        """Register approved M6 read tools against a plugin context.

        Returns the tuple of registered tool names. Idempotent. Raises
        RegistrationFailure only when the context lacks the supported
        registration surface (so callers can degrade gracefully).
        """
        if not self.enabled:
            return ()
        if not self._runtime_started:
            try:
                self.startup()
            except RegistrationFailure:
                return ()
        if not hasattr(context, "register_tool") or not callable(context.register_tool):
            self.last_diagnostic = RegistrationDiagnostic("registration_unavailable")
            raise RegistrationFailure("registration_unavailable")
        if self._registered:
            return self._registered  # idempotent re-registration
        registered: list[str] = []
        try:
            for spec in tool_schemas():
                name = spec["name"]
                if name in FORBIDDEN_TOOL_NAMES:
                    continue
                context.register_tool(name, spec["inputSchema"], self._make_handler(name))
                registered.append(name)
                self.metrics[name] = self.metrics.get(name, 0) + 1
        except Exception:
            self.last_diagnostic = RegistrationDiagnostic("registration_failed")
            return tuple(registered)
        self._registered = tuple(registered)
        return self._registered

    def _disabled_response(self) -> dict[str, Any]:
        """Sanitized master-disabled envelope. Distinct from CAPABILITY_UNAVAILABLE,
        EMPTY, POLICY_DENIED, and INVALID_REQUEST."""
        return {
            "status": "CAPABILITY_UNAVAILABLE",
            "reason_code": "ZERO_MEM_DISABLED",
            "diagnostics": {"bounded": True, "master_switch": False},
        }

    def _sidecar_call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            if not get_runtime().is_enabled():
                return {"status": "DISABLED", "reason_code": "ZERO_MEM_DISABLED"}
        except Exception:
            return {"status": "CAPABILITY_UNAVAILABLE", "reason_code": "master_gate_unavailable"}
        if self._sidecar is None:
            return {"status": "CAPABILITY_UNAVAILABLE", "reason_code": "adapter_not_ready"}
        payload = dict(arguments or {})
        payload["tool"] = tool_name
        try:
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError, OverflowError):
            return {"status": "DOWNSTREAM_ERROR", "reason_code": "DOWNSTREAM_ERROR", "diagnostics": {"bounded": True}}
        result = self._sidecar.handle(
            encoded,
            identity=self.config.profile_id,
        )
        return result.payload

    def _make_handler(self, tool_name: str):
        def handler(arguments: dict[str, Any]) -> dict[str, Any]:
            try:
                if not get_runtime().is_enabled():
                    return self._disabled_response()
            except Exception:
                return {"status": "CAPABILITY_UNAVAILABLE", "reason_code": "master_gate_unavailable"}
            if not self.enabled or not self._runtime_started:
                return {"status": "CAPABILITY_UNAVAILABLE", "reason_code": "adapter_not_ready"}
            try:
                # Forward through the verified M6 transport (no adapter policy).
                return self._sidecar_call(tool_name, arguments or {})
            except Exception:
                # Localized sanitized failure; never leak internals.
                return {
                    "status": "DOWNSTREAM_ERROR",
                    "reason_code": "DOWNSTREAM_ERROR",
                    "diagnostics": {"bounded": True},
                }
        return handler

    # ------------------------------------------------------------------
    # Direct adapter call (no plugin context required)
    # ------------------------------------------------------------------
    def call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Forward a single tool call through the M6 transport (adapter path).

        M7.1 master gate is consulted first: when Zero-Mem is disabled, every
        approved M6 tool returns the sanitized ZERO_MEM_DISABLED envelope without
        opening the DB, resolving grants, or querying M3/M4.
        """
        if not self._zero_mem.is_enabled():
            return self._disabled_response()
        if not self.enabled or not self._runtime_started:
            return {"status": "CAPABILITY_UNAVAILABLE", "reason_code": "adapter_not_ready"}
        return self._sidecar_call(tool_name, arguments or {})

    def list_tools(self) -> list[dict[str, Any]]:
        """Return the Hermes-visible tool schemas (matches M6 contract)."""
        return tool_schemas()

    def shutdown(self) -> None:
        """Clean shutdown: drop registration + runtime state. No writes."""
        self.enabled = False
        self._registered = ()
        self._runtime_started = False
        if self._sidecar is not None:
            self._sidecar.close()
            self._sidecar = None
        self.last_diagnostic = RegistrationDiagnostic("shutdown_clean")

    def restart(self) -> None:
        """Safe restart: re-run startup + registration deterministically."""
        self.shutdown()
        self.enabled = bool(self.config.enabled)
        self.startup()


__all__ = [
    "HermesReadAdapter",
    "RegistrationDiagnostic",
    "RegistrationFailure",
    "ALL_READ_TOOLS",
    "FORBIDDEN_TOOL_NAMES",
]
