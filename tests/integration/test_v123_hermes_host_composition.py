from __future__ import annotations

from pathlib import Path

import zero_mem


class HostContext:
    def __init__(self) -> None:
        self.hooks: dict[str, object] = {}
        self.tools: dict[str, object] = {}
        self.toolsets: dict[str, str] = {}
        self.descriptions: dict[str, str] = {}

    def register_hook(self, name: str, callback: object) -> None:
        if name not in self.hooks:
            self.hooks[name] = callback
            return
        previous = self.hooks[name]

        def combined(*args, **kwargs):
            results = (previous(*args, **kwargs), callback(*args, **kwargs))
            return next((result for result in results if result is not None), None)

        self.hooks[name] = combined

    def register_tool(
        self,
        name: str,
        toolset: str,
        schema: dict[str, object],
        handler: object,
        *,
        description: str,
    ) -> None:
        if name in self.tools:
            raise RuntimeError("duplicate_tool")
        self.tools[name] = handler
        self.toolsets[name] = toolset
        self.descriptions[name] = description


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
    assert context.toolsets and all(value == "zero_mem" for value in context.toolsets.values())
    assert context.descriptions and all(value == "Authorized Zero-Mem read surface" for value in context.descriptions.values())

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
    assert response.get("status") == "SUCCESS"
    assert "r03-event" in str(response)

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
