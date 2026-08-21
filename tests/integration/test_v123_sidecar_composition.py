from __future__ import annotations

from pathlib import Path

import zero_mem


def test_sidecar_advertises_and_dispatches_the_same_public_reads(tmp_path: Path) -> None:
    client = zero_mem.open_local_client(
        tmp_path / "runtime",
        project_id="project-r02",
        profile_id="profile-r02",
    )
    with __import__("pytest").warns(DeprecationWarning):
        sidecar = zero_mem.LocalSidecar(client)
    try:
        sidecar.start()
        advertised = sidecar.dispatch({"identity": "profile-r02", "capability": "capabilities"})
        capabilities = advertised["result"]["capabilities"]
        assert {"search", "get_trace", "get_task_state", "get_decisions"}.issubset(capabilities)

        client.observe_tool_call({"event_id": "r02-event", "trace_id": "r02-trace", "result": "sidecar fixture"})
        client.sync()
        direct = client.search({"text": "sidecar fixture", "consistency": "require_current"})
        routed = sidecar.dispatch(
            {
                "identity": "profile-r02",
                "capability": "search",
                "text": "sidecar fixture",
                "consistency": "require_current",
            }
        )
        assert routed["capability"] == "zero_mem.search"
        assert routed["status"] == direct.status
        assert routed["reason_code"] == direct.reason_code
        assert routed["provenance"] == list(direct.provenance)
        assert routed["freshness"] == direct.freshness
        direct_event_ids = [item["value"].event_id for item in direct.items]
        routed_event_ids = [item["value"]["event_id"] for item in routed["items"]]
        assert routed_event_ids == direct_event_ids

        empty_direct = client.search({"text": "no such sidecar fixture", "consistency": "require_current"})
        empty_routed = sidecar.dispatch(
            {
                "identity": "profile-r02",
                "capability": "search",
                "text": "no such sidecar fixture",
                "consistency": "require_current",
            }
        )
        assert empty_direct.status == "EMPTY"
        assert empty_routed["status"] == "EMPTY"
        assert empty_routed["reason_code"] == "READ_EMPTY"
    finally:
        sidecar.stop()
        client.shutdown()
