"""RED-first draft — DEF-E1 (P3): sync sidecar lacks cancel-before-start on
caller timeout; no metrics distinguishing "caller timed out" vs "work still
running".

Static evidence (src/integration/sidecar.py handle()):
  - `response = future.result(timeout=...)` -> on FutureTimeout the future is
    NOT cancelled: queued-not-started work still executes later and holds its
    admission slot until completion. The async path (zero_mem/api.py) has real
    cancel-before-start (DEF-026 verified); the sync sidecar does not.
  - No metrics surface: no counters for timeouts / still-running / queue depth.

Post-fix contract: on caller timeout the queued-not-started future is cancelled
(future.cancel() -> True => `_dispatch_if_open` never runs, admission released
by the done callback); running work continues (documented Python limitation);
the sidecar exposes counters that distinguish timed-out-caller vs still-running.

DRAFT STATUS: written without execution (no Python in environment).
Run: python -m pytest tests/unit/test_v151_audit_e1_sidecar_cancel.py
"""
from __future__ import annotations

import threading
import time

import pytest

from src.integration.sidecar import (
    SidecarConfig,
    SidecarStatus,
    ZeroMemSidecar,
)


class _BlockingDispatcher:
    """Blocks the first call until released; counts invocations."""

    def __init__(self) -> None:
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, payload: dict) -> dict:
        self.calls += 1
        if self.calls == 1:
            self.entered.set()
            if not self.release.wait(timeout=5.0):
                raise RuntimeError("test release not signalled")
        return {"tool": payload["tool"], "status": "OK"}


class TestDefE1SidecarTimeoutLifecycle:
    def test_queued_timed_out_future_cancelled_before_start(self):
        disp = _BlockingDispatcher()
        sidecar = ZeroMemSidecar(
            SidecarConfig(max_concurrency=1, max_queue=1,
                          default_deadline=5.0),
            dispatcher=disp,
        )
        try:
            payload = b'{"tool":"memory_query"}'
            results: dict = {}
            # r1 occupies the single worker (blocks) in a background thread.
            t = threading.Thread(
                target=lambda: results.setdefault(
                    "r1", sidecar.handle(payload, wait_timeout=5.0)))
            t.start()
            assert disp.entered.wait(2.0), "worker never entered dispatcher"
            # r2 is queued behind the blocked worker and times out.
            r2 = sidecar.handle(payload, wait_timeout=0.05)
            assert r2.status == SidecarStatus.DEADLINE_EXCEEDED
            # r3: admission is capacity-bounded; either full or also timed out.
            r3 = sidecar.handle(payload, wait_timeout=0.05)
            assert r3.status in (
                SidecarStatus.DEADLINE_EXCEEDED, SidecarStatus.OVERLOADED)
            disp.release.set()
            t.join(timeout=5.0)
            assert results["r1"].status == SidecarStatus.OK, (
                "the running request must complete after release")
            time.sleep(0.2)  # let any queued work drain
            # With cancel-before-start, the timed-out QUEUED future never runs:
            assert disp.calls == 1, (
                "timed-out queued work must be cancelled before start; "
                f"dispatcher called {disp.calls} times")
        finally:
            sidecar.close()

    def test_metrics_distinguish_timeout_vs_running(self):
        disp = _BlockingDispatcher()
        sidecar = ZeroMemSidecar(
            SidecarConfig(max_concurrency=1, max_queue=1,
                          default_deadline=0.05),
            dispatcher=disp,
        )
        try:
            payload = b'{"tool":"memory_query"}'
            sidecar.handle(payload)
            sidecar.handle(payload, wait_timeout=0.05)
            disp.release.set()
            time.sleep(0.2)
            # A metrics surface must exist and separate the two conditions:
            assert hasattr(sidecar, "metrics"), (
                "sidecar must expose metrics")
            m = sidecar.metrics
            assert "caller_timed_out" in m, (
                "metrics must count caller timeouts")
            assert "work_still_running" in m, (
                "metrics must count work still running after caller timeout")
            assert m["caller_timed_out"] >= 1
        finally:
            sidecar.close()

    def test_admission_slot_released_exactly_once(self):
        disp = _BlockingDispatcher()
        sidecar = ZeroMemSidecar(
            SidecarConfig(max_concurrency=1, max_queue=1,
                          default_deadline=0.05),
            dispatcher=disp,
        )
        try:
            payload = b'{"tool":"memory_query"}'
            sidecar.handle(payload)
            sidecar.handle(payload, wait_timeout=0.05)
            disp.release.set()
            time.sleep(0.2)
            # After drain, admission must be fully released (no leak).
            assert sidecar._admitted == 0, (
                f"admission leaked: _admitted={sidecar._admitted}")
        finally:
            sidecar.close()
