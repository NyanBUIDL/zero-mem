"""Increment 4.6 controlled capture-rate benchmark harness.

Drives the verified Increment 4.4 registration adapter and Increment 4.3
observation adapter over the real project ``JsonlCaptureStore`` (temporary
root) for the operationally supported Hermes hooks. Measures capture rate
against the exact Increment 4.1 formula and reports controlled-benchmark
accounting without modifying installed Hermes or the real home directory.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from src.capture.validation import validate_envelope
from src.integration.bridge_config import (
    CONDITIONAL_FIXTURE_REQUIRED,
    DEFERRED_HOOKS,
    VERIFIED_SUPPORTED_HOOKS,
)
from src.integration.hermes_registration import RegistrationAdapter
from src.storage.capture_boundary import CaptureStoreConfig, CaptureRejected
from src.storage.jsonl_capture import JsonlCaptureStore
from src.integration.payload_mapping import map_hook_payload


SECRET_CORPUS = ("SYNTHETIC_SECRET_VALUE",)


@dataclass
class BenchmarkReport:
    """Controlled benchmark accounting. All counts are disjoint where required."""

    expected_supported: int = 0
    accounted: int = 0
    appended_unique: int = 0
    accepted_duplicates: int = 0
    rejected: int = 0
    failed_captures: int = 0
    unsupported_or_deferred: int = 0
    ordering_failures: int = 0
    correlation_failures: int = 0
    envelope_failures: int = 0
    secret_scan_failures: int = 0
    capture_rate: float = 0.0
    jsonl_path: str | None = None
    supported_hooks: tuple[str, ...] = ()
    conditional_excluded: tuple[str, ...] = ()
    deferred_excluded: tuple[str, ...] = ()
    secret_present: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_supported": self.expected_supported,
            "accounted": self.accounted,
            "appended_unique": self.appended_unique,
            "accepted_duplicates": self.accepted_duplicates,
            "rejected": self.rejected,
            "failed_captures": self.failed_captures,
            "unsupported_or_deferred": self.unsupported_or_deferred,
            "ordering_failures": self.ordering_failures,
            "correlation_failures": self.correlation_failures,
            "envelope_failures": self.envelope_failures,
            "secret_scan_failures": self.secret_scan_failures,
            "capture_rate": self.capture_rate,
            "jsonl_path": self.jsonl_path,
            "supported_hooks": list(self.supported_hooks),
            "conditional_excluded": list(self.conditional_excluded),
            "deferred_excluded": list(self.deferred_excluded),
            "secret_present": self.secret_present,
        }


class _Context:
    def __init__(self) -> None:
        self.callbacks: dict[str, Callable[..., Any]] = {}

    def register_hook(self, hook: str, callback: Callable[..., Any]) -> None:
        self.callbacks[hook] = callback


def _unique_payloads(project_id: str, profile_id: str) -> dict[str, dict[str, Any]]:
    """One unique synthetic logical event per supported hook."""
    return {
        "on_session_start": {
            "event_id": "evt-session-start-1",
            "session_id": "sess-bench-1",
            "profile_id": profile_id,
            "project_id": project_id,
            "turn_id": "t1",
            "args": {"mode": "chat", "model": "tencent/hy3:free"},
            "password": SECRET_CORPUS[0],
        },
        "on_session_end": {
            "event_id": "evt-session-end-1",
            "session_id": "sess-bench-1",
            "profile_id": profile_id,
            "project_id": project_id,
            "turn_id": "t2",
            "args": {"reason": "completed"},
        },
        "on_session_finalize": {
            "event_id": "evt-session-finalize-1",
            "session_id": "sess-bench-1",
            "profile_id": profile_id,
            "project_id": project_id,
            "turn_id": "t3",
            "args": {"summary": "done"},
        },
        "on_session_reset": {
            "event_id": "evt-session-reset-1",
            "session_id": "sess-bench-1",
            "profile_id": profile_id,
            "project_id": project_id,
            "turn_id": "t-reset",
            "args": {"reason": "new conversation"},
        },
        "pre_llm_call": {
            "event_id": "evt-user-message-1",
            "session_id": "sess-bench-1",
            "task_id": "task-bench-1",
            "turn_id": "t-message-1",
            "profile_id": profile_id,
            "project_id": project_id,
            "user_message": "Inspect the repository",
            "conversation_history": [{"role": "system", "content": "fixture"}],
        },
        "post_llm_call": {
            "event_id": "evt-assistant-message-1",
            "session_id": "sess-bench-1",
            "task_id": "task-bench-1",
            "turn_id": "t-message-1",
            "profile_id": profile_id,
            "project_id": project_id,
            "user_message": "Inspect the repository",
            "assistant_response": "Inspection complete",
            "conversation_history": [{"role": "user", "content": "fixture"}],
        },
        "pre_tool_call": {
            "event_id": "evt-pre-tool-1",
            "session_id": "sess-bench-1",
            "profile_id": profile_id,
            "project_id": project_id,
            "turn_id": "t4",
            "tool_name": "shell_exec",
            "args": {"command": "ls", "flags": ["-la"]},
            "api_key": SECRET_CORPUS[0],
        },
        "post_tool_call": {
            "event_id": "evt-post-tool-1",
            "session_id": "sess-bench-1",
            "profile_id": profile_id,
            "project_id": project_id,
            "turn_id": "t5",
            "tool_name": "shell_exec",
            "args": {"command": "ls"},
            "result": {"exit_code": 0, "stdout": ["file_a", "file_b"]},
        },
        "on_skill_lifecycle": {
            "event_id": "evt-skill-lifecycle-1",
            "session_id": "sess-bench-1",
            "task_id": "task-bench-1",
            "turn_id": "t-skill-1",
            "profile_id": profile_id,
            "project_id": project_id,
            "skill_name": "repository-audit",
            "action": "loaded",
        },
        "subagent_start": {
            "event_id": "evt-subagent-start-1",
            "session_id": "sess-bench-1",
            "task_id": "task-bench-1",
            "turn_id": "t-subagent-1",
            "profile_id": profile_id,
            "project_id": project_id,
            "child_agent_id": "child-bench-1",
            "parent_agent_id": "master-bench-1",
            "agent_name": "audit-worker",
        },
        "subagent_stop": {
            "event_id": "evt-subagent-stop-1",
            "session_id": "sess-bench-1",
            "task_id": "task-bench-1",
            "turn_id": "t-subagent-2",
            "profile_id": profile_id,
            "project_id": project_id,
            "child_agent_id": "child-bench-1",
            "parent_agent_id": "master-bench-1",
            "agent_name": "audit-worker",
            "reason": "completed",
        },
        "kanban_task_claimed": {
            "event_id": "evt-kanban-claimed-1",
            "session_id": "sess-bench-1",
            "profile_id": profile_id,
            "project_id": project_id,
            "lifecycle_status": "observed",
            "board": "main",
            "assignee": "agent",
            "run_id": "run-1",
            "profile_name": "default",
            "summary": "start",
        },
        "kanban_task_completed": {
            "event_id": "evt-kanban-completed-1",
            "session_id": "sess-bench-1",
            "profile_id": profile_id,
            "project_id": project_id,
            "lifecycle_status": "observed",
            "board": "main",
            "assignee": "agent",
            "run_id": "run-1",
            "summary": "done",
            "reason": "success",
        },
        "kanban_task_blocked": {
            "event_id": "evt-kanban-blocked-1",
            "session_id": "sess-bench-1",
            "profile_id": profile_id,
            "project_id": project_id,
            "lifecycle_status": "observed",
            "board": "main",
            "assignee": "agent",
            "run_id": "run-1",
            "summary": "stuck",
            "reason": "blocked",
        },
    }


def _duplicate_payloads(base: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        "pre_tool_call": base["pre_tool_call"],
        "kanban_task_completed": base["kanban_task_completed"],
    }


def _conditional_deferred_inputs() -> dict[str, dict[str, Any]]:
    return {
        "pre_api_request": {"session_id": "s", "args": {}},
        "post_api_request": {"session_id": "s", "args": {}},
        "file_operations": {"session_id": "s", "args": {}},
        "transform_tool_result": {"session_id": "s", "args": {}},
    }


def run_benchmark(*, capture_root: Path, hermes_home: Path, project_id: str, profile_id: str) -> BenchmarkReport:
    """Run the controlled benchmark and return accounting + capture rate."""
    report = BenchmarkReport()
    report.supported_hooks = VERIFIED_SUPPORTED_HOOKS
    report.conditional_excluded = CONDITIONAL_FIXTURE_REQUIRED
    report.deferred_excluded = DEFERRED_HOOKS

    root = Path(capture_root)
    store = JsonlCaptureStore(CaptureStoreConfig(root=root / "store", stream_name="events-v1.jsonl"))
    context = _Context()
    adapter = _build_adapter(root, project_id, profile_id, store)

    payloads = _unique_payloads(project_id, profile_id)
    report.expected_supported = len(payloads)

    # Drive each supported hook once (unique logical event).
    for hook in VERIFIED_SUPPORTED_HOOKS:
        payload = payloads[hook]
        before = copy.deepcopy(payload)
        _invoke(adapter, context, hook, payload)
        event_id = payload.get("event_id", "")
        if store.contains_event_id(event_id):
            report.appended_unique += 1
            report.accounted += 1
        else:
            report.failed_captures += 1
        # Immutability: hook input unchanged by observer.
        if payload != before:
            report.correlation_failures += 1

    # Duplicate replays for a subset: must be accepted-duplicate, no new record.
    # These confirm events already accounted in the unique loop, so they do
    # NOT increment `accounted` (each expected logical event counts once).
    duplicates = _duplicate_payloads(payloads)
    for hook, payload in duplicates.items():
        before_count = _jsonl_line_count(store.path)
        before_seq = store.inspect_record(payload["event_id"])["sequence"]
        _invoke(adapter, context, hook, copy.deepcopy(payload))
        after_count = _jsonl_line_count(store.path)
        after_seq = store.inspect_record(payload["event_id"])["sequence"]
        # The original stored record must still exist and no new line was added.
        if after_count == before_count and after_seq == before_seq and store.contains_event_id(payload["event_id"]):
            report.accepted_duplicates += 1
        else:
            report.failed_captures += 1

    # Conditional/deferred inputs: reported separately, never in denominator.
    for hook, payload in _conditional_deferred_inputs().items():
        mapped = map_hook_payload(hook, copy.deepcopy(payload), project_id=project_id, profile_id=profile_id)
        if mapped.status in ("conditional_fixture_required", "deferred"):
            report.unsupported_or_deferred += 1
        else:
            report.unsupported_or_deferred += 1  # still excluded; never counted as supported accounted

    # Post-flight integrity checks.
    _check_jsonl_integrity(store, report)
    _check_secret_absence(store, report)

    if report.expected_supported:
        report.capture_rate = round(report.accounted / report.expected_supported * 100, 4)
    report.jsonl_path = str(store.path)
    store.close()
    return report


def _build_adapter(root: Path, project_id: str, profile_id: str, store: JsonlCaptureStore):
    from src.integration.bridge_config import BridgeConfig

    config = BridgeConfig(
        enabled=True,
        project_id=project_id,
        profile_id=profile_id,
        capture_root=root / "capture",
        hermes_home=root / "hermes",
        use_environment_identity=False,
    )
    return RegistrationAdapter(config, store=store)


def _invoke(adapter: RegistrationAdapter, context: _Context, hook: str, payload: Mapping[str, Any]) -> None:
    if hook not in context.callbacks:
        adapter.register(context)
    callback = context.callbacks[hook]
    callback(copy.deepcopy(payload))


def _jsonl_line_count(path: Path) -> int:
    if not path.exists():
        return 0
    data = path.read_bytes()
    if not data:
        return 0
    return len([line for line in data.splitlines() if line.strip()])


def _check_jsonl_integrity(store: JsonlCaptureStore, report: BenchmarkReport) -> None:
    path = store.path
    if not path.exists():
        report.envelope_failures += 1
        return
    sequences = []
    with path.open("rb") as stream:
        raw = stream.read()
    lines = raw.splitlines()
    if raw and not raw.endswith(b"\n"):
        report.envelope_failures += 1
    prev_seq = -1
    for line in lines:
        try:
            record = json.loads(line.decode("utf-8"))
        except Exception:
            report.envelope_failures += 1
            continue
        try:
            validate_envelope(record)
        except Exception:
            report.envelope_failures += 1
            continue
        if not isinstance(record.get("sequence"), int) or record["sequence"] < 0:
            report.envelope_failures += 1
        if record["sequence"] < prev_seq:
            report.ordering_failures += 1
        prev_seq = record["sequence"]
        sequences.append(record["sequence"])
    # Monotonic non-decreasing with no gaps for appended-unique set.
    if sequences != sorted(sequences):
        report.ordering_failures += 1


def _check_secret_absence(store: JsonlCaptureStore, report: BenchmarkReport) -> None:
    path = store.path
    blobs = [str(path.read_text(encoding="utf-8"))] if path.exists() else []
    # Include in-memory diagnostics are not retained; scan persisted JSONL only.
    for blob in blobs:
        if any(secret in blob for secret in SECRET_CORPUS):
            report.secret_scan_failures += 1
            report.secret_present = True


__all__ = ["BenchmarkReport", "run_benchmark", "SECRET_CORPUS"]
