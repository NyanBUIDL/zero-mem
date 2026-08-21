"""V124-02 — explicit runtime-mode truth table and negative registration tests.

Each truth-table cell is asserted DIRECTLY, not inferred from one enabled flag
(per docs/v1.2.4/VALIDATION_SPEC.md runtime-mode truth table).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.integration.zero_mem_runtime import (
    RuntimeConfig,
    RuntimeHealth,
    RuntimeMode,
    ZeroMemRuntime,
    mode_injection_enabled,
    mode_read_enabled,
    parse_runtime_mode,
)


def _matrix_for(mode) -> dict[str, bool]:
    return {
        "writer_open": (
            ZeroMemRuntime.open(RuntimeConfig(capture_root=Path("/tmp/x"), enabled=True, mode=mode)).is_enabled()
            if mode != RuntimeMode.OFF else False
        ),
        "read_enabled": ZeroMemRuntime.mode_read_enabled(mode),
        "injection_enabled": ZeroMemRuntime.mode_injection_enabled(mode),
    }


@pytest.mark.parametrize("raw,expected", [
    ("off", RuntimeMode.OFF),
    ("observe", RuntimeMode.OBSERVE),
    ("assist", RuntimeMode.ASSIST),
    ("inject", RuntimeMode.INJECT),
    ("OFF", RuntimeMode.OFF),
    ("InJeCt", RuntimeMode.INJECT),
])
def test_parse_runtime_mode_accepts_canonical_values(raw, expected) -> None:
    assert parse_runtime_mode(raw) is expected


@pytest.mark.parametrize("raw", ["bogus", "", "capture", "read", "disabled", "true", "1"])
def test_parse_runtime_mode_rejects_unknown(raw) -> None:
    with pytest.raises(ValueError, match="runtime_mode"):
        parse_runtime_mode(raw)


# --- Truth table: writer opened -----------------------------------------
@pytest.mark.parametrize("mode,opened", [
    (RuntimeMode.OFF, False),
    (RuntimeMode.OBSERVE, True),
    (RuntimeMode.ASSIST, True),
    (RuntimeMode.INJECT, True),
])
def test_truth_table_writer_opened(tmp_path: Path, mode, opened) -> None:
    runtime = ZeroMemRuntime.open(RuntimeConfig(capture_root=tmp_path / "c", enabled=not (mode is RuntimeMode.OFF), mode=mode))
    try:
        assert runtime.writer_open is opened
        if mode is RuntimeMode.OFF:
            with pytest.raises(RuntimeError, match="RUNTIME_WRITER_UNAVAILABLE"):
                _ = runtime.writer
            assert runtime.health().status == "CLOSED"
        else:
            assert runtime.health().status == "OPEN"
    finally:
        runtime.close()


# --- Truth table: conversation captured --------------------------------
@pytest.mark.parametrize("mode,captured", [
    (RuntimeMode.OFF, False),
    (RuntimeMode.OBSERVE, True),
    (RuntimeMode.ASSIST, True),
    (RuntimeMode.INJECT, True),
])
def test_truth_table_capture_capability(tmp_path: Path, mode, captured) -> None:
    runtime = ZeroMemRuntime.open(RuntimeConfig(capture_root=tmp_path / "c", enabled=not (mode is RuntimeMode.OFF), mode=mode))
    try:
        assert runtime.capture_enabled is captured
    finally:
        runtime.close()


# --- Truth table: read tool registered ---------------------------------
@pytest.mark.parametrize("mode,read_on", [
    (RuntimeMode.OFF, False),
    (RuntimeMode.OBSERVE, False),
    (RuntimeMode.ASSIST, True),
    (RuntimeMode.INJECT, True),
])
def test_truth_table_read_registered(mode, read_on) -> None:
    assert mode_read_enabled(mode) is read_on


# --- Truth table: injection hook registered -----------------------------
@pytest.mark.parametrize("mode,inject_on", [
    (RuntimeMode.OFF, False),
    (RuntimeMode.OBSERVE, False),
    (RuntimeMode.ASSIST, False),
    (RuntimeMode.INJECT, True),
])
def test_truth_table_injection_registered(mode, inject_on) -> None:
    assert mode_injection_enabled(mode) is inject_on


# --- Truth table: health reports exact mode -----------------------------
@pytest.mark.parametrize("mode", [
    RuntimeMode.OFF,
    RuntimeMode.OBSERVE,
    RuntimeMode.ASSIST,
    RuntimeMode.INJECT,
])
def test_truth_table_health_reports_exact_mode(tmp_path: Path, mode) -> None:
    runtime = ZeroMemRuntime.open(RuntimeConfig(capture_root=tmp_path / "c", enabled=not (mode is RuntimeMode.OFF), mode=mode))
    try:
        assert runtime.health().mode == mode.value
    finally:
        runtime.close()


def test_capability_matrix_exposes_every_cell(tmp_path: Path) -> None:
    for mode in RuntimeMode:
        runtime = ZeroMemRuntime.open(RuntimeConfig(capture_root=tmp_path / f"c-{mode.value}", enabled=mode is not RuntimeMode.OFF, mode=mode))
        try:
            matrix = runtime.capability_matrix()
            assert matrix["writer_open"] is (mode is not RuntimeMode.OFF)
            assert matrix["conversation_captured"] is (mode is not RuntimeMode.OFF)
            assert matrix["read_tool_registered"] is (mode in (RuntimeMode.ASSIST, RuntimeMode.INJECT))
            assert matrix["injection_hook_registered"] is (mode is RuntimeMode.INJECT)
            assert matrix["health_reports_mode"] is True
        finally:
            runtime.close()


# --- Backward migration: enabled=False maps to OFF ---------------------
def test_enabled_false_maps_to_off_mode(tmp_path: Path) -> None:
    config = RuntimeConfig(capture_root=tmp_path / "c", enabled=False)
    assert config.mode is RuntimeMode.OFF
    runtime = ZeroMemRuntime.open(config)
    try:
        assert runtime.writer_open is False
        assert runtime.capture_enabled is False
        assert runtime.health().mode == "off"
    finally:
        runtime.close()


# --- Backward compat: missing mode defaults to ASSIST -------------------
def test_missing_mode_defaults_to_assist(tmp_path: Path) -> None:
    config = RuntimeConfig(capture_root=tmp_path / "c", enabled=True)
    assert config.mode is RuntimeMode.ASSIST
    assert mode_read_enabled(config.mode) is True
    assert mode_injection_enabled(config.mode) is False


# --- Negative: observe must NOT create InjectionAdapter / injection hook
def test_observe_mode_creates_no_injection_adapter(tmp_path: Path) -> None:
    runtime = ZeroMemRuntime.open(RuntimeConfig(capture_root=tmp_path / "c", enabled=True, mode=RuntimeMode.OBSERVE))
    try:
        # The composition layer must not register an injection hook in observe mode.
        assert runtime.injection_enabled is False
        # No InjectionAdapter is constructed by the runtime when mode != inject.
        assert runtime.injection_adapter is None
    finally:
        runtime.close()


def test_off_mode_opens_no_derived_store(tmp_path: Path) -> None:
    runtime = ZeroMemRuntime.open(RuntimeConfig(capture_root=tmp_path / "c", enabled=False, mode=RuntimeMode.OFF))
    try:
        assert runtime.writer_open is False
        assert runtime._derived is None
        assert runtime._projection is None
    finally:
        runtime.close()


def test_runtime_mode_invalid_value_rejected() -> None:
    with pytest.raises(ValueError, match="runtime_mode"):
        RuntimeConfig(capture_root=Path("/tmp/x"), enabled=True, mode="bogus")  # type: ignore[arg-type]
