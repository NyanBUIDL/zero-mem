"""DEF-063 (project part; profile grants deliberately unchanged, see T9 closure) - grants apply only to the scopes the request names."""
from __future__ import annotations

from src.access.contracts import AccessRequest
from src.access.grants import AuthorizedReadGrant, compose_effective_scope


def _g(ttype, target, subject="claude-code"):
    return AuthorizedReadGrant(
        grant_id=f"g-{ttype}-{target}", subject_profile=subject, operation="READ",
        target_type=ttype, target_id=target)


def _req(**kw):
    return AccessRequest(operation="READ", requesting_profile_id="claude-code",
                         resource_type="corpus_unit", **kw)


def _profiles(eff):
    out = set(eff.base.allowed_profile_ids)
    for s in eff.grant_scopes:
        out |= set(s.allowed_profile_ids)
    return out


def _projects(eff):
    out = set(eff.base.allowed_project_ids)
    for s in eff.grant_scopes:
        out |= set(s.allowed_project_ids)
    return out


def test_project_grant_not_applied_to_space_only_request():
    eff = compose_effective_scope(_req(knowledge_space_ids=["ks-shared"]),
                                  [_g("project", "P")])
    assert "P" not in _projects(eff)
    assert eff.grant_scopes == []


def test_only_requested_project_grant_survives():
    eff = compose_effective_scope(
        _req(target_profile_ids=["claude-code"], project_ids=["P"]),
        [_g("project", "P"), _g("project", "Q")])
    assert eff.allow
    assert [s.allowed_project_ids for s in eff.grant_scopes] == [["P"]]


def test_requested_ungranted_project_not_replaced_by_granted_one():
    eff = compose_effective_scope(
        _req(target_profile_ids=["claude-code"], project_ids=["Q"]),
        [_g("project", "P")])
    # base policy decides (own profile); the P grant must not ride along
    assert eff.grant_scopes == []
    assert "P" not in _projects(eff)
