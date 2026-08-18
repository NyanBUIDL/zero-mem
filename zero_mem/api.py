"""Versioned, transport-neutral public Zero-Mem lifecycle API."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .core import CaptureResult, CoreConfig, EventWriter, ZeroMemClient

API_VERSION = "1.0"


class ZeroMemAPIError(RuntimeError):
    """Base typed public API failure."""


class ClientClosedError(ZeroMemAPIError):
    pass


class InvalidRequestError(ZeroMemAPIError):
    pass


@dataclass(frozen=True)
class CapabilityResult:
    capability: str
    status: str
    reason_code: str
    items: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class Health:
    api_version: str
    status: str
    active_session: bool
    writer_configured: bool


class PublicClient:
    """Synchronous generic-agent facade; no internal storage paths are exposed."""

    def __init__(self, config: CoreConfig, *, writer: EventWriter | None = None,
                 consistency_policy: str | None = None) -> None:
        self._client = ZeroMemClient(config, writer=writer, consistency_policy=consistency_policy)
        self._active_session = False
        self._closed = False
        self._writer = writer

    @classmethod
    def open(cls, config: CoreConfig | None = None, *, writer: EventWriter | None = None,
             consistency_policy: str | None = None) -> "PublicClient":
        return cls(config or CoreConfig(), writer=writer, consistency_policy=consistency_policy)

    def _ensure_open(self) -> None:
        if self._closed:
            raise ClientClosedError("client_closed")

    def session_start(self, session_id: str) -> str:
        self._ensure_open()
        if not isinstance(session_id, str) or not session_id.strip():
            raise InvalidRequestError("session_id_required")
        self._active_session = True
        return "SESSION_ACTIVE"

    def observe_message(self, payload: object) -> CaptureResult:
        return self._observe("message", payload)

    def observe_tool_call(self, payload: object) -> CaptureResult:
        return self._observe("tool_call", payload)

    def _observe(self, kind: str, payload: object) -> CaptureResult:
        self._ensure_open()
        if payload is None:
            raise InvalidRequestError("observation_payload_required")
        return self._client.capture({"kind": kind, "payload": payload})

    def sync(self) -> str:
        self._ensure_open()
        for name in ("sync", "flush"):
            method = getattr(self._writer, name, None)
            if callable(method):
                method()
                break
        return "SYNCED"

    def _unavailable(self, capability: str) -> CapabilityResult:
        self._ensure_open()
        return CapabilityResult(capability, "CAPABILITY_UNAVAILABLE", "CAPABILITY_NOT_IMPLEMENTED")

    def search(self, request: Mapping[str, Any] | None = None) -> CapabilityResult:
        return self._unavailable("zero_mem.search")

    def get_trace(self, request: Mapping[str, Any] | None = None) -> CapabilityResult:
        return self._unavailable("zero_mem.get_trace")

    def get_task_state(self, request: Mapping[str, Any] | None = None) -> CapabilityResult:
        return self._unavailable("zero_mem.get_task_state")

    def get_decisions(self, request: Mapping[str, Any] | None = None) -> CapabilityResult:
        return self._unavailable("zero_mem.get_decisions")

    def health(self) -> Health:
        self._ensure_open()
        return Health(API_VERSION, "OK", self._active_session, self._writer is not None)

    def shutdown(self) -> str:
        if self._closed:
            return "ALREADY_SHUTDOWN"
        close = getattr(self._writer, "close", None)
        if callable(close):
            close()
        self._closed = True
        self._active_session = False
        return "SHUTDOWN"

    def __enter__(self) -> "PublicClient":
        self._ensure_open()
        return self

    def __exit__(self, *_args: object) -> None:
        self.shutdown()


__all__ = [
    "API_VERSION", "CapabilityResult", "ClientClosedError", "Health",
    "InvalidRequestError", "PublicClient", "ZeroMemAPIError",
]
