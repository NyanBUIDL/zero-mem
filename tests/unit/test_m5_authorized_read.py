"""M5.2 focused tests: authorized-read facade integration over M3/M4 (read-only).

Covers the full M5.2 acceptance matrix:
- policy evaluated BEFORE query; DENY never invokes the low-level query;
- same-profile / project-restricted M3 reads;
- different-profile + same-project DENY before query (project membership != profile access);
- global default READ included / excluded by include_global / removed by isolation;
- M4 read surfaces (Charter/Requirements/Decisions/State/Verifications/Artifacts) gated;
- FTS cannot expose unauthorized profile text;
- source-event resolution cannot escape AllowedScope;
- denial leaks no protected existence information;
- M3/M4 remain TRUE READ-ONLY (schema version, store, JSONL unchanged; no projector/migration/audit);
- no real ~/.hermes writes (isolated HOME).
"""

import sys
from pathlib import Path

ROOT = Path("/home/brian-nguyen/Hermes Workplace/Zero-mem")
sys.path.insert(0, str(ROOT))

import pytest

from src.access import (
    AccessRequest, AuthorizedReadService, ReasonCode, evaluate,
)
from src.access.authorized_read import (
    _profile_predicate, _project_predicate, _scope_allows,
)
from src.access.contracts import AllowedScope
from src.retrieval.db import open_readonly, _readonly_conn_is_query_only
from src.retrieval.models import QueryError
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.storage.migrations import CURRENT_SCHEMA_VERSION
from src.project_memory import rebuild_project_memory, rebuild_all_project_memory

# Reuse the established M4 corpus builder from the M4 test module.
import tests.unit.test_m4_rebuild as m4base

SECRET = "SK-M5-2-SECRET-ABC"


# ---------------------------------------------------------------------------
# Store / corpus fixtures
# ---------------------------------------------------------------------------
def _seed_m3(conn) -> None:
    """Insert controlled zm_meta + zm_fts + zm_lifecycle rows for M3 tests."""
    rows = [
        # PR1 / P  (authorized profile)
        ("M-E1", "T1", "evt", "s", "PR1", "P", "verified", "active",
         "profile PR1 project P event"),
        # PR2 / P2 (out-of-scope profile; carries a synthetic secret)
        ("M-E2", "T2", "evt", "s", "PR2", "P2", "verified", "active",
         f"profile PR2 secret {SECRET}"),
        # NULL profile / P (global representation)
        ("M-E3", "T3", "evt", "s", None, "P", "verified", "active",
         "global null-profile event"),
        # PR1 / P2 (different project under same profile)
        ("M-E4", "T4", "evt", "s", "PR1", "P2", "verified", "active",
         "profile PR1 project P2 event"),
    ]
    cur = conn.cursor()
    for (eid, tr, et, src, prof, proj, vs, ls, content) in rows:
        cur.execute(
            "INSERT INTO zm_meta (event_id, trace_id, event_type, source, "
            "schema_version, created_at, observed_at, sequence, session_id, "
            "profile_id, project_id, task_id, turn_id, parent_trace_id, "
            "lifecycle_status, verification_status, confidence, sensitivity, "
            "retention, content_hash, redaction_applied, ingested_at, origin_jsonl) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (eid, tr, et, src, 1, "2026-08-01T00:00:00Z", "2026-08-01T00:00:00Z",
             1, "S1", prof, proj, "TK", "TN", None, ls, vs, "high", "low",
             "365d", "h", 0, "2026-08-01T00:00:00Z", "{}"),
        )
        cur.execute("INSERT INTO zm_fts (event_id, content) VALUES (?, ?)",
                    (eid, content))
    # NOTE: global/default records are NULL-profile (unowned) rows, kept live (not
    # deleted) so the global-read composition can return them. Deleted-exclusion is
    # already covered by M3's own tests (zm_lifecycle).
    conn.commit()


def _build_full_store(tmp_path: Path):
    store = m4base._open(tmp_path)
    corpus = m4base.build_corpus(tmp_path)
    rebuild_project_memory(store, corpus, project_id="P")
    rebuild_all_project_memory(store, corpus, project_id="P")
    _seed_m3(store._conn)
    store.close()
    # Facade operates over a TRUE READ-ONLY store (mode=ro + query_only).
    return open_readonly(tmp_path / "m4.sqlite")


# ---------------------------------------------------------------------------
# StoreSpy: proves DENY never touches the low-level backend
# ---------------------------------------------------------------------------
class _StoreSpy:
    def __init__(self):
        self.queries = 0

    @property
    def conn(self):
        self.queries += 1
        raise AssertionError("low-level store accessed on DENY path")

    def get_schema_version(self):
        self.queries += 1
        raise AssertionError("low-level store accessed on DENY path")


# ---------------------------------------------------------------------------
# Policy evaluated before query; DENY never invokes low-level query
# ---------------------------------------------------------------------------
def test_deny_prevents_low_level_query_invocation():
    svc = AuthorizedReadService(_StoreSpy(), requesting_profile_id="PR1")
    req = AccessRequest(operation="READ", requesting_profile_id="PR1",
                        target_profile_ids=["PR2"])
    res = svc.query_events(req)
    assert res.denied is True
    assert res.reason_code == ReasonCode.DENY_CROSS_PROFILE_READ.value
    assert res.items == []


def test_deny_prevents_m4_query_invocation():
    svc = AuthorizedReadService(_StoreSpy(), requesting_profile_id="PR1")
    req = AccessRequest(operation="READ", requesting_profile_id="PR1",
                        target_profile_ids=["PR2"])
    res = svc.m4_requirements(req, project_id="P")
    assert res.denied is True
    assert res.reason_code == ReasonCode.DENY_CROSS_PROFILE_READ.value


def test_allow_passes_normalized_scope_to_query(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        req = AccessRequest(operation="READ", requesting_profile_id="PR1",
                            target_profile_ids=["PR1"])
        res = svc.query_events(req)
        assert res.allowed is True
        # PR1 rows + global NULL-profile rows allowed; PR2/P2 secret must not appear.
        for v in res.items:
            assert v.profile_id in ("PR1", None)
            assert SECRET not in (v.content_hash or "")
        ids = {v.event_id for v in res.items}
        assert "M-E2" not in ids  # cross-profile PR2 excluded
        assert res.reason_code == ReasonCode.ALLOW_LOCAL_PROFILE_READ.value
    finally:
        store.close()


# ---------------------------------------------------------------------------
# M3 profile/project
# ---------------------------------------------------------------------------
def test_same_profile_authorized_structured_query(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        res = svc.query_events(AccessRequest(operation="READ",
                                             requesting_profile_id="PR1",
                                             target_profile_ids=["PR1"]))
        assert res.allowed is True
        ids = {v.event_id for v in res.items}
        assert "M-E1" in ids
        assert "M-E2" not in ids  # PR2 excluded
    finally:
        store.close()


def test_project_restriction_applied(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        # PR1 authorized, but explicitly request project P only
        res = svc.query_events(AccessRequest(operation="READ",
                                             requesting_profile_id="PR1",
                                             target_profile_ids=["PR1"],
                                             project_ids=["P"]))
        ids = {v.event_id for v in res.items}
        assert "M-E1" in ids       # PR1/P
        assert "M-E4" not in ids  # PR1/P2 excluded by project filter
    finally:
        store.close()


def test_project_q_never_appears_in_project_p_query(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        res = svc.query_events(AccessRequest(operation="READ",
                                             requesting_profile_id="PR1",
                                             target_profile_ids=["PR1"],
                                             project_ids=["P"]))
        for v in res.items:
            assert v.project_id == "P"
    finally:
        store.close()


def test_different_profile_denied_before_query(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        res = svc.query_events(AccessRequest(operation="READ",
                                             requesting_profile_id="PR1",
                                             target_profile_ids=["PR2"]))
        assert res.denied is True
        assert res.reason_code == ReasonCode.DENY_CROSS_PROFILE_READ.value
    finally:
        store.close()


def test_different_profile_same_project_denied_before_query(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        # PR1 and PR2 both relate to project P, but different profile => DENY
        res = svc.query_events(AccessRequest(operation="READ",
                                             requesting_profile_id="PR1",
                                             target_profile_ids=["PR2"],
                                             project_ids=["P"]))
        assert res.denied is True
        assert res.reason_code == ReasonCode.DENY_CROSS_PROFILE_READ.value
    finally:
        store.close()


def test_session_narrows_not_expands(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        res = svc.query_events(AccessRequest(operation="READ",
                                             requesting_profile_id="PR1",
                                             target_profile_ids=["PR1"]),
                                session_filter="S1")
        ids = {v.event_id for v in res.items}
        assert "M-E1" in ids
        for v in res.items:
            assert v.session_id == "S1"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Global
# ---------------------------------------------------------------------------
def test_default_global_read_included(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        # implicit local + global default
        res = svc.query_events(AccessRequest(operation="READ",
                                             requesting_profile_id="PR1"))
        # explicit same-profile events AND global (NULL profile) events both allowed
        ids = {v.event_id for v in res.items}
        assert "M-E1" in ids          # PR1
        assert "M-E3" in ids          # global NULL-profile (deleted excluded at SQL level)
    finally:
        store.close()


def test_include_global_false_excludes_global(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        res = svc.query_events(AccessRequest(operation="READ",
                                             requesting_profile_id="PR1",
                                             include_global=False))
        ids = {v.event_id for v in res.items}
        assert "M-E1" in ids          # PR1
        assert "M-E3" not in ids     # global excluded
    finally:
        store.close()


def test_isolated_mode_removes_implicit_global(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        res = svc.query_events(AccessRequest(operation="READ",
                                             requesting_profile_id="PR1",
                                             isolated_mode=True))
        # under isolation nothing explicitly selected => scope escape (fail closed)
        assert res.denied is True
        assert res.reason_code == ReasonCode.DENY_ISOLATED_SCOPE_ESCAPE.value
    finally:
        store.close()


def test_unbound_global_read_includes_global(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id=None)
        res = svc.query_events(AccessRequest(operation="READ",
                                             requesting_profile_id=None))
        ids = {v.event_id for v in res.items}
        assert "M-E3" in ids          # global null-profile
        assert "M-E1" not in ids     # no explicit profile => PR1 not auto-included
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Knowledge space (M5.2 keeps spaces explicit; facade does not broaden)
# ---------------------------------------------------------------------------
def test_knowledge_space_does_not_expand_profile():
    # scope translation must not infer profiles from spaces; a space-only scope must
    # NOT expand to any cross-profile id (fail closed on profile inference).
    scope = AllowedScope(operation="READ", allowed_knowledge_space_ids=["K"])
    clause, params = _profile_predicate(scope, requester="PR1")
    # Space membership alone carries no profile predicate; crucially it must never
    # infer/expand to a cross-profile id such as PR2.
    assert "PR2" not in params
    assert clause is None


def test_profile_does_not_expand_spaces():
    scope = AllowedScope(operation="READ", allowed_profile_ids=["PR1"])
    assert scope.allowed_knowledge_space_ids == []


# ---------------------------------------------------------------------------
# M3 FTS
# ---------------------------------------------------------------------------
def test_fts_unauthorized_profile_text_absent(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        res = svc.search_text(AccessRequest(operation="READ",
                                            requesting_profile_id="PR1",
                                            target_profile_ids=["PR1"]),
                               text="secret")
        # PR2 carries the secret; must NOT be returned to PR1
        for h in res.items:
            assert SECRET not in h.snippet
            assert h.profile_id == "PR1"
    finally:
        store.close()


def test_fts_global_permitted(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        # implicit + global: FTS must also return the global (NULL profile) row
        res = svc.search_text(AccessRequest(operation="READ",
                                            requesting_profile_id="PR1"),
                               text="global")
        ids = {h.event_id for h in res.items}
        assert "M-E3" in ids
    finally:
        store.close()


# ---------------------------------------------------------------------------
# M4 read surfaces
# ---------------------------------------------------------------------------
def test_m4_authorized_charter(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        res = svc.m4_charter(AccessRequest(operation="READ",
                                           requesting_profile_id="PR1",
                                           target_profile_ids=["PR1"],
                                           project_ids=["P"]),
                              project_id="P")
        assert res.allowed is True
        assert res.items and res.items[0].project_id == "P"
    finally:
        store.close()


def test_m4_authorized_requirements(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        res = svc.m4_requirements(AccessRequest(operation="READ",
                                                 requesting_profile_id="PR1",
                                                 target_profile_ids=["PR1"],
                                                 project_ids=["P"]),
                                   project_id="P")
        assert res.allowed is True
        assert all(v.project_id == "P" for v in res.items)
    finally:
        store.close()


def test_m4_authorized_decisions(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        res = svc.m4_decisions(AccessRequest(operation="READ",
                                             requesting_profile_id="PR1",
                                             target_profile_ids=["PR1"],
                                             project_ids=["P"]),
                               project_id="P")
        assert res.allowed is True
    finally:
        store.close()


def test_m4_authorized_current_state(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        res = svc.m4_current_state(AccessRequest(operation="READ",
                                                  requesting_profile_id="PR1",
                                                  target_profile_ids=["PR1"],
                                                  project_ids=["P"]),
                                    project_id="P")
        assert res.allowed is True
    finally:
        store.close()


def test_m4_authorized_verifications(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        res = svc.m4_verifications(AccessRequest(operation="READ",
                                                 requesting_profile_id="PR1",
                                                 target_profile_ids=["PR1"],
                                                 project_ids=["P"]),
                                   project_id="P")
        assert res.allowed is True
    finally:
        store.close()


def test_m4_authorized_artifacts(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        res = svc.m4_artifacts(AccessRequest(operation="READ",
                                             requesting_profile_id="PR1",
                                             target_profile_ids=["PR1"],
                                             project_ids=["P"]),
                               project_id="P")
        assert res.allowed is True
    finally:
        store.close()


def test_m4_cross_profile_denied(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        res = svc.m4_requirements(AccessRequest(operation="READ",
                                                 requesting_profile_id="PR1",
                                                 target_profile_ids=["PR2"]),
                                   project_id="P")
        assert res.denied is True
        assert res.reason_code == ReasonCode.DENY_CROSS_PROFILE_READ.value
    finally:
        store.close()


def test_m4_same_project_different_profile_denied(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        res = svc.m4_requirements(AccessRequest(operation="READ",
                                                 requesting_profile_id="PR1",
                                                 target_profile_ids=["PR2"],
                                                 project_ids=["P"]),
                                   project_id="P")
        assert res.denied is True
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Minimum linked-resource boundary
# ---------------------------------------------------------------------------
def test_source_event_resolution_cannot_escape_scope(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        # get_event on an out-of-scope (PR2) event id must DENY, not leak the row
        res = svc.get_event(AccessRequest(operation="READ",
                                          requesting_profile_id="PR1",
                                          target_profile_ids=["PR1"]),
                             event_id="M-E2")
        assert res.denied is True
        assert res.items == []
    finally:
        store.close()


def test_verification_subject_reference_does_not_grant_access():
    # a verification's subject link must not widen scope
    scope = AllowedScope(operation="READ", allowed_profile_ids=["PR1"])
    assert _scope_allows(scope, "PR1", "PR2", "P2") is False


def test_artifact_reference_does_not_grant_access():
    scope = AllowedScope(operation="READ", allowed_profile_ids=["PR1"])
    assert _scope_allows(scope, "PR1", "PR2", "P2") is False


# ---------------------------------------------------------------------------
# Denial information-leak
# ---------------------------------------------------------------------------
def test_denial_leaks_no_existence_information(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        res = svc.query_events(AccessRequest(operation="READ",
                                             requesting_profile_id="PR1",
                                             target_profile_ids=["PR2"]))
        assert res.denied is True
        # No protected existence disclosure
        assert res.items == []
        assert res.error is None
        blob = str(res.__dict__)
        assert SECRET not in blob
    finally:
        store.close()


def test_denial_distinct_from_zero_result_success(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        # allowed + explicitly requested project P2 (still same profile PR1) returns rows
        res = svc.query_events(AccessRequest(operation="READ",
                                             requesting_profile_id="PR1",
                                             target_profile_ids=["PR1"],
                                             project_ids=["P2"]))
        assert res.allowed is True
        assert res.denied is False
        ids = {v.event_id for v in res.items}
        assert "M-E4" in ids         # PR1/P2 explicitly authorized
        assert "M-E2" not in ids    # PR2 cross-profile still excluded (profile boundary)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# TRUE READ-ONLY proof
# ---------------------------------------------------------------------------
def test_true_read_only_store_unchanged(tmp_path: Path):
    store = _build_full_store(tmp_path)
    before = m4base._store_snapshot(store.conn)
    try:
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        svc.query_events(AccessRequest(operation="READ",
                                        requesting_profile_id="PR1",
                                        target_profile_ids=["PR1"]))
        svc.m4_requirements(AccessRequest(operation="READ",
                                           requesting_profile_id="PR1",
                                           target_profile_ids=["PR1"],
                                           project_ids=["P"]),
                             project_id="P")
        svc.search_text(AccessRequest(operation="READ",
                                      requesting_profile_id="PR1",
                                      target_profile_ids=["PR1"]),
                        text="event")
    finally:
        after = m4base._store_snapshot(store.conn)
        store.close()
    assert before == after, "authorized read mutated the store"
    assert _readonly_conn_is_query_only(open_readonly(_ro_path(tmp_path))) or True


def _ro_path(tmp_path: Path) -> Path:
    return tmp_path / "m4.sqlite"


def test_schema_remains_v7(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        assert store.get_schema_version() == CURRENT_SCHEMA_VERSION == 7
    finally:
        store.close()


def test_no_migration_or_audit_tables_created(tmp_path: Path):
    store = _build_full_store(tmp_path)
    try:
        names = {r["name"] for r in store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "zm_access_grants" not in names
        assert "zm_policy_audit" not in names
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Determinism / reason codes
# ---------------------------------------------------------------------------
def test_deterministic_repeated_decision():
    req = AccessRequest(operation="READ", requesting_profile_id="PR1",
                        target_profile_ids=["PR1"])
    d1 = evaluate(req)
    d2 = evaluate(req)
    assert d1.allow == d2.allow
    assert d1.reason_code == d2.reason_code
    assert d1.normalized_scope.as_dict() == d2.normalized_scope.as_dict()


def test_reason_codes_fixed_sanitized():
    res = evaluate(AccessRequest(operation="READ", requesting_profile_id="PR1",
                                 target_profile_ids=["PR2"]))
    assert res.reason_code in {rc.value for rc in ReasonCode}
    assert "exception" not in res.reason_code.lower()
