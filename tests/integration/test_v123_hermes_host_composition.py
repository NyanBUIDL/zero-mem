from __future__ import annotations

import os
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


def _open_boundary(tmp_path: Path, *, mode: str | None = None):
    if mode is not None:
        os.environ["ZERO_MEM_MODE"] = mode
    capture_root = tmp_path / "capture"
    store_path = capture_root / "derived" / "events.sqlite"
    return zero_mem.open_hermes_boundary(
        project_id="project-r03",
        profile_id="profile-r03",
        capture_root=capture_root,
        store_path=store_path,
    )


def test_host_factory_default_observes_only(tmp_path: Path) -> None:
    # R124-01 compatibility change: the DEFAULT setup (no ZERO_MEM_MODE, canonical
    # config present) now resolves to OBSERVE — capture hooks only, NO read tools,
    # NO injection hook. The prior `assist` default over-elevated the boundary by
    # registering read tools without an explicit operator opt-in. See
    # docs/v1.2.4/COMPATIBILITY.md (R124-01 default-mode change).
    boundary = _open_boundary(tmp_path)
    context = HostContext()
    result = boundary.register(context)
    assert result["hooks"]
    # OBSERVE: no read tools, no injection hook, no InjectionAdapter.
    assert result["tools"] == ()
    assert result["injection"] == ()
    assert boundary._injection_adapter is None
    # Capture still works (canonical JSONL is written).
    context.hooks["on_session_start"](
        {"event_id": "r03-d0", "trace_id": "r03-t0", "session_id": "r03", "text": "observe only"}
    )
    assert (tmp_path / "capture" / "canonical" / "events-v1.jsonl").is_file()
    boundary.shutdown()


def test_public_host_factory_assist_register_capture_projection_read_restart_shutdown(tmp_path: Path) -> None:
    # V124-02: explicit ASSIST mode — capture + authorized read tools, NO injection hook.
    # (The original default-mode E2E read test now runs under explicit assist because the
    # default mode changed to observe; see docs/v1.2.4/COMPATIBILITY.md.)
    os.environ["ZERO_MEM_MODE"] = "assist"
    try:
        boundary = _open_boundary(tmp_path)
        context = HostContext()
        first = boundary.register(context)
        assert first["hooks"]
        assert first["tools"]
        # assist mode must NOT register a controlled injection hook.
        assert first["injection"] == ()
        assert "on_session_start" in context.hooks
        assert context.toolsets and all(value == "zero_mem" for value in context.toolsets.values())
        assert context.descriptions and all(value == "Authorized Zero-Mem read surface" for value in context.descriptions.values())

        context.hooks["on_session_start"](
            {"event_id": "r03-event", "trace_id": "r03-trace", "session_id": "r03", "text": "host fixture"}
        )
        assert (tmp_path / "capture" / "canonical" / "events-v1.jsonl").is_file()
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
        assert len((tmp_path / "capture" / "canonical" / "events-v1.jsonl").read_bytes().splitlines()) == 2
    finally:
        os.environ.pop("ZERO_MEM_MODE", None)


def test_host_factory_inject_mode_registers_controlled_injection_hook(tmp_path: Path) -> None:
    # V124-02: explicit inject mode registers the controlled pre_llm_call hook.
    os.environ["ZERO_MEM_MODE"] = "inject"
    try:
        boundary = _open_boundary(tmp_path)
        context = HostContext()
        result = boundary.register(context)
        assert result["hooks"]
        assert result["tools"]
        assert result["injection"] == ("pre_llm_call",)
        assert boundary._injection_adapter is not None
    finally:
        os.environ.pop("ZERO_MEM_MODE", None)


def test_host_factory_observe_mode_registers_no_read_and_no_injection(tmp_path: Path) -> None:
    # V124-02: observe mode captures only; no read tools, no injection hook.
    os.environ["ZERO_MEM_MODE"] = "observe"
    try:
        boundary = _open_boundary(tmp_path)
        context = HostContext()
        result = boundary.register(context)
        assert result["hooks"]
        assert result["tools"] == ()
        assert result["injection"] == ()
        assert boundary._injection_adapter is None
    finally:
        os.environ.pop("ZERO_MEM_MODE", None)


def test_host_factory_off_mode_no_side_effects(tmp_path: Path) -> None:
    # R124-01: OFF mode registers nothing and creates no file/directory/database.
    os.environ["ZERO_MEM_MODE"] = "off"
    try:
        boundary = _open_boundary(tmp_path)
        context = HostContext()
        result = boundary.register(context)
        assert result["hooks"] == ()
        assert result["tools"] == ()
        assert result["injection"] == ()
        assert boundary._capture_adapter is None
        # No canonical JSONL, no derived store, no projection worker.
        assert not (tmp_path / "capture" / "canonical" / "events-v1.jsonl").exists()
        assert not (tmp_path / "capture" / "derived" / "events.sqlite").exists()
        # Invoking a host callback must not create anything either.
        if "on_session_start" in context.hooks:
            context.hooks["on_session_start"](
                {"event_id": "r03-off", "trace_id": "r03-off-t", "session_id": "r03", "text": "x"}
            )
        assert not (tmp_path / "capture").exists()
    finally:
        os.environ.pop("ZERO_MEM_MODE", None)


def test_host_factory_invalid_mode_fails_closed_without_side_effect(tmp_path: Path) -> None:
    # R124-01: an invalid ZERO_MEM_MODE fails closed to OFF with no side effects.
    os.environ["ZERO_MEM_MODE"] = "bogus-mode"
    try:
        boundary = _open_boundary(tmp_path)
        context = HostContext()
        result = boundary.register(context)
        assert result["hooks"] == ()
        assert result["tools"] == ()
        assert result["injection"] == ()
        assert not (tmp_path / "capture").exists()
    finally:
        os.environ.pop("ZERO_MEM_MODE", None)
