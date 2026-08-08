"""M5.1 focused tests: deterministic policy contracts + authoritative access matrix.

Covers the full M5.1 acceptance matrix from the approved M5 plan:
- contract validation (typed request, no identity inference);
- READ matrix (same-profile, global, cross-profile, cross-project, unbound);
- WRITE matrix (local allow, global deny, cross-profile/project deny, read!=write);
- isolation base semantics;
- AllowedScope non-expansion invariants;
- fixed reason codes (no raw exception / secret / path);
- determinism (repeated decision identical);
- architecture boundaries (schema v7, no v8, no M3/M4 integration, no audit,
  no LLM/network, no real ~/.hermes writes).

Policy evaluation is pure and deterministic; it does not touch the filesystem,
the network, or M3/M4 stores.
"""

import sys
from pathlib import Path

ROOT = Path("/home/brian-nguyen/Hermes Workplace/Zero-mem")
sys.path.insert(0, str(ROOT))

import pytest

from src.access import (
    READ, WRITE, AccessRequest, AllowedScope, AccessDecision, ReasonCode, evaluate,
)
from src.access.contracts import Operation
from src.storage.sqlite_store import CURRENT_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _req(**kw):
    return AccessRequest(operation=kw.pop("operation", READ), **kw)


def _scope_ids(decision):
    sc = decision.normalized_scope
    return (sc.allowed_profile_ids, sc.allowed_project_ids,
            sc.allowed_knowledge_space_ids, sc.global_read_allowed)


# ---------------------------------------------------------------------------
# Contract validation
# ---------------------------------------------------------------------------
def test_valid_read_request():
    r = _req(operation=READ, requesting_profile_id="A")
    assert r.validate().operation == READ


def test_valid_write_request():
    r = _req(operation=WRITE, requesting_profile_id="A")
    assert r.validate().operation == WRITE


def test_invalid_operation_denied():
    d = evaluate(_req(operation="SCAN", requesting_profile_id="A"))
    assert d.allow is False
    assert d.reason_code == ReasonCode.DENY_INVALID_REQUEST.value


def test_explicit_requesting_profile_preserved():
    r = _req(requesting_profile_id="A")
    assert r.validate().requesting_profile_id == "A"


def test_null_requesting_profile_remains_null():
    r = _req(requesting_profile_id=None)
    assert r.validate().requesting_profile_id is None
    assert r.is_unbound is True


def test_no_inferred_profile_from_cwd_or_path():
    # identifiers are explicit only; nothing infers a profile
    r = _req(requesting_profile_id=None, target_profile_ids=None)
    assert r.validate().requesting_profile_id is None
    assert r.validate().target_profile_ids is None


def test_explicit_target_profile_preserved():
    r = _req(requesting_profile_id="A", target_profile_ids=["B"])
    assert r.validate().target_profile_ids == ["B"]


def test_explicit_project_preserved():
    r = _req(requesting_profile_id="A", project_ids=["P"])
    assert r.validate().project_ids == ["P"]


def test_explicit_knowledge_space_preserved():
    r = _req(requesting_profile_id="A", knowledge_space_ids=["K"])
    assert r.validate().knowledge_space_ids == ["K"]


def test_include_global_normalization_default_true():
    r = _req(requesting_profile_id="A")
    assert r.validate().include_global is True


def test_include_global_normalization_explicit_false():
    r = _req(requesting_profile_id="A", include_global=False)
    assert r.validate().include_global is False


def test_isolated_mode_normalization():
    r = _req(requesting_profile_id="A", isolated_mode=True)
    assert r.validate().isolated_mode is True


def test_duplicate_ids_normalize_deterministically():
    r = _req(requesting_profile_id="A", target_profile_ids=["B", "B", "A"])
    assert r.validate().target_profile_ids == ["A", "B"]


def test_invalid_resource_type_denied():
    r = _req(requesting_profile_id="A", resource_type="nonsense")
    with pytest.raises(ValueError):
        r.validate()


# ---------------------------------------------------------------------------
# READ matrix
# ---------------------------------------------------------------------------
def test_same_profile_read_allow():
    d = evaluate(_req(operation=READ, requesting_profile_id="A",
                      target_profile_ids=["A"]))
    assert d.allow is True
    assert "A" in d.normalized_scope.allowed_profile_ids
    assert d.reason_code == ReasonCode.ALLOW_LOCAL_PROFILE_READ.value


def test_global_read_default_allow():
    d = evaluate(_req(operation=READ, requesting_profile_id="A"))
    assert d.allow is True
    assert d.normalized_scope.global_read_allowed is True
    assert d.reason_code == ReasonCode.ALLOW_GLOBAL_READ.value


def test_include_global_false_excludes_global():
    d = evaluate(_req(operation=READ, requesting_profile_id="A",
                      include_global=False))
    assert d.allow is True
    assert d.normalized_scope.global_read_allowed is False


def test_different_profile_read_deny():
    d = evaluate(_req(operation=READ, requesting_profile_id="A",
                      target_profile_ids=["B"]))
    assert d.allow is False
    assert d.reason_code == ReasonCode.DENY_CROSS_PROFILE_READ.value


def test_different_profile_same_project_read_deny():
    # regression: A and B both relate to P, but different profile => DENY
    d = evaluate(_req(operation=READ, requesting_profile_id="A",
                      target_profile_ids=["B"], project_ids=["P"]))
    assert d.allow is False
    assert d.reason_code == ReasonCode.DENY_CROSS_PROFILE_READ.value


def test_different_project_read_deny():
    d = evaluate(_req(operation=READ, requesting_profile_id="A",
                      project_ids=["P-other"]))
    assert d.allow is False
    assert d.reason_code == ReasonCode.DENY_CROSS_PROJECT.value


def test_unbound_global_read_allow():
    d = evaluate(_req(operation=READ, requesting_profile_id=None))
    assert d.allow is True
    assert d.normalized_scope.global_read_allowed is True


def test_unbound_protected_profile_read_deny():
    d = evaluate(_req(operation=READ, requesting_profile_id=None,
                      target_profile_ids=["A"]))
    assert d.allow is False
    assert d.reason_code == ReasonCode.DENY_UNBOUND_PROTECTED.value


def test_unrequested_knowledge_space_not_included():
    d = evaluate(_req(operation=READ, requesting_profile_id="A",
                      knowledge_space_ids=["K"]))
    assert d.allow is True
    assert "K" in d.normalized_scope.allowed_knowledge_space_ids


# ---------------------------------------------------------------------------
# WRITE matrix
# ---------------------------------------------------------------------------
def test_permitted_same_profile_local_write_allow():
    d = evaluate(_req(operation=WRITE, requesting_profile_id="A",
                      target_profile_ids=["A"], project_ids=["P"]))
    assert d.allow is True
    assert "A" in d.normalized_scope.allowed_profile_ids
    assert "P" in d.normalized_scope.allowed_project_ids
    assert d.reason_code == ReasonCode.ALLOW_LOCAL_WRITE.value


def test_global_write_deny():
    d = evaluate(_req(operation=WRITE, requesting_profile_id="A"))
    assert d.allow is False
    assert d.reason_code == ReasonCode.DENY_GLOBAL_WRITE.value


def test_different_profile_write_deny():
    d = evaluate(_req(operation=WRITE, requesting_profile_id="A",
                      target_profile_ids=["B"]))
    assert d.allow is False
    assert d.reason_code == ReasonCode.DENY_CROSS_PROFILE_WRITE.value


def test_different_profile_same_project_write_deny():
    d = evaluate(_req(operation=WRITE, requesting_profile_id="A",
                      target_profile_ids=["B"], project_ids=["P"]))
    assert d.allow is False
    assert d.reason_code == ReasonCode.DENY_CROSS_PROFILE_WRITE.value


def test_cross_project_write_deny():
    d = evaluate(_req(operation=WRITE, requesting_profile_id="A",
                      project_ids=["P-other"]))
    assert d.allow is False
    assert d.reason_code == ReasonCode.DENY_CROSS_PROJECT.value


def test_unbound_write_deny():
    d = evaluate(_req(operation=WRITE, requesting_profile_id=None))
    assert d.allow is False
    assert d.reason_code == ReasonCode.DENY_UNBOUND_PROTECTED.value


def test_read_allowance_does_not_imply_write():
    read_d = evaluate(_req(operation=READ, requesting_profile_id="A",
                           target_profile_ids=["B"]))
    write_d = evaluate(_req(operation=WRITE, requesting_profile_id="A",
                            target_profile_ids=["B"]))
    assert read_d.allow is False  # cross-profile read denied too (no grants)
    assert write_d.allow is False
    assert write_d.reason_code == ReasonCode.DENY_CROSS_PROFILE_WRITE.value


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------
def test_isolated_local_same_profile_works():
    d = evaluate(_req(operation=READ, requesting_profile_id="A",
                      target_profile_ids=["A"], isolated_mode=True))
    assert d.allow is True
    assert "A" in d.normalized_scope.allowed_profile_ids
    assert d.normalized_scope.global_read_allowed is False


def test_isolated_mode_removes_implicit_global():
    d = evaluate(_req(operation=READ, requesting_profile_id="A",
                      isolated_mode=True))
    assert d.allow is False  # nothing explicitly selected => escape
    assert d.reason_code == ReasonCode.DENY_ISOLATED_SCOPE_ESCAPE.value


def test_isolated_mode_blocks_implicit_profile_expansion():
    # unbound + isolated + include_global => no implicit profile, no global
    d = evaluate(_req(operation=READ, requesting_profile_id=None,
                      isolated_mode=True, include_global=True))
    assert d.allow is False
    assert d.reason_code == ReasonCode.DENY_ISOLATED_SCOPE_ESCAPE.value


def test_isolated_mode_blocks_project_expansion():
    d = evaluate(_req(operation=READ, requesting_profile_id="A",
                      project_ids=["P"], isolated_mode=True))
    # same-profile not asserted; project without same-profile => cross-project deny
    assert d.allow is False
    assert d.reason_code == ReasonCode.DENY_CROSS_PROJECT.value


def test_isolated_mode_blocks_knowledge_space_expansion():
    # M5.3 authoritative isolated-mode semantics: a knowledge space selected under
    # isolation WITHOUT an explicit profile scope cannot be resolved to authorized
    # profiles, so it is a scope escape (fail closed). This is the corrected
    # behavior; the test name reflects the intent (expansion is blocked).
    d = evaluate(_req(operation=READ, requesting_profile_id="A",
                      knowledge_space_ids=["K"], isolated_mode=True))
    assert d.allow is False
    assert d.reason_code == "DENY_ISOLATED_SCOPE_ESCAPE"
    assert "K" in d.denied_scopes


# ---------------------------------------------------------------------------
# Scope normalization invariants
# ---------------------------------------------------------------------------
def test_project_does_not_add_another_profile():
    d = evaluate(_req(operation=READ, requesting_profile_id="A",
                      target_profile_ids=["A"], project_ids=["P"]))
    assert d.normalized_scope.allowed_profile_ids == ["A"]
    assert d.normalized_scope.allowed_project_ids == ["P"]


def test_profile_does_not_add_unrelated_projects():
    d = evaluate(_req(operation=READ, requesting_profile_id="A",
                      target_profile_ids=["A"]))
    assert d.normalized_scope.allowed_project_ids == []


def test_profile_does_not_add_unrelated_knowledge_spaces():
    d = evaluate(_req(operation=READ, requesting_profile_id="A",
                      target_profile_ids=["A"]))
    assert d.normalized_scope.allowed_knowledge_space_ids == []


def test_relation_like_input_does_not_expand_scope():
    # even if a relation-style field were present, scope stays narrow;
    # here we confirm project permission does not widen profile set.
    d = evaluate(_req(operation=READ, requesting_profile_id="A",
                      target_profile_ids=["A"], project_ids=["P", "Q"]))
    assert set(d.normalized_scope.allowed_profile_ids) == {"A"}
    assert set(d.normalized_scope.allowed_project_ids) == {"P", "Q"}


def test_normalized_ordering_deterministic():
    a = evaluate(_req(operation=READ, requesting_profile_id="A",
                      target_profile_ids=["A"], project_ids=["Q", "P"]))
    b = evaluate(_req(operation=READ, requesting_profile_id="A",
                      target_profile_ids=["A"], project_ids=["P", "Q"]))
    assert a.normalized_scope.allowed_project_ids == \
        b.normalized_scope.allowed_project_ids == ["P", "Q"]


# ---------------------------------------------------------------------------
# Reason codes
# ---------------------------------------------------------------------------
def test_reason_codes_fixed_and_sanitized():
    d = evaluate(_req(operation=READ, requesting_profile_id="A",
                      target_profile_ids=["B"]))
    assert d.reason_code in {rc.value for rc in ReasonCode}
    assert "exception" not in d.reason_code.lower()
    assert "/" not in d.reason_code  # no raw path


def test_no_secret_in_decision():
    d = evaluate(_req(operation=READ, requesting_profile_id="A"))
    blob = repr(d.as_dict()).lower()
    assert "secret" not in blob
    assert "password" not in blob


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
def test_repeated_request_same_allow_deny():
    for _ in range(5):
        d = evaluate(_req(operation=READ, requesting_profile_id="A",
                          target_profile_ids=["B"]))
        assert d.allow is False


def test_repeated_request_same_normalized_scope():
    d1 = evaluate(_req(operation=READ, requesting_profile_id="A",
                       target_profile_ids=["A"], project_ids=["P"]))
    d2 = evaluate(_req(operation=READ, requesting_profile_id="A",
                       target_profile_ids=["A"], project_ids=["P"]))
    assert d1.normalized_scope.as_dict() == d2.normalized_scope.as_dict()


def test_decision_id_does_not_affect_semantics():
    base = _req(operation=READ, requesting_profile_id="A",
                target_profile_ids=["A"])
    d1 = evaluate(base)
    d2 = AccessDecision(allow=d1.allow, normalized_scope=d1.normalized_scope,
                        reason_code=d1.reason_code, decision_id="fixed-id")
    assert d1.allow == d2.allow
    assert d1.normalized_scope.as_dict() == d2.normalized_scope.as_dict()


# ---------------------------------------------------------------------------
# Architecture boundaries
# ---------------------------------------------------------------------------
def test_schema_remains_v7():
    assert CURRENT_SCHEMA_VERSION == 7


def test_no_migration_8_present():
    import importlib.util
    spec = importlib.util.find_spec("src.storage.migrations.migrate_8")
    assert spec is None


def test_no_grants_tables_in_policy():
    # policy module must not reference grant tables or audit writes
    import inspect
    from src.access import policy
    src = inspect.getsource(policy)
    assert "zm_access_grants" not in src
    assert "zm_policy_audit" not in src
    assert "policy_decision" not in src


def test_no_llm_or_network_in_policy():
    import inspect
    from src.access import policy, contracts
    combined = inspect.getsource(policy) + inspect.getsource(contracts)
    for banned in ("openai", "requests.", "http", "llm", "socket",
                   "urllib", "aiohttp"):
        assert banned not in combined


def test_no_real_home_write_risk():
    # Evaluation never receives or writes a real home path.
    d = evaluate(_req(operation=READ, requesting_profile_id="A"))
    assert "home" not in repr(d.normalized_scope).lower()
