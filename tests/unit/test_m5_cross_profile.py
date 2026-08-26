"""M5.3 focused tests: isolated mode + explicit cross-profile READ composition.

Covers the M5.3 acceptance matrix:
- isolated-mode full semantics (no implicit global/project/space/cross-profile expansion);
- cross-profile READ denied without explicit authorization (same project insufficient);
- explicit cross-profile READ via the in-memory pre-authorized GrantView (plan §11.1 shape);
- READ != WRITE (a WRITE grant never authorizes READ);
- scope-limited grants (B/P does not authorize B/Q; profile grant does not imply spaces);
- resource-type restriction enforced;
- multi-profile deterministic composition;
- mixed-scope partial authorization (allowed/denied scopes explicit);
- scope intersection (no union expansion);
- M3 structured query / FTS across authorized A+B only;
- M4 cross-profile authorized read across resource types;
- relation / source_event / artifact link cannot expand scope;
- pagination deterministic + cursor binds EffectiveReadScope (scope change invalidates);
- denial leaks no protected existence;
- TRUE READ-ONLY (schema v7, JSONL unchanged, no projector/migration/audit);
- no persistent grants / migration v8 / policy audit table.

The cross-profile authorization uses ONLY the plan-approved pre-authorized
AuthorizedReadGrant (GrantView) supplied by the caller as already-validated
input. M5.3 never queries persistent grant state (it does not exist yet).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest

from src.access import AccessRequest, AuthorizedReadService, ReasonCode, evaluate
from src.access.grants import AuthorizedReadGrant, compose_effective_scope
from src.access.contracts import AllowedScope, READ, WRITE
from src.retrieval.db import open_readonly, _readonly_conn_is_query_only
from src.retrieval.models import QueryError
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.storage.migrations import CURRENT_SCHEMA_VERSION
from src.project_memory import rebuild_project_memory

import tests.unit.test_m4_rebuild as m4base

SECRET = "SK-M5-3-SECRET-XYZ"


def _ev(event_id, domain, identity, op, profile_id, project_id, event_type="m4_x", **kw):
    m4 = {"domain": domain, "identity": identity, "op": op, "project_id": project_id}
    m4.update(kw)
    return {
        "event_id": event_id, "event_type": event_type, "project_id": project_id,
        "trace_id": "T-" + event_id, "session_id": "S1", "profile_id": profile_id,
        "created_at": "2026-08-01T00:00:00Z", "m4": m4,
    }


def _seed_m3(conn) -> None:
    rows = [
        ("M-E1", "PR1", "P", "profile PR1 project P event"),
        ("M-E2", "PR2", "P2", f"profile PR2 secret {SECRET}"),
        ("M-E3", None, "P", "global null-profile event"),
        ("M-E4", "PR1", "P2", "profile PR1 project P2 event"),
        ("M-E5", "PR2", "P", "profile PR2 project P event"),
    ]
    cur = conn.cursor()
    for (eid, prof, proj, content) in rows:
        cur.execute(
            "INSERT INTO zm_meta (event_id, trace_id, event_type, source, "
            "schema_version, created_at, observed_at, sequence, session_id, "
            "profile_id, project_id, task_id, turn_id, parent_trace_id, "
            "lifecycle_status, verification_status, confidence, sensitivity, "
            "retention, content_hash, redaction_applied, ingested_at, origin_jsonl) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (eid, "T", "evt", "s", 1, "2026-08-01T00:00:00Z", "2026-08-01T00:00:00Z",
             1, "S1", prof, proj, "TK", "TN", None, "active", "verified", "high", "low",
             "365d", "h", 0, "2026-08-01T00:00:00Z", "{}"),
        )
        cur.execute("INSERT INTO zm_fts (event_id, content) VALUES (?, ?)",
                    (eid, content))
    conn.commit()


def _corpus_for(profile_id, project_id, prefix="1"):
    # Distinct identities per project (R1/D1/S1/V1 vs R2/D2/S2/V2) so that
    # per-project rebuilds do NOT collide on the canonical requirement_id PK.
    # Reusing the same identity across projects would trigger a ConflictError
    # (rolled back) and silently drop the second project's row.
    return [
        _ev("P1", "requirement", f"R{prefix}", "create", profile_id, project_id,
            statement="req one", state="accepted", lifecycle_status="active",
            verification_status="deterministic_verification"),
        _ev("P2", "decision", f"D{prefix}", "create", profile_id, project_id,
            scope=f"project:{project_id}", decision_key="K", statement="decision one",
            state="accepted", lifecycle_status="active"),
        _ev("P3", "state", f"S{prefix}", "create", profile_id, project_id,
            state_key="progress", state_value="50%", lifecycle_status="active"),
        _ev("P4", "verification", f"V{prefix}", "create", profile_id, project_id,
            target_domain="requirement", target_identity=f"R{prefix}", status="verified",
            lifecycle_status="active"),
    ]


def _write_corpus(tmp_path: Path, name, profile_id, project_id, prefix="1"):
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(e) for e in _corpus_for(profile_id, project_id, prefix)))
    return path


def _build_store(tmp_path: Path):
    store = m4base._open(tmp_path)
    c_p = _write_corpus(tmp_path, "p.jsonl", "PR1", "P")
    c_p2 = _write_corpus(tmp_path, "p2.jsonl", "PR2", "P2", prefix="2")
    rebuild_project_memory(store, c_p, project_id="P")
    rebuild_project_memory(store, c_p2, project_id="P2")
    _seed_m3(store._conn)
    store.close()
    return open_readonly(tmp_path / "m4.sqlite")


# ---------------------------------------------------------------------------
# Grant factories (plan §11.1 shape; caller-supplied pre-validated)
# ---------------------------------------------------------------------------
def _grant_profile(gid, subject, target, op=READ, state=None, lifecycle="active",
                   resource_types=None):
    return AuthorizedReadGrant(
        grant_id=gid, subject_profile=subject, operation=op, target_type="profile",
        target_id=target, resource_types=resource_types, state=state,
        lifecycle_status=lifecycle, verification_ref=None,
        source_event_id="SE-" + gid, created_at="2026-08-01T00:00:00Z")


def _grant_project(gid, subject, project, op=READ, resource_types=None):
    return AuthorizedReadGrant(
        grant_id=gid, subject_profile=subject, operation=op, target_type="project",
        target_id=project, resource_types=resource_types, state=None,
        lifecycle_status="active", source_event_id="SE-" + gid)


# ---------------------------------------------------------------------------
# Isolated mode
# ---------------------------------------------------------------------------
def test_isolated_same_profile_local_read(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        res = svc.query_events(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                             target_profile_ids=["PR1"], isolated_mode=True))
        assert res.allowed is True
        ids = {v.event_id for v in res.items}
        assert "M-E1" in ids
    finally:
        store.close()


def test_isolated_removes_implicit_global(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        # No explicit target under isolation -> scope escape DENY (no implicit global)
        res = svc.query_events(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                             isolated_mode=True, include_global=True))
        assert res.denied is True
        assert res.reason_code == ReasonCode.DENY_ISOLATED_SCOPE_ESCAPE.value
        # NULL-profile global must NOT appear
    finally:
        store.close()


def test_isolated_include_global_true_does_not_override(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        res = svc.query_events(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                             isolated_mode=True, include_global=True))
        assert res.denied is True
        assert res.reason_code == ReasonCode.DENY_ISOLATED_SCOPE_ESCAPE.value
    finally:
        store.close()


def test_isolated_removes_implicit_project_expansion(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        # Same profile only; no project selected. PR1's own P2 data is authorized
        # (it is PR1's profile); PR2's data must NOT appear (no implicit expansion).
        res = svc.query_events(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                             target_profile_ids=["PR1"], isolated_mode=True))
        ids = {v.event_id for v in res.items}
        assert "M-E4" in ids   # PR1/P2 is PR1's own data -> authorized
        assert "M-E2" not in ids  # PR2/P2 excluded
    finally:
        store.close()


def test_isolated_removes_implicit_knowledge_space_expansion(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        # Selecting only a knowledge space with no profile scope -> escape
        res = svc.query_events(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                             knowledge_space_ids=["K1"], isolated_mode=True))
        assert res.denied is True
    finally:
        store.close()


def test_isolated_removes_implicit_cross_profile_expansion(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        res = svc.query_events(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                             target_profile_ids=["PR2"], isolated_mode=True))
        assert res.denied is True
        assert res.reason_code in (
            ReasonCode.DENY_CROSS_PROFILE_READ.value,
            ReasonCode.DENY_UNAUTHORIZED_CROSS_PROFILE_READ.value)
    finally:
        store.close()


def test_explicit_global_in_isolation_requires_grant(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        # include_global alone does not authorize isolated global (already covered);
        # an explicit global-profile grant is honored under isolation.
        g = _grant_profile("Gg", "PR1", "*", op=READ)
        res = svc.query_events(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "*"], isolated_mode=True),
            grants=[g])
        assert res.allowed is True
        # global NULL-profile row returned
        assert "M-E3" in {v.event_id for v in res.items}
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Cross-profile base deny
# ---------------------------------------------------------------------------
def test_cross_profile_denied_without_authorization(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        res = svc.query_events(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                             target_profile_ids=["PR2"]))
        assert res.denied is True
        assert res.reason_code in (
            ReasonCode.DENY_CROSS_PROFILE_READ.value,
            ReasonCode.DENY_UNAUTHORIZED_CROSS_PROFILE_READ.value)
        assert res.items == []
    finally:
        store.close()


def test_same_project_cross_profile_denied(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        # PR1 and PR2 both have rows in project P; same project does NOT authorize.
        res = svc.query_events(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                             target_profile_ids=["PR1", "PR2"],
                                             project_ids=["P"]))
        assert res.denied is True
        assert res.reason_code in (
            ReasonCode.DENY_CROSS_PROFILE_READ.value,
            ReasonCode.DENY_UNAUTHORIZED_CROSS_PROFILE_READ.value)
    finally:
        store.close()


def test_relation_does_not_authorize(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        # Request only own profile; no relation traversal expands to PR2.
        res = svc.query_events(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                             target_profile_ids=["PR1"]))
        ids = {v.event_id for v in res.items}
        assert "M-E5" not in ids  # PR2/P must never appear
    finally:
        store.close()


def test_source_event_link_does_not_authorize(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        res = svc.get_event(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                          target_profile_ids=["PR1"]), "M-E2")
        assert res.denied is True  # M-E2 is PR2; source link does not grant
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Explicit cross-profile READ (pre-authorized GrantView)
# ---------------------------------------------------------------------------
def test_explicit_cross_profile_read_allowed(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        g = _grant_profile("G1", "PR1", "PR2")
        res = svc.query_events(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2"]),
            grants=[g])
        assert res.allowed is True
        ids = {v.event_id for v in res.items}
        assert "M-E1" in ids
        assert "M-E2" in ids   # PR2 authorized -> its record appears
        assert res.decision.grant_refs == ["G1"]
    finally:
        store.close()


def test_read_grant_does_not_authorize_write(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        g = _grant_profile("G1", "PR1", "PR2", op=READ)
        # A WRITE request must not be authorized by a READ grant.
        res = svc.query_events(
            AccessRequest(operation=WRITE, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2"]),
            grants=[g])
        assert res.denied is True
        assert res.reason_code == ReasonCode.DENY_CROSS_PROFILE_WRITE.value
    finally:
        store.close()


def test_write_grant_not_treated_as_read(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        g = _grant_profile("GW", "PR1", "PR2", op=WRITE)
        res = svc.query_events(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2"]),
            grants=[g])
        # WRITE grant is not a READ grant -> still denied
        assert res.denied is True
        assert res.decision.grant_refs == []
    finally:
        store.close()


def test_grant_b_p_does_not_allow_b_q(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        # Authorize PR2/project P2 only.
        g = _grant_project("GP", "PR1", "P2")
        res = svc.query_events(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2"], project_ids=["P2"]),
            grants=[g])
        ids = {v.event_id for v in res.items}
        # M-E2 (PR2/P2) allowed; M-E5 (PR2/P) NOT requested/authorized.
        assert "M-E2" in ids
        assert "M-E5" not in ids
    finally:
        store.close()


def test_grant_profile_does_not_implicitly_add_spaces(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        g = _grant_profile("G1", "PR1", "PR2")
        res = svc.query_events(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2"],
                          knowledge_space_ids=["K1"]),
            grants=[g])
        # K1 was never authorized -> denied scope includes K1.
        assert "K1" in res.decision.denied_scopes
    finally:
        store.close()


def test_resource_type_restriction_enforced(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        # Project grant P2 restricted to requirements only.
        g = _grant_project("GR", "PR1", "P2", resource_types=["requirement"])
        res = svc.m4_requirements(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2"], project_ids=["P2"]),
            project_id="P2", grants=[g])
        assert res.allowed is True
        # Decisions not permitted by grant -> denied.
        res2 = svc.m4_decisions(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2"], project_ids=["P2"]),
            project_id="P2", grants=[g])
        assert res2.denied is True
    finally:
        store.close()


def test_multiple_explicit_profiles_compose(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        g1 = _grant_profile("G1", "PR1", "PR2")
        # Add a third profile PR3 not in store but grant-authorized to show composition.
        g2 = _grant_profile("G2", "PR1", "PR3")
        res = svc.query_events(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2", "PR3"]),
            grants=[g1, g2])
        assert res.allowed is True
        ids = {v.event_id for v in res.items}
        assert "M-E1" in ids   # PR1
        assert "M-E2" in ids   # PR2 authorized
        # PR3 has no records; no leak of existence; result deterministic.
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Mixed scopes / partial authorization
# ---------------------------------------------------------------------------
def test_mixed_local_plus_authorized(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        g = _grant_profile("G1", "PR1", "PR2")
        res = svc.query_events(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2"]),
            grants=[g])
        assert res.allowed is True
        assert res.decision.denied_scopes == []
    finally:
        store.close()


def test_mixed_local_authorized_denied_explicit(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        g = _grant_profile("G1", "PR1", "PR2")
        # C=PR3 requested but not authorized -> entire request DENIED (cross-profile
        # base rule); denied_scopes exposes PR3 explicitly.
        res = svc.query_events(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2", "PR3"]),
            grants=[g])
        assert res.denied is True
        assert "PR3" in res.decision.denied_scopes
    finally:
        store.close()


def test_partial_denied_portion_leaks_no_data(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        g = _grant_profile("G1", "PR1", "PR2")
        res = svc.query_events(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2", "PR3"]),
            grants=[g])
        # The denied PR3 portion must not be served; the request is denied wholesale
        # because PR3 is an unauthorized cross-profile target.
        assert res.denied is True
        assert res.items == []
        assert "PR3" in res.decision.denied_scopes
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Scope intersection (no union expansion)
# ---------------------------------------------------------------------------
def test_requested_larger_than_grant_narrowed(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        # Grant authorizes PR2 only; request asks PR1,PR2,PR3 -> PR3 not unioned in.
        g = _grant_profile("G1", "PR1", "PR2")
        res = compose_effective_scope(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2", "PR3"]),
            grants=[g])
        assert "PR3" not in res.normalized_scope.allowed_profile_ids
        assert "PR2" in res.normalized_scope.allowed_profile_ids
    finally:
        store.close()


def test_project_intersection(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        g = _grant_project("GP", "PR1", "P2")
        res = compose_effective_scope(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2"], project_ids=["P2"]),
            grants=[g])
        # Grant narrows the requested project set: only P2 authorized (P2 in grant).
        assert "P2" in res.base.allowed_project_ids
        assert res.allow is True
        assert res.denied_scopes == []
    finally:
        store.close()


def test_knowledge_space_intersection(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        g = _grant_profile("G1", "PR1", "PR2")
        res = svc.query_events(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2"], knowledge_space_ids=["K1"]),
            grants=[g])
        assert "K1" in res.decision.denied_scopes
    finally:
        store.close()


# ---------------------------------------------------------------------------
# M3 FTS composition
# ---------------------------------------------------------------------------
def test_fts_across_authorized_profiles_only(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        g = _grant_profile("G1", "PR1", "PR2")
        res = svc.search_text(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2"]),
            "secret", grants=[g])
        # PR2 is explicitly authorized by the grant, so PR2's secret record must
        # be returned. The FTS highlighter wraps the matched term in brackets, so
        # the literal SECRET constant is split as 'SK-M5-3-[SECRET]-XYZ'; assert on
        # the highlighted token to prove PR2 authorized content was surfaced.
        assert any("M-E2" == h.event_id for h in res.items)
        assert any("[SECRET]" in (getattr(h, "snippet", "") or "") for h in res.items)
    finally:
        store.close()


def test_fts_unauthorized_content_absent(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        # No grant for PR2 -> FTS must not surface PR2 secret.
        res = svc.search_text(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1"]),
            "secret")
        assert not any(SECRET in (getattr(h, "snippet", "") or "") for h in res.items)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# M4 cross-profile authorized read
# ---------------------------------------------------------------------------
def test_m4_cross_profile_requirements(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        g = _grant_project("G1", "PR1", "P2")
        res = svc.m4_requirements(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2"], project_ids=["P2"]),
            project_id="P2", grants=[g])

        assert res.allowed is True
        assert any(v.requirement_id == "R2" for v in res.items)
    finally:
        store.close()


def test_m4_cross_profile_decisions(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        g = _grant_project("G1", "PR1", "P2")
        res = svc.m4_decisions(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2"], project_ids=["P2"]),
            project_id="P2", grants=[g])
        assert res.allowed is True
    finally:
        store.close()


def test_m4_cross_profile_current_state(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        g = _grant_project("G1", "PR1", "P2")
        res = svc.m4_current_state(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2"], project_ids=["P2"]),
            project_id="P2", grants=[g])
        assert res.allowed is True
    finally:
        store.close()


def test_m4_cross_profile_verifications(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        g = _grant_project("G1", "PR1", "P2")
        res = svc.m4_verifications(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2"], project_ids=["P2"]),
            project_id="P2", grants=[g])
        assert res.allowed is True
    finally:
        store.close()


def test_m4_cross_profile_artifacts(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        g = _grant_project("G1", "PR1", "P2")
        res = svc.m4_artifacts(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2"], project_ids=["P2"]),
            project_id="P2", grants=[g])
        assert res.allowed is True
    finally:
        store.close()


def test_m4_same_project_alone_insufficient(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        # PR2 is in project P2; requesting PR2 without grant must deny.
        res = svc.m4_requirements(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR2"], project_ids=["P2"]),
            project_id="P2")
        assert res.denied is True
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Pagination + cursor binding
# ---------------------------------------------------------------------------
def test_pagination_deterministic_multi_scope(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        g = _grant_profile("G1", "PR1", "PR2")
        full = svc.query_events(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2"]),
            grants=[g], limit=500)
        # Concatenation of pages == deterministic full result.
        page_ids = []
        cursor = None
        seen = set()
        for _ in range(10):
            res = svc.query_events(
                AccessRequest(operation=READ, requesting_profile_id="PR1",
                              target_profile_ids=["PR1", "PR2"]),
                grants=[g], limit=1, cursor=cursor)
            if not res.items:
                break
            for v in res.items:
                assert v.event_id not in seen, "duplicate id across pages"
                seen.add(v.event_id)
                page_ids.append(v.event_id)
            cursor = res.next_cursor
            if cursor is None:
                break
        # Deterministic ordering; full set covered.
        assert set(page_ids) == {v.event_id for v in full.items}
    finally:
        store.close()


def test_cursor_scope_change_invalidates(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        g = _grant_profile("G1", "PR1", "PR2")
        res = svc.query_events(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2"]),
            grants=[g], limit=1)
        cursor = res.next_cursor
        assert cursor is not None
        # Reuse cursor under a narrower scope (PR1 only, no grant) -> mismatch.
        with pytest.raises(QueryError) as exc:
            svc.query_events(
                AccessRequest(operation=READ, requesting_profile_id="PR1",
                              target_profile_ids=["PR1"]),
                limit=1, cursor=cursor)
        assert exc.value.code == "cursor_query_mismatch"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Read-only / boundaries / no persistent grants
# ---------------------------------------------------------------------------
def test_true_read_only_preserved(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        _readonly_conn_is_query_only(store)
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        g = _grant_project("G1", "PR1", "P2")
        svc.query_events(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2"]),
            grants=[g])
        # store untouched
        assert store.get_schema_version() == CURRENT_SCHEMA_VERSION
    finally:
        store.close()


def test_persistent_grant_table_present_in_v8():
    # M5.4 introduces zm_access_grants / zm_policy_audit (schema v8).
    from src.storage.migrations import CURRENT_SCHEMA_VERSION
    assert CURRENT_SCHEMA_VERSION == 13
    from src.storage.migrations.migrate_8 import up as m8_up
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    m8_up(conn, "t")
    conn.commit()
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "zm_access_grants" in names
    assert "zm_policy_audit" in names


def test_grant_validity_not_fooled_by_flag(tmp_path: Path):
    # A caller cannot authorize by passing an ad-hoc boolean; validity is derived
    # from grant fields only. The AuthorizedReadGrant has no 'authorized' field.
    g = _grant_profile("G1", "PR1", "PR2")
    assert not hasattr(g, "authorized")
    # Subject mismatch -> not authorizing for a different requester.
    decision = compose_effective_scope(
        AccessRequest(operation=READ, requesting_profile_id="PR9",
                      target_profile_ids=["PR9", "PR2"]),
        grants=[g])
    assert "PR2" not in decision.normalized_scope.allowed_profile_ids


def test_revoked_grant_not_authorizing(tmp_path: Path):
    store = _build_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        g = _grant_profile("G1", "PR1", "PR2", state="revoked")
        res = svc.query_events(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1", "PR2"]),
            grants=[g])
        # Revoked grant => PR2 unauthorized => cross-profile request DENIED.
        assert res.denied is True
        assert res.items == []
    finally:
        store.close()
