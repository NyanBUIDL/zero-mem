"""Versioned, transport-neutral public Zero-Mem lifecycle API."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .core import CaptureResult, CoreConfig, EventWriter, ZeroMemClient

API_VERSION = "1.0"


class ZeroMemAPIError(RuntimeError):
    """Base typed public API failure."""


class ClientClosedError(ZeroMemAPIError):
    pass


class InvalidRequestError(ZeroMemAPIError):
    pass


class AsyncQueueFullError(ZeroMemAPIError):
    pass


class AsyncTimeoutError(ZeroMemAPIError):
    pass


class PublicReadService(Protocol):
    """Injected authorized read boundary; the public module stays storage-neutral."""
    def search(self, request: Mapping[str, Any] | None = None) -> Any: ...
    def get_trace(self, request: Mapping[str, Any] | None = None) -> Any: ...
    def get_task_state(self, request: Mapping[str, Any] | None = None) -> Any: ...
    def get_decisions(self, request: Mapping[str, Any] | None = None) -> Any: ...


@dataclass(frozen=True)
class CapabilityResult:
    capability: str
    status: str
    reason_code: str
    items: tuple[Mapping[str, Any], ...] = ()
    provenance: tuple[Mapping[str, Any], ...] = ()
    freshness: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class Health:
    api_version: str
    status: str
    active_session: bool
    writer_configured: bool
    runtime_mode: str | None = None
    capture_enabled: bool | None = None
    read_enabled: bool | None = None
    injection_enabled: bool | None = None
    writer_open: bool | None = None
    canonical_store_identity: str | None = None
    derived_store_identity: str | None = None
    last_canonical_sequence: int | None = None
    last_projected_sequence: int | None = None
    lag: int | None = None
    projection_status: str | None = None
    last_projection_error: str | None = None
    readiness: str | None = None
    reason_code: str | None = None


class HealthProvider(Protocol):
    """Injected truthful runtime health source; the public module stays storage-neutral.

    Implementations must return a mapping with the keys defined by VALIDATION_SPEC
    (runtime_mode, capture_enabled, read_enabled, injection_enabled, writer_open,
    canonical/derived_store_identity, last_canonical/projected_sequence, lag,
    projection_status, last_projection_error, status, readiness, reason_code).
    """

    def health(self) -> Mapping[str, Any]: ...
    def sync_status(self) -> str: ...


class PublicClient:
    """Synchronous generic-agent facade; no internal storage paths are exposed."""

    def __init__(self, config: CoreConfig, *, writer: EventWriter | None = None,
                 consistency_policy: str | None = None,
                 read_service: PublicReadService | None = None,
                 health_provider: HealthProvider | None = None) -> None:
        self._client = ZeroMemClient(config, writer=writer, consistency_policy=consistency_policy)
        self._active_session = False
        self._closed = False
        self._writer = writer
        self._read_service = read_service
        self._health_provider = health_provider

    @classmethod
    def open(cls, config: CoreConfig | None = None, *, writer: EventWriter | None = None,
             consistency_policy: str | None = None,
             read_service: PublicReadService | None = None,
             health_provider: HealthProvider | None = None) -> "PublicClient":
        return cls(config or CoreConfig(), writer=writer, consistency_policy=consistency_policy,
                   read_service=read_service, health_provider=health_provider)

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
        """Backward-compatible alias for a user-authored message."""
        return self.observe_user_message(payload)

    def observe_user_message(self, payload: object) -> CaptureResult:
        return self._observe("user_message", payload)

    def observe_assistant_message(self, payload: object) -> CaptureResult:
        return self._observe("assistant_message", payload)

    def observe_tool_call(self, payload: object) -> CaptureResult:
        return self._observe("tool_call", payload)

    def _observe(self, kind: str, payload: object) -> CaptureResult:
        self._ensure_open()
        if payload is None:
            raise InvalidRequestError("observation_payload_required")
        return self._client.capture({"kind": kind, "payload": payload})

    def sync(self) -> str:
        self._ensure_open()
        # R124-03: never claim SYNCED/CURRENT merely because a flush method was
        # called. Delegate to the injected runtime provider; absent a provider,
        # fall back to the writer flush but truthfully report the legacy state.
        if self._health_provider is not None:
            return str(self._health_provider.sync_status())
        for name in ("sync", "flush"):
            method = getattr(self._writer, name, None)
            if callable(method):
                method()
                break
        return "SYNCED"

    def _unavailable(self, capability: str) -> CapabilityResult:
        self._ensure_open()
        return CapabilityResult(capability, "CAPABILITY_UNAVAILABLE", "CAPABILITY_NOT_IMPLEMENTED")

    def health(self) -> Health:
        self._ensure_open()
        # R124-03: when a truthful runtime provider is wired, surface its real
        # freshness/watermark state. The public health response must never
        # self-green to mask a lagging or unavailable derived store.
        if self._health_provider is not None:
            raw = self._health_provider.health()
            return Health(
                api_version=API_VERSION,
                status=str(raw.get("status", "UNKNOWN")),
                active_session=self._active_session,
                writer_configured=self._writer is not None,
                runtime_mode=raw.get("mode"),
                capture_enabled=raw.get("capture_enabled"),
                read_enabled=raw.get("read_enabled"),
                injection_enabled=raw.get("injection_enabled"),
                writer_open=raw.get("writer_open"),
                canonical_store_identity=raw.get("canonical_store_identity"),
                derived_store_identity=raw.get("read_store_identity"),
                last_canonical_sequence=raw.get("last_canonical_sequence"),
                last_projected_sequence=raw.get("last_projected_sequence"),
                lag=raw.get("lag"),
                projection_status=raw.get("projection_status"),
                last_projection_error=raw.get("last_projection_error"),
                readiness=raw.get("readiness"),
                reason_code=raw.get("reason_code"),
            )
        # No provider wired: report the REAL client state instead of unconditionally
        # "OK". R124-03 — the public surface must not self-green; an unconfigured or
        # closed client is reported truthfully.
        if self._writer is None:
            status = "UNCONFIGURED"
        else:
            status = "OK"
        return Health(API_VERSION, status, self._active_session, self._writer is not None)

    def _read(self, capability: str, request: Mapping[str, Any] | None) -> CapabilityResult:
        self._ensure_open()
        if self._read_service is None:
            return self._unavailable(capability)
        method_name = capability.rsplit(".", 1)[-1]
        try:
            raw = getattr(self._read_service, method_name)(request or {})
        except TimeoutError:
            return CapabilityResult(capability, "TIMEOUT", "READ_TIMEOUT")
        except Exception:
            return CapabilityResult(capability, "UNAVAILABLE", "READ_UNAVAILABLE")
        status = getattr(raw, "status", None)
        reason = getattr(raw, "reason_code", None)
        if getattr(raw, "denied", False):
            status, reason = "DENIED", str(reason or "READ_DENIED")
        elif getattr(raw, "error", None) is not None:
            status, reason = "UNAVAILABLE", "READ_UNAVAILABLE"
        else:
            status, reason = str(status or "READY"), str(reason or "READ_OK")
        items = getattr(raw, "items", ()) or ()
        normalized = tuple(item if isinstance(item, Mapping) else {"value": item} for item in items)
        return CapabilityResult(capability, status, reason, normalized,
                                tuple(getattr(raw, "provenance", ()) or ()),
                                getattr(raw, "freshness", None))

    def search(self, request: Mapping[str, Any] | None = None) -> CapabilityResult:
        return self._read("zero_mem.search", request)

    def get_trace(self, request: Mapping[str, Any] | None = None) -> CapabilityResult:
        return self._read("zero_mem.get_trace", request)

    def get_task_state(self, request: Mapping[str, Any] | None = None) -> CapabilityResult:
        return self._read("zero_mem.get_task_state", request)

    def get_decisions(self, request: Mapping[str, Any] | None = None) -> CapabilityResult:
        return self._read("zero_mem.get_decisions", request)

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


class AsyncClient:
    """Bounded async wrapper; blocking work runs on one owned worker."""

    def __init__(self, sync_client: PublicClient, *, queue_capacity: int = 16) -> None:
        if not isinstance(queue_capacity, int) or queue_capacity < 1:
            raise InvalidRequestError("queue_capacity_invalid")
        self._sync = sync_client
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="zero-mem")
        self._slots = asyncio.BoundedSemaphore(queue_capacity)
        self._closed = False

    @classmethod
    def open(cls, config: CoreConfig | None = None, *, writer: EventWriter | None = None,
             consistency_policy: str | None = None, read_service: PublicReadService | None = None,
             health_provider: HealthProvider | None = None,
             queue_capacity: int = 16) -> "AsyncClient":
        return cls(PublicClient.open(config, writer=writer, consistency_policy=consistency_policy,
                                     read_service=read_service, health_provider=health_provider),
                   queue_capacity=queue_capacity)

    async def _call(self, operation: Any, *, deadline: float | None = None) -> Any:
        if self._closed:
            raise ClientClosedError("client_closed")
        try:
            acquire = self._slots.acquire()
            if deadline is None:
                await acquire
            else:
                await asyncio.wait_for(acquire, timeout=deadline)
        except asyncio.TimeoutError:
            raise AsyncQueueFullError("async_queue_full") from None
        try:
            loop = asyncio.get_running_loop()
            future = loop.run_in_executor(self._executor, operation)
            if deadline is None:
                return await future
            return await asyncio.wait_for(future, timeout=deadline)
        except asyncio.TimeoutError:
            raise AsyncTimeoutError("async_operation_timeout") from None
        finally:
            self._slots.release()

    async def session_start(self, session_id: str, *, deadline: float | None = None) -> str:
        return await self._call(lambda: self._sync.session_start(session_id), deadline=deadline)

    async def observe_message(self, payload: object, *, deadline: float | None = None) -> CaptureResult:
        return await self._call(lambda: self._sync.observe_message(payload), deadline=deadline)

    async def observe_user_message(self, payload: object, *, deadline: float | None = None) -> CaptureResult:
        return await self._call(lambda: self._sync.observe_user_message(payload), deadline=deadline)

    async def observe_assistant_message(self, payload: object, *, deadline: float | None = None) -> CaptureResult:
        return await self._call(lambda: self._sync.observe_assistant_message(payload), deadline=deadline)

    async def observe_tool_call(self, payload: object, *, deadline: float | None = None) -> CaptureResult:
        return await self._call(lambda: self._sync.observe_tool_call(payload), deadline=deadline)

    async def sync(self, *, deadline: float | None = None) -> str:
        return await self._call(self._sync.sync, deadline=deadline)

    async def health(self) -> Health:
        if self._closed:
            raise ClientClosedError("client_closed")
        return self._sync.health()

    async def aclose(self) -> str:
        if self._closed:
            return "ALREADY_SHUTDOWN"
        self._closed = True
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(self._executor, self._sync.shutdown)
        self._executor.shutdown(wait=True)
        return result

    async def __aenter__(self) -> "AsyncClient":
        if self._closed:
            raise ClientClosedError("client_closed")
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()


__all__ = [
    "API_VERSION", "AsyncClient", "AsyncQueueFullError", "AsyncTimeoutError",
    "CapabilityResult", "ClientClosedError", "Health", "InvalidRequestError",
    "PublicClient", "ZeroMemAPIError",
]
