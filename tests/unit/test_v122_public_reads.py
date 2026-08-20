from __future__ import annotations

from src.access.authorized_read import AuthorizedReadService
from src.integration.public_read_adapter import AuthorizedPublicReadAdapter


def test_public_read_authorizes_before_freshness_discovery() -> None:
    service = AuthorizedReadService(None, "profile-a")
    freshness_calls: list[str] = []
    wait_calls: list[float] = []
    adapter = AuthorizedPublicReadAdapter(
        service,
        requesting_profile_id="profile-a",
        freshness_provider=lambda: freshness_calls.append("freshness") or {"status": "DERIVED_PENDING"},
        wait_provider=lambda timeout: wait_calls.append(timeout),
    )
    result = adapter.search({"text": "secret", "target_profile_ids": ["profile-b"], "consistency": "bounded_wait"})
    assert result.status == "DENIED"
    assert freshness_calls == []
    assert wait_calls == []


def test_public_read_rejects_malformed_scope_types() -> None:
    service = AuthorizedReadService(None, "profile-a")
    adapter = AuthorizedPublicReadAdapter(service, requesting_profile_id="profile-a")
    for request in (
        {"target_profile_ids": "profile-b"},
        {"project_ids": ["p1", 2]},
        {"include_global": "false"},
        {"isolated_mode": "false"},
    ):
        result = adapter.search(request)
        assert result.status == "INVALID"
        assert result.reason_code == "INVALID_REQUEST"


def test_public_read_rejects_non_mapping_requests() -> None:
    service = AuthorizedReadService(None, "profile-a")
    adapter = AuthorizedPublicReadAdapter(service, requesting_profile_id="profile-a")
    for request in ("x", 1, [], ["x"]):
        result = adapter.search(request)
        assert result.status == "INVALID"
        assert result.reason_code == "INVALID_REQUEST"


def test_bounded_wait_rejects_nonfinite_deadlines() -> None:
    service = AuthorizedReadService(None, "profile-a")
    calls: list[float] = []
    adapter = AuthorizedPublicReadAdapter(
        service,
        requesting_profile_id="profile-a",
        freshness_provider=lambda: {"status": "DERIVED_PENDING"},
        wait_provider=lambda timeout: calls.append(timeout),
    )
    for deadline in (float("inf"), float("-inf"), float("nan")):
        result = adapter.search({"text": "x", "consistency": "bounded_wait", "deadline": deadline})
        assert result.status == "STALE"
        assert result.reason_code == "INVALID_DEADLINE"
    assert calls == []


def test_bounded_wait_uses_finite_deadline_once() -> None:
    service = AuthorizedReadService(None, "profile-a")
    calls: list[float] = []
    adapter = AuthorizedPublicReadAdapter(
        service,
        requesting_profile_id="profile-a",
        freshness_provider=lambda: {"status": "DERIVED_PENDING"},
        wait_provider=lambda timeout: calls.append(timeout),
    )
    result = adapter.search({"text": "x", "consistency": "bounded_wait", "deadline": 0.25})
    assert result.status == "STALE"
    assert calls == [0.25]
