from __future__ import annotations

from pathlib import Path

import zero_mem


class HostContext:
    def __init__(self) -> None:
        self.hooks: dict[str, object] = {}
        self.tools: dict[str, object] = {}

    def register_hook(self, name: str, callback: object) -> None:
        self.hooks[name] = callback

    def register_tool(self, name: str, *args: object, **kwargs: object) -> None:
        handler = args[2] if len(args) >= 3 else args[1]
        self.tools[name] = handler


def test_public_host_factory_register_capture_projection_read_restart_shutdown(tmp_path: Path) -> None:
    capture_root = tmp_path / "capture"
    store_path = capture_root / "derived" / "events.sqlite"
    boundary = zero_mem.open_hermes_boundary(
        project_id="project-r03",
        profile_id="profile-r03",
        capture_root=capture_root,
        store_path=store_path,
    )
    context = HostContext()
    first = boundary.register(context)
    assert first["hooks"]
    assert first["tools"]
    assert first["injection"] == ("pre_llm_call",)
    assert "on_session_start" in context.hooks

    context.hooks["on_session_start"](
        {"event_id": "r03-event", "trace_id": "r03-trace", "session_id": "r03", "text": "host fixture"}
    )
    assert capture_root.joinpath("canonical/events-v1.jsonl").is_file()
    assert boundary._capture_adapter.runtime.flush_projection(timeout=5.0).value == "DERIVED_CURRENT"
    assert "memory_search" in context.tools
    response = context.tools["memory_search"](
        {"requesting_profile_id": "profile-r03", "search_text": "host fixture"}
    )
    assert isinstance(response, dict)
    assert response.get("status") in {"SUCCESS", "EMPTY", "POLICY_DENIED", "CAPABILITY_UNAVAILABLE"}

    hook_count = len(context.hooks)
    tool_count = len(context.tools)
    boundary.shutdown()
    restarted = boundary.register(context)
    assert restarted == first
    assert len(context.hooks) == hook_count
    assert len(context.tools) == tool_count
    context.hooks["on_session_start"](
        {"event_id": "r03-event-2", "trace_id": "r03-trace-2", "session_id": "r03", "text": "after restart"}
    )
    boundary.shutdown()
    assert len(capture_root.joinpath("canonical/events-v1.jsonl").read_bytes().splitlines()) == 2
