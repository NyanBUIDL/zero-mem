from __future__ import annotations

"""R124-10 regression: process-global runtime-gate test isolation.

A `HermesBoundary.register()` in OFF/invalid mode configures the module-level
`src.integration.zero_mem_runtime._default_runtime` gate to disabled
(`source="boundary"`). Without the root `conftest.py` autouse isolation fixture,
that process-global state leaked into later tests in the same pytest process:
a `RegistrationAdapter` composed from an explicit `BridgeConfig(enabled=True)`
then observed a disabled gate and silently opened NO writer (canonical JSONL
never created) — an order-dependent failure.

The root fixture snapshots/restores the gate around every test, so the test
below that runs an OFF-mode boundary can never disable the capture adapter in
the NEXT test. These tests prove the isolation WITHOUT weakening the product's
fail-closed OFF semantics (asserted separately in this file and in
`test_wp31_boundary_cannot_reenable_disabled_global_runtime`).
"""

from pathlib import Path

import pytest

from src.integration.bridge_config import BridgeConfig
from src.integration.hermes_registration import RegistrationAdapter
from src.integration.zero_mem_runtime import RuntimeConfig, ZeroMemRuntime


class _HostContext:
    def __init__(self) -> None:
        self.hooks: dict[str, object] = {}
        self.tools: dict[str, object] = {}

    def register_hook(self, name: str, callback: object) -> None:
        self.hooks[name] = callback

    def register_tool(self, *args, **kwargs) -> None:  # pragma: no cover
        self.tools[args[0]] = args[0]


def _register_off_boundary(tmp_path: Path) -> None:
    """Simulate an OFF-mode Hermes boundary registration (the polluter)."""
    import os

    import zero_mem

    os.environ["ZERO_MEM_MODE"] = "off"
    try:
        boundary = zero_mem.open_hermes_boundary(
            project_id="p-isolation",
            profile_id="pr-isolation",
            capture_root=tmp_path / "off-capture",
            store_path=tmp_path / "off-capture" / "derived" / "events.sqlite",
        )
        result = boundary.register(_HostContext())
        assert result == {"hooks": (), "tools": (), "injection": ()}
    finally:
        os.environ.pop("ZERO_MEM_MODE", None)


def test_register_off_boundary_fails_closed(tmp_path: Path) -> None:
    """FIRST in file (pytest default order): pollute the process-global gate.

    Without the root isolation fixture, this test leaves the global runtime
    gate disabled for every later test in the same process.
    """
    _register_off_boundary(tmp_path)
    # The OFF boundary itself must have created no canonical/derived artifacts.
    assert not (tmp_path / "off-capture" / "canonical").exists()


def test_adapter_captures_after_prior_off_boundary(tmp_path: Path) -> None:
    """SECOND in file: a fresh enabled adapter still captures after the OFF run.

    Regression for R124-10: without the root isolation fixture this failed with
    FileNotFoundError (canonical JSONL never written) because the gate stayed
    disabled from the previous test.
    """
    adapter = RegistrationAdapter(
        BridgeConfig(enabled=True, capture_root=tmp_path / "capture"),
    )
    try:
        adapter._observe("on_session_start", {"session_id": "s-isolation"})
        canonical = tmp_path / "capture" / "canonical" / "events-v1.jsonl"
        assert canonical.is_file()
        assert canonical.read_text(encoding="utf-8").strip()
    finally:
        adapter.shutdown()


def test_adapter_captures_without_prior_boundary(tmp_path: Path) -> None:
    """Baseline: a fresh adapter captures with no prior boundary at all."""
    adapter = RegistrationAdapter(
        BridgeConfig(enabled=True, capture_root=tmp_path / "capture"),
    )
    try:
        adapter._observe("on_session_start", {"session_id": "s-baseline"})
        canonical = tmp_path / "capture" / "canonical" / "events-v1.jsonl"
        assert canonical.is_file()
    finally:
        adapter.shutdown()


def test_off_runtime_still_fails_closed_in_isolation(tmp_path: Path) -> None:
    """The product's fail-closed OFF semantics are NOT weakened by isolation.

    A runtime explicitly opened with `enabled=False` must still refuse a writer
    and report ZERO_MEM_DISABLED, exactly as the production contract requires.
    """
    runtime = ZeroMemRuntime.open(RuntimeConfig(capture_root=tmp_path / "capture", enabled=False))
    try:
        assert runtime.health().reason_code == "ZERO_MEM_DISABLED"
        with pytest.raises(RuntimeError, match="RUNTIME_WRITER_UNAVAILABLE"):
            _ = runtime.writer
    finally:
        runtime.close()
