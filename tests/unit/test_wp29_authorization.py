from __future__ import annotations

from src.access.authorized_read import AuthorizedReadService
from src.access.contracts import AccessRequest, READ, ReasonCode
from src.access.grants import AuthorizedReadGrant


class StoreSpy:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def conn(self):
        self.calls += 1
        raise AssertionError("low-level discovery occurred before authorization")

    def get_schema_version(self):
        self.calls += 1
        raise AssertionError("schema access occurred before authorization")


def _denied_request() -> AccessRequest:
    return AccessRequest(
        operation=READ,
        requesting_profile_id="profile-a",
        target_profile_ids=["profile-b"],
        include_global=False,
    )


def test_wp29_denial_precedes_every_read_surface() -> None:
    service = AuthorizedReadService(StoreSpy(), requesting_profile_id="profile-a")
    request = _denied_request()
    calls = (
        lambda: service.query_events(request),
        lambda: service.get_event(request, "event-b"),
        lambda: service.get_trace(request, "trace-b"),
        lambda: service.search_text(request, "secret"),
        lambda: service.m4_charter(request, "project-b"),
        lambda: service.get_related(request, "event-b"),
    )
    for operation in calls:
        result = operation()
        assert result.denied is True
        assert result.reason_code in {
            ReasonCode.DENY_CROSS_PROFILE_READ.value,
            ReasonCode.DENY_UNAUTHORIZED_CROSS_PROFILE_READ.value,
        }


def test_wp29_foreign_subject_and_write_grants_do_not_expand_scope() -> None:
    service = AuthorizedReadService(StoreSpy(), requesting_profile_id="profile-a")
    foreign = AuthorizedReadGrant(
        grant_id="foreign", subject_profile="profile-b", operation=READ,
        target_type="profile", target_id="profile-c",
    )
    write = AuthorizedReadGrant(
        grant_id="write", subject_profile="profile-a", operation="WRITE",
        target_type="profile", target_id="profile-b",
    )
    result = service.query_events(_denied_request(), grants=[foreign, write])
    assert result.denied is True
    assert result.items == []
    assert result.query == {}


def test_wp29_denial_does_not_expose_identifier_or_scope_metadata() -> None:
    service = AuthorizedReadService(StoreSpy(), requesting_profile_id="profile-a")
    result = service.get_event(_denied_request(), "highly-sensitive-event-id")
    assert result.denied is True
    assert result.items == []
    assert result.query == {}
    assert "highly-sensitive-event-id" not in result.reason_code
    assert "profile-b" not in result.reason_code
