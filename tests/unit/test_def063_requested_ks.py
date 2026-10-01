"""DEF-063 - a requested knowledge space narrows the grants; it never widens them.

Reproduces the design-doc section 3 matrix through the real MCP path
(``tools/call corpus_search``) and then the DEF-063 quirk: a request for an
unknown / ungranted knowledge space used to return every granted space because
the MCP handler resolves ALL of the caller's READ grants and
``compose_effective_scope`` added a grant scope for each of them regardless of
what the request named (``grants.py`` base_scope/grant_scopes loop).

Rules pinned here:
  * grants apply only to the dimension values the request explicitly names;
  * an unknown or ungranted requested space returns only what the caller is
    entitled to anyway (own rows in that space, all-NULL rows) - never another
    granted space;
  * an unrequested granted space never rides along with a named one;
  * authorization still fails closed (cross-profile, isolation, unbound).
"""
from __future__ import annotations

import pytest

from src.access.contracts import AccessRequest
from src.access.grants import AuthorizedReadGrant, compose_effective_scope
from tests.unit.t6a_mcp_helpers import (
    build_matrix_store, call_tool, configure_inprocess, envelope_of, markers,
)


@pytest.fixture()
def mcp(tmp_path):
    db = build_matrix_store(tmp_path)
    server = configure_inprocess(db)
    yield server


def _search(server, profile, **extra):
    args = {"search_text": "zebra", "requesting_profile_id": profile, "limit": 50}
    args.update(extra)
    return envelope_of(call_tool(server, "corpus_search", args))


# --------------------------------------------------------------------------
# Section 3 matrix (guards: these already held before the fix)
# --------------------------------------------------------------------------
class TestSection3Matrix:
    def test_implicit_sees_own_rows_in_any_space_plus_global(self, mcp):
        env = _search(mcp, "claude-code")
        # A (own, ks-shared), C (own private), H (own, ks-other), E (all-NULL);
        # the ks-shared GRANT is not applied to an implicit request.
        assert markers(env["results"]) == ["A", "C", "E", "H"]

    def test_explicit_shared_space_sees_all_profiles_rows_not_private(self, mcp):
        env = _search(mcp, "claude-code", knowledge_space_ids=["ks-shared"])
        assert markers(env["results"]) == ["A", "B", "E", "F"]

    def test_ungranted_caller_naming_shared_space_sees_only_global(self, mcp):
        env = _search(mcp, "hermes", knowledge_space_ids=["ks-shared"])
        assert markers(env["results"]) == ["E"]

    def test_cross_profile_target_without_grant_is_denied(self, mcp):
        env = _search(mcp, "claude-code", target_profile_ids=["codex"])
        assert env["status"] == "POLICY_DENIED"
        assert env.get("results", []) == []

    def test_isolated_mode_with_nothing_explicit_is_denied(self, mcp):
        env = _search(mcp, "claude-code", isolated_mode=True)
        assert env["status"] == "POLICY_DENIED"

    def test_include_global_false_hides_all_null_rows(self, mcp):
        env = _search(mcp, "claude-code", include_global=False,
                      knowledge_space_ids=["ks-shared"])
        assert "E" not in markers(env["results"])
        assert markers(env["results"]) == ["A", "B", "F"]

    def test_unbound_caller_naming_a_space_is_denied(self, mcp):
        args = {"search_text": "zebra", "knowledge_space_ids": ["ks-shared"]}
        env = envelope_of(call_tool(mcp, "corpus_search", args))
        assert env["status"] == "POLICY_DENIED"


# --------------------------------------------------------------------------
# DEF-063 quirk: requested space is never used to narrow the grants
# --------------------------------------------------------------------------
class TestRequestedSpaceNarrowsGrants:
    def test_unknown_space_does_not_return_other_granted_spaces(self, mcp):
        env = _search(mcp, "claude-code", knowledge_space_ids=["ks-does-not-exist"])
        got = markers(env.get("results", []))
        assert not ({"A", "B", "F"} & set(got)), (
            f"unknown space returned granted ks-shared rows: {got}")
        assert got == ["E"]

    def test_ungranted_real_space_is_not_widened_by_other_grants(self, mcp):
        # ks-hermes-only holds unit I; claude-code has no grant there.
        env = _search(mcp, "claude-code", knowledge_space_ids=["ks-hermes-only"])
        got = markers(env.get("results", []))
        assert "I" not in got
        assert not ({"A", "B", "F"} & set(got))

    def test_requesting_two_spaces_one_unknown_returns_only_the_granted_one(self, mcp):
        env = _search(mcp, "claude-code",
                      knowledge_space_ids=["ks-shared", "ks-does-not-exist"])
        assert markers(env["results"]) == ["A", "B", "E", "F"]

    def test_unrequested_granted_space_does_not_ride_along(self, tmp_path):
        db = build_matrix_store(tmp_path, grants=[
            ("g1", "claude-code", "ks-shared"), ("g2", "claude-code", "ks-other")])
        server = configure_inprocess(db)
        env = _search(server, "claude-code", knowledge_space_ids=["ks-shared"])
        got = markers(env["results"])
        # G (codex/ks-other) and H (own/ks-other) belong to the unrequested space.
        assert got == ["A", "B", "E", "F"], got

    def test_each_granted_space_is_still_reachable_by_naming_it(self, tmp_path):
        db = build_matrix_store(tmp_path, grants=[
            ("g1", "claude-code", "ks-shared"), ("g2", "claude-code", "ks-other")])
        server = configure_inprocess(db)
        other = _search(server, "claude-code", knowledge_space_ids=["ks-other"])
        assert markers(other["results"]) == ["E", "G", "H"]
        both = _search(server, "claude-code",
                       knowledge_space_ids=["ks-shared", "ks-other"])
        assert markers(both["results"]) == ["A", "B", "E", "F", "G", "H"]

    def test_project_request_does_not_pull_in_unrequested_space_grants(self, mcp):
        env = _search(mcp, "claude-code", project_ids=["no-such-project"])
        # A project the caller cannot show ownership of fails closed (unchanged);
        # what must never happen is a grant-space leak instead of the denial.
        got = markers(env.get("results", []))
        assert not ({"B", "F"} & set(got)), got


# --------------------------------------------------------------------------
# Unit level: the composed scope itself
# --------------------------------------------------------------------------
def _ks_grant(space: str, subject: str = "claude-code") -> AuthorizedReadGrant:
    return AuthorizedReadGrant(
        grant_id=f"g-{space}", subject_profile=subject, operation="READ",
        target_type="knowledge_space", target_id=space)


def _spaces_of(scope) -> set:
    out = set(scope.base.allowed_knowledge_space_ids)
    for g in scope.grant_scopes:
        out |= set(g.allowed_knowledge_space_ids)
    return out


class TestComposeEffectiveScope:
    def _req(self, spaces):
        return AccessRequest(operation="READ", requesting_profile_id="claude-code",
                             knowledge_space_ids=spaces, resource_type="corpus_unit")

    def test_unknown_space_drops_every_space_grant(self):
        eff = compose_effective_scope(self._req(["ks-unknown"]), [_ks_grant("ks-shared")])
        assert eff.grant_scopes == []
        assert _spaces_of(eff) == {"ks-unknown"}
        assert eff.allow

    def test_only_requested_space_grants_survive(self):
        grants = [_ks_grant("ks-shared"), _ks_grant("ks-other")]
        eff = compose_effective_scope(self._req(["ks-shared"]), grants)
        assert [g.allowed_knowledge_space_ids for g in eff.grant_scopes] == [["ks-shared"]]

    def test_no_effective_grant_keeps_the_base_policy_reason(self):
        from src.access.policy import evaluate

        req = self._req(["ks-unknown"])
        eff = compose_effective_scope(req, [_ks_grant("ks-shared")])
        assert eff.reason_code == evaluate(req).reason_code

    def test_other_subjects_grants_never_apply(self):
        eff = compose_effective_scope(
            self._req(["ks-shared"]), [_ks_grant("ks-shared", subject="codex")])
        assert eff.grant_scopes == []


# --------------------------------------------------------------------------
# Shape validation of the requested space ids (contract layer)
# --------------------------------------------------------------------------
class TestRequestedSpaceShape:
    @pytest.mark.parametrize("bad", [[""], ["   "], ["x" * 257], ["a\nb"], ["ok", ""]])
    def test_malformed_space_ids_are_invalid_requests(self, mcp, bad):
        env = _search(mcp, "claude-code", knowledge_space_ids=bad)
        assert env["status"] == "INVALID_REQUEST"
        assert env.get("results", []) == []

    def test_well_formed_ids_still_pass(self, mcp):
        env = _search(mcp, "claude-code", knowledge_space_ids=["ks-shared", "ks.v2_x"])
        assert env["status"] == "SUCCESS"
