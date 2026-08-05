"""Increment 4.5 isolated non-interference harness.

This module provides a controlled, project-local runtime harness for proving
that enabling the Zero-Mem observer bridge does not alter Hermes behavior. It
reuses the verified Increment 4.4 registration adapter and Increment 4.3
observation adapter.

All persistent state lives under caller-provided temporary roots. The harness
never touches the real home directory, installed Hermes source, or any network
resource. It contains no LLM, retry, dead-letter, or retrieval logic.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .bridge_config import BridgeConfig, VERIFIED_SUPPORTED_HOOKS
from .hermes_registration import RegistrationAdapter
from .capture_adapter import adapt_mapped_event
from .payload_mapping import map_hook_payload


def _append_result(event: dict[str, Any]) -> Any:
    from src.storage.capture_boundary import AppendResult

    content_hash = event.get("sanitized_content_hash", "sha256:test")
    return AppendResult(
        status="appended",
        event_id=event.get("event_id", "evt"),
        sequence=1,
        content_hash=content_hash,
    )


class FakeCaptureStore:
    """In-memory CaptureStore double confined to a temporary root."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.records: list[dict[str, Any]] = []
        self.event_ids: set[str] = set()
        self.content_hashes: set[str] = set()
        # Injection points for failure-isolation tests.
        self.fail_append: bool = False
        self.append_calls: int = 0

    def append(self, event: dict[str, Any]) -> Any:
        self.append_calls += 1
        if self.fail_append:
            from src.storage.capture_boundary import CaptureRejected

            raise CaptureRejected("injected storage failure")
        self.records.append(copy.deepcopy(event))
        event_id = event.get("event_id")
        if event_id:
            self.event_ids.add(event_id)
        content_hash = event.get("sanitized_content_hash")
        if content_hash:
            self.content_hashes.add(content_hash)
        return _append_result(event)

    def contains_event_id(self, event_id: str) -> bool:
        return event_id in self.event_ids

    def contains_content_hash(self, content_hash: str) -> bool:
        return content_hash in self.content_hashes

    def inspect_record(self, event_id: str) -> dict[str, Any] | None:
        for record in self.records:
            if record.get("event_id") == event_id:
                return copy.deepcopy(record)
        return None

    def close(self) -> None:
        return None


class HermesContext:
    """Public-style plugin context accepting ``register_hook``."""

    def __init__(self) -> None:
        self.callbacks: dict[str, Callable[..., Any]] = {}

    def register_hook(self, hook: str, callback: Callable[..., Any]) -> None:
        self.callbacks[hook] = callback


@dataclass
class CapturedOutcome:
    """Bridge-owned outputs only (permitted differences)."""

    jsonl_records: list[dict[str, Any]] = field(default_factory=list)
    metrics_counts: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    registered_hooks: tuple[str, ...] = ()


class NonInterferenceHarness:
    """Runs identical synthetic callbacks with bridge disabled and enabled."""

    def __init__(
        self,
        *,
        capture_root: Path,
        hermes_home: Path,
        project_id: str,
        profile_id: str,
        enabled: bool = False,
    ) -> None:
        self.capture_root = Path(capture_root)
        self.hermes_home = Path(hermes_home)
        self.project_id = project_id
        self.profile_id = profile_id
        self.enabled = enabled
        self.config = BridgeConfig(
            enabled=enabled,
            project_id=project_id,
            profile_id=profile_id,
            capture_root=self.capture_root,
            hermes_home=self.hermes_home,
            use_environment_identity=False,
        )
        self.store = FakeCaptureStore(self.capture_root / "store")
        self.context = HermesContext()
        self.adapter = RegistrationAdapter(self.config, store=self.store)
        self.registered = self.adapter.register(self.context)

    def invoke(self, hook: str, *args: Any, **kwargs: Any) -> Any:
        callback = self.context.callbacks.get(hook)
        if callback is None:
            raise AssertionError(f"hook not registered: {hook}")
        return callback(*args, **kwargs)

    def outcome(self) -> CapturedOutcome:
        outcome = CapturedOutcome()
        outcome.jsonl_records = [copy.deepcopy(r) for r in self.store.records]
        outcome.metrics_counts = self.adapter.metrics.to_dict()["counts"]
        if self.adapter.last_diagnostic is not None:
            outcome.diagnostics.append(self.adapter.last_diagnostic.code)
        outcome.registered_hooks = self.registered
        return outcome


def synthetic_payloads() -> dict[str, dict[str, Any]]:
    """Identical synthetic Hermes inputs per supported hook.

    Nested mutable structures are included so immutability tests can compare
    deep copies before and after callback invocation.
    """
    return {
        "on_session_start": {
            "session_id": "sess-1",
            "profile_id": "profile-test",
            "args": {"mode": "chat", "model": "tencent/hy3:free"},
        },
        "on_session_end": {
            "session_id": "sess-1",
            "args": {"reason": "completed"},
        },
        "on_session_finalize": {
            "session_id": "sess-1",
            "args": {"summary": "done"},
        },
        "pre_tool_call": {
            "session_id": "sess-1",
            "tool_name": "shell_exec",
            "args": {"command": "ls", "flags": ["-la"]},
            "password": "SYNTHETIC_SECRET_VALUE",
        },
        "post_tool_call": {
            "session_id": "sess-1",
            "tool_name": "shell_exec",
            "args": {"command": "ls"},
            "result": {"exit_code": 0, "stdout": ["file_a", "file_b"]},
            "api_key": "SYNTHETIC_SECRET_VALUE",
        },
        "kanban_task_claimed": {
            "session_id": "sess-1",
            "board": "main",
            "assignee": "agent",
            "run_id": "run-1",
            "profile_name": "default",
            "summary": "start",
        },
        "kanban_task_completed": {
            "session_id": "sess-1",
            "board": "main",
            "assignee": "agent",
            "run_id": "run-1",
            "summary": "done",
            "reason": "success",
            "lifecycle_status": "completed",
        },
        "kanban_task_blocked": {
            "session_id": "sess-1",
            "board": "main",
            "assignee": "agent",
            "run_id": "run-1",
            "summary": "stuck",
            "reason": "blocked",
            "lifecycle_status": "blocked",
        },
    }


__all__ = [
    "CapturedOutcome",
    "FakeCaptureStore",
    "HermesContext",
    "NonInterferenceHarness",
    "VERIFIED_SUPPORTED_HOOKS",
    "synthetic_payloads",
]
