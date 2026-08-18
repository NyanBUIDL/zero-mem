"""Versioned, transport-neutral public Zero-Mem lifecycle API."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
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


class AsyncQueueFullError(ZeroMemAPIError):
    pass


class AsyncTimeoutError(ZeroMemAPIError):
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
             consistency_policy: str | None = None, queue_capacity: int = 16) -> "AsyncClient":
        return cls(PublicClient.open(config, writer=writer, consistency_policy=consistency_policy), queue_capacity=queue_capacity)

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
