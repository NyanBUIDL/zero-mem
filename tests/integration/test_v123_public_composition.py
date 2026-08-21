from __future__ import annotations

from pathlib import Path

import zero_mem


def test_public_factory_real_capture_and_four_reads_without_src_import(tmp_path: Path) -> None:
    client = zero_mem.open_local_client(
        tmp_path / "runtime",
        project_id="project-r01",
        profile_id="profile-r01",
    )
    try:
        assert client.session_start("session-r01") == "SESSION_ACTIVE"
        captured = client.observe_tool_call(
            {
                "event_id": "r01-event-1",
                "trace_id": "r01-trace-1",
                "session_id": "session-r01",
                "tool_name": "fixture",
                "result": "authorized fixture",
            }
        )
        assert captured.status == "CAPTURED"
        assert client.sync() == "SYNCED"

        search = client.search({"text": "authorized fixture", "consistency": "require_current"})
        trace = client.get_trace({"trace_id": "r01-trace-1", "consistency": "require_current"})
        task = client.get_task_state({"project_id": "project-r01", "consistency": "require_current"})
        decisions = client.get_decisions({"project_id": "project-r01", "consistency": "require_current"})

        assert search.status == "READY" and search.items
        assert trace.status == "READY" and trace.items
        assert task.status in {"READY", "EMPTY"}
        assert decisions.status in {"READY", "EMPTY"}
        for result in (search, trace, task, decisions):
            assert result.capability.startswith("zero_mem.")
            assert result.reason_code
            assert result.freshness is not None
    finally:
        client.shutdown()




def test_public_reads_deny_foreign_scope_without_leakage_and_restart(tmp_path: Path) -> None:
    root = tmp_path / "restart-runtime"
    client = zero_mem.open_local_client(root, project_id="project-r01", profile_id="profile-r01")
    client.observe_message({"event_id": "r01-event-2", "trace_id": "r01-trace-2", "text": "private fixture"})
    client.sync()
    denied = client.search({"text": "private fixture", "target_profile_ids": ["foreign-profile"]})
    assert denied.status == "DENIED"
    assert denied.items == ()
    assert denied.provenance == ()
    client.shutdown()

    reopened = zero_mem.open_local_client(root, project_id="project-r01", profile_id="profile-r01")
    try:
        result = reopened.search({"text": "private fixture", "consistency": "require_current"})
        assert result.status == "READY"
        assert result.items
    finally:
        reopened.shutdown()


def test_public_factory_disabled_has_no_runtime_side_effect(tmp_path: Path) -> None:
    client = zero_mem.open_local_client(
        tmp_path / "disabled-runtime",
        project_id="project-r01",
        profile_id="profile-r01",
        enabled=False,
    )
    try:
        result = client.observe_message({"text": "disabled"})
        assert result.status == "CAPABILITY_UNAVAILABLE"
        assert result.reason_code == "ZERO_MEM_DISABLED"
        assert not (tmp_path / "disabled-runtime").exists()
    finally:
        client.shutdown()
