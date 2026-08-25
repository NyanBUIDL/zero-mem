"""Bounded transport-only sidecar for the canonical Zero-Mem dispatcher."""
from __future__ import annotations

import json
import math
import threading
import time
from concurrent.futures import CancelledError, ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from enum import Enum
from numbers import Real
from typing import Any, Callable, cast

from .m6.mcp_wrapper import handle_call


class SidecarStatus(str, Enum):
    OK = "OK"
    INVALID_REQUEST = "INVALID_REQUEST"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    OVERLOADED = "OVERLOADED"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    DOWNSTREAM_ERROR = "DOWNSTREAM_ERROR"
    UNAVAILABLE = "UNAVAILABLE"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class SidecarConfig:
    max_request_bytes: int = 64 * 1024
    max_response_bytes: int = 256 * 1024
    max_concurrency: int = 4
    max_queue: int = 16
    default_deadline: float = 5.0
    max_depth: int = 32
    max_items: int = 4096

    def __post_init__(self) -> None:
        for name in ("max_request_bytes", "max_response_bytes", "max_concurrency"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"invalid {name}")
        for name in ("max_depth", "max_items"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"invalid {name}")
        if isinstance(self.max_queue, bool) or not isinstance(self.max_queue, int) or self.max_queue < 0:
            raise ValueError("invalid max_queue")
        if (
            isinstance(self.default_deadline, bool)
            or not isinstance(self.default_deadline, Real)
            or not _finite_number(self.default_deadline)
            or self.default_deadline <= 0
        ):
            raise ValueError("invalid default_deadline")


def _finite_number(value: Real) -> bool:
    try:
        return math.isfinite(float(value))
    except (OverflowError, ValueError):
        return False


@dataclass(frozen=True)
class SidecarResult:
    status: SidecarStatus
    payload: dict[str, Any]
    bytes_in: int = 0
    bytes_out: int = 0


Dispatcher = Callable[[dict[str, Any]], dict[str, Any]]
_CLOSED_DISPATCH = object()


def _within_bounds(value: Any, *, max_depth: int, max_items: int,
                   depth: int = 0, seen: int = 0) -> tuple[bool, int]:
    """Bound nested JSON structures before dispatch/serialization."""
    if depth > max_depth or seen > max_items:
        return False, seen
    if isinstance(value, dict):
        seen += len(value)
        for key, child in value.items():
            ok, seen = _within_bounds(key, max_depth=max_depth, max_items=max_items, depth=depth + 1, seen=seen)
            if not ok:
                return False, seen
            ok, seen = _within_bounds(child, max_depth=max_depth, max_items=max_items, depth=depth + 1, seen=seen)
            if not ok:
                return False, seen
    elif isinstance(value, (list, tuple)):
        seen += len(value)
        for child in value:
            ok, seen = _within_bounds(child, max_depth=max_depth, max_items=max_items, depth=depth + 1, seen=seen)
            if not ok:
                return False, seen
    return seen <= max_items, seen


class ZeroMemSidecar:
    """Bounded local adapter; all semantics remain in the injected dispatcher."""

    def __init__(self, config: SidecarConfig | None = None, *, dispatcher: Dispatcher | None = None) -> None:
        self.config = config or SidecarConfig()
        self._dispatcher = dispatcher or self._default_dispatch
        self._admission_capacity = self.config.max_concurrency + self.config.max_queue
        self._admitted = 0
        self._executor = ThreadPoolExecutor(max_workers=self.config.max_concurrency, thread_name_prefix="zero-mem-sidecar")
        self._closed = False
        self._close_lock = threading.RLock()
        self._admission_condition = threading.Condition(self._close_lock)
        self._futures: set[Any] = set()
        # DEF-033 (DEF-E1): observable counters distinguishing caller-timeout
        # from still-running work (the admission slot stays held while a
        # started future runs; queued-not-started futures are cancelled).
        self._metrics: dict[str, int] = {
            "caller_timed_out": 0,
            "work_still_running": 0,
            "queued_cancelled_before_start": 0,
            "deadline_exceeded": 0,
            "overloaded": 0,
        }

    @property
    def metrics(self) -> dict[str, int]:
        """Snapshot of the sidecar counters (caller-timeout vs still-running)."""
        with self._admission_condition:
            return dict(self._metrics)

    @staticmethod
    def _default_dispatch(payload: dict[str, Any]) -> dict[str, Any]:
        tool = cast(str, payload["tool"])
        return handle_call(tool, payload)

    def _dispatch_if_open(self, payload: dict[str, Any]) -> dict[str, Any] | object:
        with self._admission_condition:
            if self._closed:
                return _CLOSED_DISPATCH
        return self._dispatcher(payload)

    @staticmethod
    def _result(status: SidecarStatus, *, payload: dict[str, Any] | None = None, bytes_in: int = 0) -> SidecarResult:
        body = payload or {"status": status.value}
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return SidecarResult(status, body, bytes_in, len(raw))

    def _future_done(self, future: Any) -> None:
        with self._admission_condition:
            self._futures.discard(future)
            self._admitted -= 1
            self._admission_condition.notify_all()

    def _acquire_admission(self, deadline: float, *, immediate: bool) -> SidecarStatus | None:
        with self._admission_condition:
            while self._admitted >= self._admission_capacity:
                if self._closed:
                    return SidecarStatus.CLOSED
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return SidecarStatus.OVERLOADED if immediate else SidecarStatus.DEADLINE_EXCEEDED
                self._admission_condition.wait(timeout=remaining)
            if self._closed:
                return SidecarStatus.CLOSED
            self._admitted += 1
            return None

    def handle(self, request: bytes, *, identity: str | None = None, wait_timeout: float | None = None) -> SidecarResult:
        if not isinstance(request, (bytes, bytearray)):
            return self._result(SidecarStatus.INVALID_REQUEST)
        size = len(request)
        if size > self.config.max_request_bytes:
            return self._result(SidecarStatus.PAYLOAD_TOO_LARGE, bytes_in=size)
        with self._close_lock:
            if self._closed:
                return self._result(SidecarStatus.CLOSED, bytes_in=size)
        try:
            payload = json.loads(bytes(request).decode("utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("tool"), str):
                raise ValueError("invalid envelope")
            bounded, _ = _within_bounds(payload, max_depth=self.config.max_depth, max_items=self.config.max_items)
            if not bounded:
                raise ValueError("request bounds exceeded")
            if identity is not None:
                if "requesting_profile_id" in payload and payload["requesting_profile_id"] != identity:
                    return self._result(SidecarStatus.INVALID_REQUEST, bytes_in=size)
                payload["requesting_profile_id"] = identity
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError, TypeError):
            return self._result(SidecarStatus.INVALID_REQUEST, bytes_in=size)

        timeout = self.config.default_deadline if wait_timeout is None else wait_timeout
        if isinstance(timeout, bool) or not isinstance(timeout, Real) or not _finite_number(timeout) or timeout < 0:
            return self._result(SidecarStatus.INVALID_REQUEST, bytes_in=size)
        deadline = time.monotonic() + timeout
        admission_status = self._acquire_admission(deadline, immediate=timeout == 0)
        if admission_status is not None:
            with self._admission_condition:
                if admission_status is SidecarStatus.OVERLOADED:
                    self._metrics["overloaded"] += 1
                else:
                    self._metrics["deadline_exceeded"] += 1
            return self._result(admission_status, bytes_in=size)
        with self._admission_condition:
            if self._closed:
                self._admitted -= 1
                self._admission_condition.notify_all()
                return self._result(SidecarStatus.CLOSED, bytes_in=size)
            try:
                future = self._executor.submit(self._dispatch_if_open, payload)
            except RuntimeError:
                closed = self._closed
                self._admitted -= 1
                self._admission_condition.notify_all()
                status = SidecarStatus.CLOSED if closed else SidecarStatus.UNAVAILABLE
                return self._result(status, bytes_in=size)
            self._futures.add(future)
            future.add_done_callback(self._future_done)
        try:
            response = future.result(timeout=max(0.0, deadline - time.monotonic()))
        except FutureTimeout:
            # DEF-033 (DEF-E1): cancel-before-start — a future that has NOT
            # begun executing is cancelled so the queued work never runs after
            # the caller timed out (parity with the async path, DEF-026). A
            # future already running keeps its admission slot until completion
            # (Python cannot kill a thread safely) and is counted separately.
            cancelled = future.cancel()
            with self._admission_condition:
                if cancelled:
                    self._metrics["queued_cancelled_before_start"] += 1
                else:
                    self._metrics["work_still_running"] += 1
                self._metrics["caller_timed_out"] += 1
            return self._result(SidecarStatus.DEADLINE_EXCEEDED, bytes_in=size)
        except CancelledError:
            return self._result(SidecarStatus.CLOSED, bytes_in=size)
        except Exception:
            return self._result(SidecarStatus.DOWNSTREAM_ERROR, bytes_in=size)
        with self._admission_condition:
            if self._closed:
                return self._result(SidecarStatus.CLOSED, bytes_in=size)
            if not isinstance(response, dict):
                return self._result(SidecarStatus.DOWNSTREAM_ERROR, bytes_in=size)
            try:
                bounded, _ = _within_bounds(response, max_depth=self.config.max_depth, max_items=self.config.max_items)
                if not bounded:
                    return self._result(SidecarStatus.DOWNSTREAM_ERROR, bytes_in=size)
                raw = json.dumps(response, sort_keys=True, separators=(",", ":")).encode("utf-8")
            except (TypeError, ValueError, OverflowError, RecursionError):
                return self._result(SidecarStatus.DOWNSTREAM_ERROR, bytes_in=size)
            if len(raw) > self.config.max_response_bytes:
                return self._result(SidecarStatus.PAYLOAD_TOO_LARGE, bytes_in=size)
            return SidecarResult(SidecarStatus.OK, response, size, len(raw))

    def close(self, timeout: float | None = None) -> bool:
        """Close admission and report whether owned work fully terminated.

        Running dispatcher code is not forcibly interrupted: Python cannot safely
        kill an arbitrary thread. With ``timeout`` supplied, the method waits only
        that long and returns ``False`` if a cooperative dispatcher is still
        running. With no timeout it performs immediate close and returns ``False``
        whenever in-flight work exists. Late results are discarded by closed-state
        checks; queued work is cancelled before it can enter the dispatcher.
        """
        if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, Real) or not _finite_number(timeout) or timeout < 0):
            raise ValueError("invalid close timeout")
        wait_deadline = time.monotonic() + float(timeout or 0.0)
        with self._admission_condition:
            if self._closed:
                return True
            self._closed = True
            futures = tuple(self._futures)
            self._admission_condition.notify_all()
        for future in futures:
            future.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)
        complete = True
        for future in futures:
            remaining = wait_deadline - time.monotonic()
            if remaining <= 0:
                if not future.done():
                    complete = False
                continue
            try:
                future.result(timeout=remaining)
            except Exception:
                pass
            if not future.done():
                complete = False
        return complete



__all__ = ["SidecarConfig", "SidecarResult", "SidecarStatus", "ZeroMemSidecar"]
