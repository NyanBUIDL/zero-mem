"""Project-local, opt-in observer registration adapter for Hermes v0.19.1."""
from __future__ import annotations

import copy
import threading
from dataclasses import dataclass
from typing import Any

from .bridge_config import BridgeConfig, BridgeMetrics, VERIFIED_SUPPORTED_HOOKS
from .capture_adapter import adapt_mapped_event
from .payload_mapping import MappingResult, map_hook_payload
from .zero_mem_runtime import RuntimeConfig, ZeroMemRuntime, configure as configure_zero_mem_runtime, get_runtime
from zero_mem.core import AppendReceipt, CoreConfig, ZeroMemClient


class RegistrationFailure(RuntimeError):
    """Sanitized registration failure."""


@dataclass(frozen=True)
class RegistrationDiagnostic:
    code: str
    hook: str | None = None


class RegistrationAdapter:
    """Register only verified observer hooks against a plugin context-like API."""

    def __init__(self, config: BridgeConfig, *, store: Any = None) -> None:
        self.config = config
        self.enabled = bool(config.enabled)
        self.store = store
        self.metrics = BridgeMetrics()
        self._registered: tuple[str, ...] = ()
        self.last_diagnostic: RegistrationDiagnostic | None = None
        # M7.1 master runtime gate: resolve the single shared authority from the
        # canonical config value. Master OFF dominates adapter-local enabled state.
        try:
            get_runtime()
        except RuntimeError:
            configure_zero_mem_runtime(enabled=bool(config.zero_mem_enabled))
        self._zero_mem = get_runtime()
        self._lifecycle_lock = threading.RLock()
        effective_enabled = bool(config.zero_mem_enabled) and self._zero_mem.is_enabled()
        self.runtime = ZeroMemRuntime.open(
            RuntimeConfig(config.capture_root, enabled=effective_enabled),
            store=store,
        )
        runtime_writer = _CaptureWriter(self.runtime.writer) if effective_enabled else None
        self._client = ZeroMemClient(
            CoreConfig(
                enabled=effective_enabled,
                project_id=config.project_id,
                profile_id=config.profile_id,
            ),
            writer=runtime_writer,
            consistency_policy="append-only" if runtime_writer is not None else None,
        )

    def register(self, context: Any) -> tuple[str, ...]:
        if not self.enabled:
            return ()
        if not hasattr(context, "register_hook") or not callable(context.register_hook):
            self.last_diagnostic = RegistrationDiagnostic("registration_unavailable")
            raise RegistrationFailure("registration_unavailable")
        if self._registered:
            return self._registered
        callbacks: list[str] = []
        try:
            for hook in VERIFIED_SUPPORTED_HOOKS:
                context.register_hook(hook, self._make_callback(hook))
                callbacks.append(hook)
                self.metrics.record(hook, "registered")
        except Exception:
            self.last_diagnostic = RegistrationDiagnostic("registration_failed")
            return tuple(callbacks)
        self._registered = tuple(callbacks)
        return self._registered

    def _make_callback(self, hook: str):
        def callback(*args: Any, **kwargs: Any) -> None:
            try:
                if not get_runtime().is_enabled() or not self.enabled:
                    return None
                payload = kwargs if kwargs else (args[0] if len(args) == 1 else {"args": args})
                self._observe(hook, payload)
                self.metrics.record(hook, "observed")
            except Exception:
                self.last_diagnostic = RegistrationDiagnostic("callback_failed", hook)
                self.metrics.record(hook, "failed")
            return None
        return callback

    def _observe(self, hook: str, payload: Any) -> None:
        # M7.1 master gate: OFF => deterministic no-op (no redaction, no schema
        # processing, no canonical append, no derived-state update). Valid bypass
        # state, not an error.
        with self._lifecycle_lock:
            runtime = get_runtime()
            if not runtime.is_enabled():
                return
            copied = copy.deepcopy(payload)
            mapped = map_hook_payload(
                hook,
                copied,
                project_id=self.config.project_id,
                profile_id=self.config.profile_id,
            )
            if self.runtime.is_enabled() and runtime.is_enabled():
                self._client.capture(mapped)

    def restart(self) -> None:
        """Reopen the owned runtime without registering duplicate callbacks."""
        self.shutdown()
        self.__init__(self.config, store=self.store)

    def shutdown(self) -> None:
        with self._lifecycle_lock:
            self.enabled = False
            self._registered = ()
            try:
                self.runtime.close()
            except Exception:
                self.last_diagnostic = RegistrationDiagnostic("shutdown_failed")


__all__ = ["RegistrationAdapter", "RegistrationDiagnostic", "RegistrationFailure"]


class _CaptureWriter:
    """Translate the generic client append into the existing capture adapter."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def append(self, event: object) -> AppendReceipt:
        result = adapt_mapped_event(event if isinstance(event, MappingResult) else None, store=self._store)
        if result.code == "appended":
            return AppendReceipt("appended", result.event_id, result.sequence, True)
        if result.code.startswith("duplicate_"):
            return AppendReceipt(
                "duplicate",
                result.event_id,
                result.sequence,
                True,
                duplicate_class=result.duplicate_class,
                reason_code="CANONICAL_DUPLICATE",
            )
        return AppendReceipt(
            "failed",
            result.event_id,
            result.sequence,
            False,
            reason_code="CANONICAL_APPEND_REJECTED",
        )
