from __future__ import annotations

import json
import threading
import time

import pytest

from src.integration.sidecar import SidecarConfig, SidecarStatus, ZeroMemSidecar


def _dispatcher(payload):
    return {
        "status": "OK",
        "tool": payload.get("tool", "memory_query"),
        "items": [{"identity": payload.get("requesting_profile_id")}],
    }


def test_sidecar_rejects_nonfinite_config_deadline() -> None:
    with pytest.raises(ValueError):
        SidecarConfig(default_deadline=float("nan"))
    with pytest.raises(ValueError):
        SidecarConfig(default_deadline=float("inf"))


def test_sidecar_rejects_nonfinite_and_overflowing_request_deadlines() -> None:
    sidecar = ZeroMemSidecar()
    try:
        request = b'{"tool":"memory_query"}'
        assert sidecar.handle(request, wait_timeout=float("nan")).status is SidecarStatus.INVALID_REQUEST
        assert sidecar.handle(request, wait_timeout=float("inf")).status is SidecarStatus.INVALID_REQUEST
        assert sidecar.handle(request, wait_timeout=10**1000).status is SidecarStatus.INVALID_REQUEST
    finally:
        sidecar.close()


def test_sidecar_rejects_deeply_nested_request_json() -> None:
    nested = b'{"tool":"memory_query","nested":[' + (b"[" * 2000) + (b"]" * 2000) + b']}'
    sidecar = ZeroMemSidecar()
    try:
        assert sidecar.handle(nested).status is SidecarStatus.INVALID_REQUEST
    finally:
        sidecar.close()


def test_sidecar_enforces_request_response_bounds() -> None:
    sidecar = ZeroMemSidecar(SidecarConfig(max_request_bytes=32, max_response_bytes=200), dispatcher=_dispatcher)
    try:
        result = sidecar.handle(b'{"tool":"memory_query","query":"x"}')
        assert result.status is SidecarStatus.PAYLOAD_TOO_LARGE
        assert sidecar.handle(b"not-json").status is SidecarStatus.INVALID_REQUEST
    finally:
        sidecar.close()


def test_sidecar_preserves_identity_and_serializes_response() -> None:
    sidecar = ZeroMemSidecar(SidecarConfig(max_request_bytes=1024, max_response_bytes=1024), dispatcher=_dispatcher)
    try:
        result = sidecar.handle(json.dumps({"tool": "memory_query"}).encode(), identity="profile-a")
        assert result.status is SidecarStatus.OK
        assert result.payload["items"][0]["identity"] == "profile-a"
        assert result.bytes_out <= 1024
    finally:
        sidecar.close()


def test_sidecar_rejects_identity_mismatch_and_overload() -> None:
    sidecar = ZeroMemSidecar(SidecarConfig(max_request_bytes=1024, max_response_bytes=1024, max_concurrency=1, max_queue=0), dispatcher=lambda payload: (time.sleep(0.05), {"status": "OK"})[1])
    try:
        mismatch = sidecar.handle(b'{"tool":"memory_query","requesting_profile_id":"other"}', identity="profile-a")
        assert mismatch.status is SidecarStatus.INVALID_REQUEST
        first = sidecar.handle(b'{"tool":"memory_query"}', identity="profile-a", wait_timeout=0.1)
        assert first.status is SidecarStatus.OK
    finally:
        sidecar.close()




def test_sidecar_queue_full_is_bounded() -> None:
    entered = threading.Event()
    release = threading.Event()

    def blocked(_payload):
        entered.set()
        release.wait(timeout=1.0)
        return {"status": "OK"}

    sidecar = ZeroMemSidecar(SidecarConfig(max_concurrency=1, max_queue=0), dispatcher=blocked)
    holder = threading.Thread(target=lambda: sidecar.handle(b'{"tool":"memory_query"}', wait_timeout=0.8))
    holder.start()
    assert entered.wait(timeout=0.5)
    try:
        result = sidecar.handle(b'{"tool":"memory_query"}', wait_timeout=0.0)
        assert result.status is SidecarStatus.OVERLOADED
    finally:
        release.set()
        holder.join(timeout=1.0)
        sidecar.close()


def test_sidecar_dispatch_failure_is_sanitized() -> None:
    def fail(_payload):
        raise RuntimeError("secret /home/private")

    sidecar = ZeroMemSidecar(SidecarConfig(), dispatcher=fail)
    try:
        result = sidecar.handle(b'{"tool":"memory_query"}')
        assert result.status is SidecarStatus.DOWNSTREAM_ERROR
        assert "private" not in json.dumps(result.payload)
    finally:
        sidecar.close()


def test_sidecar_serialization_failure_is_sanitized() -> None:
    sidecar = ZeroMemSidecar(dispatcher=lambda _payload: {"value": object()})
    try:
        result = sidecar.handle(b'{"tool":"memory_query"}')
        assert result.status is SidecarStatus.DOWNSTREAM_ERROR
    finally:
        sidecar.close()


def test_sidecar_recursive_serialization_failure_is_sanitized() -> None:
    nested = {}
    current = nested
    for _ in range(2000):
        current["next"] = {}
        current = current["next"]
    sidecar = ZeroMemSidecar(dispatcher=lambda _payload: nested)
    try:
        result = sidecar.handle(b'{"tool":"memory_query"}')
        assert result.status is SidecarStatus.DOWNSTREAM_ERROR
    finally:
        sidecar.close()


def test_sidecar_timeout_retains_admission_until_work_finishes() -> None:
    entered = threading.Event()
    release = threading.Event()

    def blocked(_payload):
        entered.set()
        release.wait(timeout=1.0)
        return {"status": "OK"}

    sidecar = ZeroMemSidecar(
        SidecarConfig(max_concurrency=1, max_queue=1),
        dispatcher=blocked,
    )
    holder = threading.Thread(
        target=lambda: sidecar.handle(b'{"tool":"memory_query"}', wait_timeout=1.0)
    )
    holder.start()
    assert entered.wait(timeout=0.5)
    queued = threading.Thread(
        target=lambda: sidecar.handle(b'{"tool":"memory_query"}', wait_timeout=1.0)
    )
    queued.start()
    time.sleep(0.02)
    try:
        timed_out = sidecar.handle(b'{"tool":"memory_query"}', wait_timeout=0.01)
        assert timed_out.status is SidecarStatus.DEADLINE_EXCEEDED
        assert sidecar.handle(b'{"tool":"memory_query"}', wait_timeout=0.0).status is SidecarStatus.OVERLOADED
    finally:
        release.set()
        holder.join(timeout=1.0)
        queued.join(timeout=1.0)
        sidecar.close()


def test_sidecar_deadline_covers_admission_and_execution() -> None:
    first_entered = threading.Event()
    first_release = threading.Event()
    second_entered = threading.Event()
    second_release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def staged(_payload):
        nonlocal calls
        with calls_lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            first_entered.set()
            first_release.wait(timeout=1.0)
        else:
            second_entered.set()
            second_release.wait(timeout=1.0)
        return {"status": "OK"}

    sidecar = ZeroMemSidecar(
        SidecarConfig(max_concurrency=1, max_queue=1),
        dispatcher=staged,
    )
    first = threading.Thread(
        target=lambda: sidecar.handle(b'{"tool":"memory_query"}', wait_timeout=1.0)
    )
    second = threading.Thread(
        target=lambda: sidecar.handle(b'{"tool":"memory_query"}', wait_timeout=1.0)
    )
    first.start()
    assert first_entered.wait(timeout=0.5)
    second.start()
    time.sleep(0.02)
    timer = threading.Timer(0.04, first_release.set)
    timer.start()
    started = time.monotonic()
    try:
        result = sidecar.handle(b'{"tool":"memory_query"}', wait_timeout=0.1)
        elapsed = time.monotonic() - started
        assert result.status is SidecarStatus.DEADLINE_EXCEEDED
        # R124-10: the semantic contract is the DEADLINE_EXCEEDED status. The
        # wall-clock ceiling is a sanity bound proving the deadline path
        # returned promptly (well below the sibling request's 1.0s wait), not a
        # latency SLA; 0.13s was flaky on slow macOS CI runners.
        assert elapsed < 1.0
        assert second_entered.wait(timeout=0.2)
    finally:
        first_release.set()
        second_release.set()
        timer.cancel()
        first.join(timeout=1.0)
        second.join(timeout=1.0)
        sidecar.close()


def test_sidecar_close_wakes_admission_waiters() -> None:
    entered = threading.Event()
    release = threading.Event()
    results = []

    def blocked(_payload):
        entered.set()
        release.wait(timeout=1.0)
        return {"status": "OK"}

    sidecar = ZeroMemSidecar(
        SidecarConfig(max_concurrency=1, max_queue=0),
        dispatcher=blocked,
    )
    holder = threading.Thread(
        target=lambda: sidecar.handle(b'{"tool":"memory_query"}', wait_timeout=1.0)
    )
    waiter = threading.Thread(
        target=lambda: results.append(sidecar.handle(b'{"tool":"memory_query"}', wait_timeout=1.0))
    )
    holder.start()
    assert entered.wait(timeout=0.5)
    waiter.start()
    time.sleep(0.02)
    sidecar.close()
    waiter.join(timeout=0.5)
    release.set()
    holder.join(timeout=1.0)
    assert len(results) == 1
    assert results[0].status is SidecarStatus.CLOSED


def test_sidecar_close_returns_closed_for_inflight_requests() -> None:
    entered = threading.Event()
    release = threading.Event()
    results = []

    def blocked(_payload):
        entered.set()
        release.wait(timeout=1.0)
        return {"status": "OK"}

    sidecar = ZeroMemSidecar(
        SidecarConfig(max_concurrency=1, max_queue=1),
        dispatcher=blocked,
    )
    first = threading.Thread(
        target=lambda: results.append(sidecar.handle(b'{"tool":"memory_query"}', wait_timeout=1.0))
    )
    second = threading.Thread(
        target=lambda: results.append(sidecar.handle(b'{"tool":"memory_query"}', wait_timeout=1.0))
    )
    first.start()
    assert entered.wait(timeout=0.5)
    second.start()
    sidecar.close()
    release.set()
    first.join(timeout=1.0)
    second.join(timeout=1.0)
    assert len(results) == 2
    assert all(result.status is SidecarStatus.CLOSED for result in results)
