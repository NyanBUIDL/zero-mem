"""Project-local, opt-in observer registration adapter for Hermes v0.19.1."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from .bridge_config import BridgeConfig, BridgeMetrics, VERIFIED_SUPPORTED_HOOKS
from .capture_adapter import adapt_mapped_event
from .payload_mapping import map_hook_payload


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
            if not self.enabled:
                return None
            payload = kwargs if kwargs else (args[0] if len(args) == 1 else {"args": args})
            try:
                self._observe(hook, payload)
                self.metrics.record(hook, "observed")
            except Exception:
                self.last_diagnostic = RegistrationDiagnostic("callback_failed", hook)
                self.metrics.record(hook, "failed")
            return None
        return callback

    def _observe(self, hook: str, payload: Any) -> None:
        copied = copy.deepcopy(payload)
        mapped = map_hook_payload(
            hook,
            copied,
            project_id=self.config.project_id,
            profile_id=self.config.profile_id,
        )
        if self.store is not None:
            adapt_mapped_event(mapped, store=self.store)

    def shutdown(self) -> None:
        self.enabled = False
        self._registered = ()
        try:
            if self.store is not None and hasattr(self.store, "close"):
                self.store.close()
        except Exception:
            self.last_diagnostic = RegistrationDiagnostic("shutdown_failed")


__all__ = ["RegistrationAdapter", "RegistrationDiagnostic", "RegistrationFailure"]
