"""DEF-051: ``authorize_write`` must not let "own profile + knowledge space/project" bypass the WRITE grant.

Matrix source: docs/design/SHARED-MEMORY-RUNTIME.md section 4 (requester ``claude-code``,
``resource_type=corpus_source``). A request that names the requester's own profile PLUS a
knowledge space or project must need exactly the same persistent, verified WRITE grant as the
knowledge-space/project-only request. Own-profile-only stays ``ALLOW_LOCAL_WRITE``.

Synthetic in-memory store only; no network, no LLM, no real ~/.hermes.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pytest

from src.access import AccessRequest, ReasonCode
from src.access import authorized_write, grant_events
from src.access.contracts import WRITE
from src.storage.migrations import migrate_8

ME = "claude-code"
KS = "ks-shared"
KS_OTHER = "ks-other"
PROJ = "proj-a"
PROJ_OTHER = "proj-b"
RT = "corpus_source"

ALLOW_LOCAL = ReasonCode.ALLOW_LOCAL_WRITE.value
ALLOW_CROSS = ReasonCode.ALLOW_EXPLICIT_CROSS_PROFILE_WRITE.value
DENY_CROSS = ReasonCode.DENY_CROSS_PROFILE_WRITE.value
DENY_GLOBAL = ReasonCode.DENY_GLOBAL_WRITE.value


@dataclass
class _Ver:
    verification_status: str


def _verified(ref):
    return _Ver("verified") if ref == "V1" else None


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    migrate_8.up(conn, "test")
    conn.commit()
    return conn


def _grant(conn, gid, target_type, target_id, resource_types=None):
    grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
        grant_id=gid, subject_profile=ME, operation=WRITE,
        target_type=target_type, target_id=target_id, op="create",
        verification_ref="V1", resource_types=resource_types))
    conn.commit()


def _authz(conn, **kw):
    kw.setdefault("resource_type", RT)
    req = AccessRequest(operation=WRITE, requesting_profile_id=ME, **kw)
    return authorized_write.authorize_write(req, conn, _verified)


# --- baseline rows of the matrix that must keep working -----------------------------------

def test_own_profile_only_is_local_write():
    d = _authz(_conn(), target_profile_ids=[ME])
    assert d.allow and d.reason_code == ALLOW_LOCAL


def test_no_target_is_global_write_denied():
    d = _authz(_conn())
    assert not d.allow and d.reason_code == DENY_GLOBAL


def test_other_profile_denied():
    d = _authz(_conn(), target_profile_ids=["codex"])
    assert not d.allow and d.reason_code == DENY_CROSS


@pytest.mark.parametrize("kw", [
    {"knowledge_space_ids": [KS]},
    {"project_ids": [PROJ]},
])
def test_ks_or_project_only_without_grant_denied(kw):
    d = _authz(_conn(), **kw)
    assert not d.allow and d.reason_code == DENY_CROSS


@pytest.mark.parametrize("target_type,target_id,kw", [
    ("knowledge_space", KS, {"knowledge_space_ids": [KS]}),
    ("project", PROJ, {"project_ids": [PROJ]}),
])
def test_ks_or_project_only_with_verified_grant_allowed(target_type, target_id, kw):
    conn = _conn()
    _grant(conn, "GW", target_type, target_id, [RT])
    d = _authz(conn, **kw)
    assert d.allow and d.reason_code == ALLOW_CROSS and d.grant_refs == ["GW"]


# --- DEF-051: the bypass rows (RED before the fix) ----------------------------------------

@pytest.mark.parametrize("kw", [
    {"target_profile_ids": [ME], "knowledge_space_ids": [KS]},
    {"target_profile_ids": [ME], "project_ids": [PROJ]},
])
def test_own_profile_plus_ks_or_project_without_grant_is_denied(kw):
    d = _authz(_conn(), **kw)
    assert not d.allow, "own profile must not bypass the WRITE grant for a KS/project"
    assert d.reason_code == DENY_CROSS
    assert d.reason_code != ALLOW_LOCAL


@pytest.mark.parametrize("target_type,target_id,kw", [
    ("knowledge_space", KS, {"target_profile_ids": [ME], "knowledge_space_ids": [KS]}),
    ("project", PROJ, {"target_profile_ids": [ME], "project_ids": [PROJ]}),
])
def test_own_profile_plus_ks_or_project_with_verified_grant_matches_scope_only_request(
        target_type, target_id, kw):
    conn = _conn()
    _grant(conn, "GW", target_type, target_id, [RT])
    combined = _authz(conn, **kw)
    only = _authz(conn, **{k: v for k, v in kw.items() if k != "target_profile_ids"})
    assert combined.allow and combined.reason_code == ALLOW_CROSS
    assert combined.grant_refs == ["GW"]
    # identical decision to the KS/project-only request (same scope, same reason, same grant)
    assert combined == only


def test_grant_for_other_ks_does_not_cover_own_profile_plus_ks():
    conn = _conn()
    _grant(conn, "GW", "knowledge_space", KS, [RT])
    d = _authz(conn, target_profile_ids=[ME], knowledge_space_ids=[KS_OTHER])
    assert not d.allow and d.reason_code == DENY_CROSS


def test_grant_for_other_project_does_not_cover_own_profile_plus_project():
    conn = _conn()
    _grant(conn, "GW", "project", PROJ, [RT])
    d = _authz(conn, target_profile_ids=[ME], project_ids=[PROJ_OTHER])
    assert not d.allow and d.reason_code == DENY_CROSS


def test_resource_type_restriction_applies_to_own_profile_plus_ks():
    conn = _conn()
    _grant(conn, "GW", "knowledge_space", KS, ["corpus_unit"])  # not corpus_source
    d = _authz(conn, target_profile_ids=[ME], knowledge_space_ids=[KS])
    assert not d.allow and d.reason_code == DENY_CROSS


def test_own_profile_plus_ks_and_project_is_denied_even_with_one_grant():
    # Grants are scoped to ONE target; a request spanning two dimensions has no single
    # grant scope and must fail closed, with or without the own-profile decoration.
    conn = _conn()
    _grant(conn, "GW", "knowledge_space", KS, [RT])
    d = _authz(conn, target_profile_ids=[ME], knowledge_space_ids=[KS], project_ids=[PROJ])
    assert not d.allow
    only = _authz(conn, knowledge_space_ids=[KS], project_ids=[PROJ])
    assert not only.allow


def test_own_profile_plus_two_spaces_is_denied():
    conn = _conn()
    _grant(conn, "GW", "knowledge_space", KS, [RT])
    d = _authz(conn, target_profile_ids=[ME], knowledge_space_ids=[KS, KS_OTHER])
    assert not d.allow


def test_other_profile_plus_ks_still_denied():
    conn = _conn()
    _grant(conn, "GW", "knowledge_space", KS, [RT])
    d = _authz(conn, target_profile_ids=["codex"], knowledge_space_ids=[KS])
    assert not d.allow and d.reason_code == DENY_CROSS


def test_write_service_facade_and_writer_not_invoked_for_bypass_shape():
    conn = _conn()
    calls = []
    req = AccessRequest(operation=WRITE, requesting_profile_id=ME, resource_type=RT,
                        target_profile_ids=[ME], knowledge_space_ids=[KS])
    decision, result = authorized_write.authorize_then_write(
        req, conn, _verified, lambda r: calls.append(r) or "MUTATED")
    assert not decision.allow and result is None and calls == []


def test_isolated_mode_own_profile_plus_ks_is_not_a_bypass():
    d = _authz(_conn(), target_profile_ids=[ME], knowledge_space_ids=[KS], isolated_mode=True)
    assert not d.allow
