from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from zero_mem.core import CoreConfig, ZeroMemClient


def test_clients_keep_immutable_distinct_runtime_configuration() -> None:
    first = ZeroMemClient(CoreConfig(enabled=True, project_id="p1", profile_id="r1"))
    second = ZeroMemClient(CoreConfig(enabled=False, project_id="p2", profile_id="r2"))

    assert first.config.project_id == "p1"
    assert second.config.project_id == "p2"
    assert first.enabled is True
    assert second.enabled is False
    with pytest.raises(FrozenInstanceError):
        first.config.enabled = False  # type: ignore[misc]


def test_capture_is_unavailable_without_explicit_writer_and_policy() -> None:
    client = ZeroMemClient(CoreConfig(enabled=True, project_id="p", profile_id="r"))

    result = client.capture({"kind": "observation"})

    assert result.status == "CAPABILITY_UNAVAILABLE"
    assert result.reason_code == "CAPTURE_WRITER_UNCONFIGURED"


def test_core_source_has_no_host_adapter_imports() -> None:
    source = Path("zero_mem/core.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = [
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    ]
    assert not any("hermes" in module or module.startswith("src.integration") for module in imported)


def test_disabled_client_never_calls_writer() -> None:
    calls: list[object] = []

    class Writer:
        def append(self, event: object) -> None:
            calls.append(event)

    client = ZeroMemClient(
        CoreConfig(enabled=False, project_id="p", profile_id="r"),
        writer=Writer(),
        consistency_policy="append-only",
    )

    result = client.capture({"kind": "observation"})

    assert result.status == "CAPABILITY_UNAVAILABLE"
    assert result.reason_code == "ZERO_MEM_DISABLED"
    assert calls == []


def test_enabled_client_requires_explicit_consistency_policy() -> None:
    class Writer:
        def append(self, event: object) -> None:
            pass

    with pytest.raises(ValueError, match="consistency_policy"):
        ZeroMemClient(
            CoreConfig(enabled=True, project_id="p", profile_id="r"),
            writer=Writer(),
        )


def test_enabled_client_writes_through_injected_writer() -> None:
    calls: list[object] = []

    class Writer:
        def append(self, event: object) -> None:
            calls.append(event)

    event = {"kind": "observation"}
    client = ZeroMemClient(
        CoreConfig(enabled=True, project_id="p", profile_id="r"),
        writer=Writer(),
        consistency_policy="append-only",
    )

    result = client.capture(event)

    assert result.status == "CAPTURED"
    assert calls == [event]
