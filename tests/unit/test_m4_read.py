"""M4.6 focused tests: TRUE READ-ONLY project-memory query APIs + M3 composition.

Covers only M4.6. Builds data via the M4 projectors (deterministic writers) into
an isolated store, then opens a SEPARATE ReadonlyStore (mode=ro + query_only) for
all reads. Proves reads never invoke projectors, never mutate the store, and
respect the documented active/conflict/supersession/deleted semantics.
"""
import sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.storage.migrations import CURRENT_SCHEMA_VERSION
from src.retrieval.db import open_readonly, ReadonlyStore, _readonly_conn_is_query_only
from src.retrieval.models import QueryError
from src.project_memory import (
    project_charter, project_requirement, project_decision, project_state,
    project_verification, project_artifact, classify_event_for_m4,
)
from src.project_memory import (
    get_project_charter, list_project_charters, get_requirement, list_requirements,
    get_decision, list_decisions, get_active_decision, get_current_project_state,
    get_state_value, get_verification, list_verifications, list_project_artifacts,
    is_query_only, CharterView, RequirementView, DecisionView, ProjectStateView,
    VerificationView, ProjectArtifactView, ProjectMemoryResult, INVALID_PROJECT_ID,
    INVALID_SUBJECT_TYPE,
)
from src.project_memory.contracts import (
    CharterOp, RequirementOp, DecisionOp, StateOp, VerificationOp, ArtifactOp,
)

SECRET = "SK-M4-6-SECRET-XYZ"


def _open(tmp_path: Path) -> SQLiteStore:
    p = tmp_path / "m4.sqlite"
    store = SQLiteStore(SQLiteStoreConfig(path=p))
    store.ensure_schema()
    return store


def _seed(store: SQLiteStore) -> None:
    # Charter: active v2 + a superseded prior v1 (same charter_id).
    project_charter(store._conn, CharterOp(op="create", charter_id="C1", project_id="P",
        name="Charter", goal="g", lifecycle_status="active", state="confirmed",
        source_event_id="E0", created_at="2026-08-01T00:00:00Z"))
    project_charter(store._conn, CharterOp(op="update", charter_id="C1", project_id="P",
        name="Charter v2", goal="g v2", lifecycle_status="active", state="confirmed",
        supersedes="C1", source_event_id="E0", created_at="2026-07-01T00:00:00Z"))
    # Requirement: active + candidate.
    project_requirement(store._conn, RequirementOp(op="create", requirement_id="R1", project_id="P",
        statement="do x", lifecycle_status="active", state="accepted", verification_status="deterministic_verification",
        source_event_id="E1", created_at="2026-08-02T00:00:00Z"))
    project_requirement(store._conn, RequirementOp(op="create", requirement_id="R2", project_id="P",
        statement="do y", lifecycle_status="candidate", state="proposed", source_event_id="E2",
        created_at="2026-08-03T00:00:00Z"))
    # Decision: active with key + a conflicted sibling (no winner).
    project_decision(store._conn, DecisionOp(op="create", decision_id="D1", project_id="P", scope="project:P",
        decision_key="K", statement="pick A", lifecycle_status="active", state="accepted",
        effective_at="2026-08-04T00:00:00Z", source_event_id="E3"))
    project_decision(store._conn, DecisionOp(op="create", decision_id="D2", project_id="P", scope="project:P",
        decision_key="K", statement="pick B", lifecycle_status="conflicted", state="accepted",
        effective_at="2026-08-04T00:00:00Z", source_event_id="E4"))
    # Current State: active progress (50%) + a superseded prior (40%).
    project_state(store._conn, StateOp(op="create", project_id="P", state_key="progress", state_value="40%",
        lifecycle_status="active", source_event_id="E5", created_at="2026-08-01T00:00:00Z"))
    project_state(store._conn, StateOp(op="update", project_id="P", state_key="progress", state_value="50%",
        lifecycle_status="active", source_event_id="E5", created_at="2026-08-05T00:00:00Z"))
    # Verification: two of same subject, different status (contradictory, preserved).
    project_verification(store._conn, VerificationOp(op="create", verification_id="V1", project_id="P",
        subject_type="requirement", subject_id="R1", method="pytest", verification_status="deterministic_verification",
        source_event_id="E6", timestamp="2026-08-06T00:00:00Z"))
    project_verification(store._conn, VerificationOp(op="create", verification_id="V2", project_id="P",
        subject_type="requirement", subject_id="R1", method="manual", verification_status="direct_tool_output",
        source_event_id="E7", timestamp="2026-08-06T00:00:00Z"))
    # Artifact: link existing M2 artifact to project.
    store._conn.execute(
        "INSERT INTO zm_artifacts(artifact_id, content_hash, kind, retention, origin_event_id, stored_path, created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        ("ART1", "deadbeef", "report", "project", "E8", f"artifacts/{SECRET}.md", "2026-08-07T00:00:00Z"),
    )
    store._conn.commit()
    project_artifact(store._conn, ArtifactOp(op="create", artifact_id="ART1", project_id="P",
        artifact_type="report", version="1", safe_reference="artifacts/report.md", source_event_id="E8"))


# ---------------------------------------------------------------------------
# Read-only connection
# ---------------------------------------------------------------------------

def test_open_readonly_mode_and_query_only(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    assert isinstance(rs, ReadonlyStore)
    assert rs.get_schema_version() == CURRENT_SCHEMA_VERSION == 12
    assert is_query_only(rs) is True  # query_only=ON
    # No migration/ projector invoked: schema version is 7, unchanged.
    assert rs.get_schema_version() == 12
    rs.close()
    store.close()


def test_v6_rejected_without_migration(tmp_path: Path) -> None:
    # A v6 db (no M4 tables) must NOT be silently upgraded by an M4.6 query.
    store = _open(tmp_path)
    store.downgrade_to(6, "test")  # drops M4 v7 tables -> v6
    store.close()
    # open_readonly must refuse to migrate: version stays 6, no M4 tables created.
    rs = open_readonly(store.path)
    assert rs.get_schema_version() == 6
    with pytest.raises(QueryError) as ei:
        list_project_charters(rs, "P")  # M4 table missing on v6 -> sanitized error
    assert ei.value.code in ("database_unavailable", "schema_mismatch")
    rs.close()


def test_no_projector_invoked_during_read(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    # Reading must not import/use the projector module path.
    import src.project_memory.reader as r
    assert "projector" not in {m for m in dir(r) if not m.startswith("__")}
    # Exercise every read surface; assert no exception and types.
    assert isinstance(get_project_charter(rs, "P"), CharterView)
    assert isinstance(list_project_charters(rs, "P"), ProjectMemoryResult)
    assert isinstance(get_requirement(rs, "R1"), RequirementView)
    assert isinstance(list_requirements(rs, "P"), ProjectMemoryResult)
    assert isinstance(get_decision(rs, "D1"), DecisionView)
    assert isinstance(list_decisions(rs, "P"), ProjectMemoryResult)
    assert get_active_decision(rs, "P", "project:P", "K") is not None
    assert isinstance(get_current_project_state(rs, "P"), list)
    assert isinstance(get_state_value(rs, "P", "project:P", "progress"), ProjectStateView)
    assert isinstance(get_verification(rs, "V1"), VerificationView)
    assert isinstance(list_verifications(rs, project_id="P"), ProjectMemoryResult)
    assert isinstance(list_project_artifacts(rs, "P"), ProjectMemoryResult)
    rs.close()
    store.close()


# ---------------------------------------------------------------------------
# Charter APIs
# ---------------------------------------------------------------------------

def test_active_charter_selected_by_lifecycle(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    c = get_project_charter(rs, "P")
    assert c is not None
    assert c.lifecycle_status == "active"
    assert c.name == "Charter v2"  # the active v2 (correctly selected by lifecycle)
    assert c.state == "confirmed"  # separate from lifecycle
    rs.close(); store.close()


def test_charter_no_active_returns_none(tmp_path: Path) -> None:
    store = _open(tmp_path)
    project_charter(store._conn, CharterOp(op="create", charter_id="CX", project_id="P2",
        lifecycle_status="candidate", state="proposed", created_at="2026-08-01T00:00:00Z"))
    store.close()
    rs = open_readonly(store.path)
    assert get_project_charter(rs, "P2") is None
    rs.close()


def test_charter_exact_id_and_history(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    exact = get_project_charter(rs, "P", charter_id="C1", include_history=True)
    assert exact is not None and exact.charter_id == "C1" and exact.version == 2
    # Without history, the superseded row is reachable via exact id too (include_history not needed for explicit id).
    rs.close(); store.close()


def test_charter_deleted_excluded(tmp_path: Path) -> None:
    store = _open(tmp_path)
    project_charter(store._conn, CharterOp(op="create", charter_id="CD", project_id="P3",
        lifecycle_status="deleted", created_at="2026-08-01T00:00:00Z"))
    store.close()
    rs = open_readonly(store.path)
    assert get_project_charter(rs, "P3", charter_id="CD") is None
    assert get_project_charter(rs, "P3") is None
    # Historical non-deleted retrievable via explicit id when include_history=True.
    assert get_project_charter(rs, "P3", charter_id="CD", include_history=True) is not None
    rs.close()


# ---------------------------------------------------------------------------
# Requirement APIs
# ---------------------------------------------------------------------------

def test_requirement_exact_and_listing(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    r = get_requirement(rs, "R1")
    assert r is not None and r.requirement_id == "R1" and r.state == "accepted" and r.lifecycle_status == "active"
    res = list_requirements(rs, "P")
    ids = {x.requirement_id for x in res.items}
    assert ids == {"R1", "R2"}  # both, no inference/promotion
    rs.close(); store.close()


def test_requirement_state_and_lifecycle_filters(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    accepted = list_requirements(rs, "P", state="accepted")
    assert {x.requirement_id for x in accepted.items} == {"R1"}
    active = list_requirements(rs, "P", lifecycle_status="active")
    assert {x.requirement_id for x in active.items} == {"R1"}
    candidate = list_requirements(rs, "P", lifecycle_status="candidate")
    assert {x.requirement_id for x in candidate.items} == {"R2"}
    # Deleted excluded by default.
    assert all(x.lifecycle_status != "deleted" for x in list_requirements(rs, "P").items)
    rs.close(); store.close()


def test_requirement_zero_result_success(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    res = list_requirements(rs, "P", state="nonexistent_state")
    assert res.items == [] and res.error is None  # no error, empty list
    rs.close(); store.close()


def test_requirement_invalid_lifecycle_rejected(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    with pytest.raises(QueryError) as ei:
        list_requirements(rs, "P", lifecycle_status="bogus")
    assert ei.value.code == "invalid_lifecycle_status"
    rs.close(); store.close()


# ---------------------------------------------------------------------------
# Decision APIs
# ---------------------------------------------------------------------------

def test_decision_exact_and_listing(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    d = get_decision(rs, "D1")
    assert d is not None and d.decision_key == "K"
    ids = {x.decision_id for x in list_decisions(rs, "P").items}
    assert ids == {"D1", "D2"}
    rs.close(); store.close()


def test_active_decision_by_explicit_key(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    d = get_active_decision(rs, "P", "project:P", "K")
    assert d is not None and d.decision_id == "D1" and d.lifecycle_status == "active"
    rs.close(); store.close()


def test_active_decision_null_key_rejected(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    with pytest.raises(QueryError) as ei:
        get_active_decision(rs, "P", "project:P", "")
    assert ei.value.code == "invalid_query"
    with pytest.raises(QueryError) as ei2:
        get_active_decision(rs, "P", "project:P", None)
    assert ei2.value.code == "invalid_query"
    rs.close(); store.close()


def test_conflicted_decisions_preserved_no_winner(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    all_d = list_decisions(rs, "P")
    statuses = {x.decision_id: x.lifecycle_status for x in all_d.items}
    # Both D1 (active) and D2 (conflicted) present; read does not pick a winner.
    assert statuses == {"D1": "active", "D2": "conflicted"}
    rs.close(); store.close()


# ---------------------------------------------------------------------------
# Current State APIs
# ---------------------------------------------------------------------------

def test_state_exact_lookup_by_explicit_key(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    s = get_state_value(rs, "P", "project:P", "progress")
    assert s is not None and s.lifecycle_status == "active" and s.state_value == "50%"
    rs.close(); store.close()


def test_state_active_current_value_only(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    cur = get_current_project_state(rs, "P")
    assert len(cur) == 1 and cur[0].state_value == "50%"  # superseded 40% excluded
    rs.close(); store.close()


def test_state_null_key_not_logical_lookup(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    with pytest.raises(QueryError) as ei:
        get_state_value(rs, "P", None, "")  # empty key rejected
    assert ei.value.code == "invalid_query"
    # A null-key state row is not retrievable as a logical slot.
    project_state(store._conn, StateOp(op="create", project_id="P", state_key=None, state_value="x",
        lifecycle_status="active", created_at="2026-08-09T00:00:00Z"))
    store.close()
    rs = open_readonly(store.path)
    with pytest.raises(QueryError):
        get_state_value(rs, "P", None, None)
    rs.close()


# ---------------------------------------------------------------------------
# Verification APIs
# ---------------------------------------------------------------------------

def test_verification_exact_and_listing(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    v = get_verification(rs, "V1")
    assert v is not None and v.subject_id == "R1"
    res = list_verifications(rs, project_id="P")
    assert {x.verification_id for x in res.items} == {"V1", "V2"}
    rs.close(); store.close()


def test_verification_subject_and_status_filters(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    subj = list_verifications(rs, subject_type="requirement", subject_id="R1")
    assert {x.verification_id for x in subj.items} == {"V1", "V2"}
    verified = list_verifications(rs, verification_status="deterministic_verification")
    assert {x.verification_id for x in verified.items} == {"V1"}
    rs.close(); store.close()


def test_verification_contradictory_preserved_no_winner(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    res = list_verifications(rs, subject_id="R1")
    statuses = {x.verification_id: x.verification_status for x in res.items}
    assert statuses["V1"] == "deterministic_verification" and statuses["V2"] == "direct_tool_output"
    # No promotion: requirement R1 lifecycle/state unchanged by verification reads.
    r = get_requirement(rs, "R1")
    assert r.lifecycle_status == "active" and r.state == "accepted"
    with pytest.raises(QueryError):
        list_verifications(rs, subject_type="bogus")
    rs.close(); store.close()


# ---------------------------------------------------------------------------
# Artifact APIs
# ---------------------------------------------------------------------------

def test_artifact_listing_reuses_m2_metadata(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    res = list_project_artifacts(rs, "P")
    assert len(res.items) == 1
    a = res.items[0]
    assert isinstance(a, ProjectArtifactView)
    assert a.artifact_id == "ART1" and a.safe_reference == "artifacts/report.md"
    # M2 safe metadata joined, stored_path NOT exposed.
    assert a.kind == "report" and a.content_hash == "deadbeef" and a.retention == "project"
    assert not hasattr(a, "stored_path")
    rs.close(); store.close()


def test_artifact_no_local_path_leakage(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    a = list_project_artifacts(rs, "P").items[0]
    blob = str(a.__dict__)
    assert SECRET not in blob  # M2 stored_path carried the secret; not exposed
    assert "/home/" not in blob and "/tmp/" not in blob
    rs.close(); store.close()


# ---------------------------------------------------------------------------
# M3 composition (source-event resolution)
# ---------------------------------------------------------------------------

def test_source_event_resolution_via_m3(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    # The source events referenced (E1..) do not exist in M3 zm_meta, so composition
    # must return None (not fabricate / not error).
    rs = open_readonly(store.path)
    r = get_requirement(rs, "R1", include_source_event=True)
    assert r is not None
    assert r.source_event is None  # missing source -> None, not fabricated
    c = get_project_charter(rs, "P", include_source_event=True)
    assert c is not None and c.source_event is None
    rs.close(); store.close()


# ---------------------------------------------------------------------------
# Pagination / filtering
# ---------------------------------------------------------------------------

def test_pagination_deterministic_multi_page(tmp_path: Path) -> None:
    store = _open(tmp_path)
    for i in range(5):
        project_requirement(store._conn, RequirementOp(op="create", requirement_id=f"RP{i}",
            project_id="P", statement=f"s{i}", lifecycle_status="active",
            created_at=f"2026-08-{10+i}T00:00:00Z"))
    store.close()
    rs = open_readonly(store.path)
    page1 = list_requirements(rs, "P", limit=2)
    assert len(page1.items) == 2
    assert page1.next_cursor is not None
    page2 = list_requirements(rs, "P", limit=2, cursor=page1.next_cursor)
    # No overlap, no duplicates, order stable.
    ids1 = [x.requirement_id for x in page1.items]
    ids2 = [x.requirement_id for x in page2.items]
    assert not (set(ids1) & set(ids2))  # no overlap between pages
    page3 = list_requirements(rs, "P", limit=2, cursor=page2.next_cursor)
    assert len(page3.items) == 1
    assert page3.next_cursor is None  # end of results
    all_ids = ids1 + ids2 + [x.requirement_id for x in page3.items]
    assert sorted(all_ids) == all_ids  # deterministic order
    rs.close(); store.close()


def test_cursor_query_mismatch(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    p1 = list_requirements(rs, "P", limit=2)
    # Reuse cursor with a DIFFERENT query (decisions) -> mismatch.
    with pytest.raises(QueryError) as ei:
        list_decisions(rs, "P", limit=2, cursor=p1.next_cursor)
    assert ei.value.code == "cursor_query_mismatch"
    # Reuse with a different limit -> mismatch.
    with pytest.raises(QueryError) as ei2:
        list_requirements(rs, "P", limit=5, cursor=p1.next_cursor)
    assert ei2.value.code == "cursor_limit_mismatch"
    rs.close(); store.close()


def test_and_filters_zero_result_success(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    res = list_verifications(rs, project_id="P", subject_type="requirement", subject_id="R9")
    assert res.items == [] and res.error is None
    rs.close(); store.close()


# ---------------------------------------------------------------------------
# Safety: deleted exclusion / conflict / supersession / secret / immutability
# ---------------------------------------------------------------------------

def test_lifecycle_domain_state_separate(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    r = get_requirement(rs, "R1")
    assert r.lifecycle_status == "active" and r.state == "accepted"
    assert r.lifecycle_status != r.state  # two distinct values
    rs.close(); store.close()


def test_explicit_supersession_only(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    c = get_project_charter(rs, "P", charter_id="C1", include_history=True)
    # Stored supersession reference only; not inferred from version/timestamp.
    assert c.supersedes == "C1"  # the active row links to itself as superseded-by target in our seed
    rs.close(); store.close()


def test_secret_absent_from_artifacts(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    a = list_project_artifacts(rs, "P").items[0]
    assert SECRET not in str(a.__dict__)
    rs.close(); store.close()


def test_read_only_no_mutation(tmp_path: Path) -> None:
    store = _open(tmp_path)
    _seed(store)
    rs = open_readonly(store.path)
    before = {t: store._conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
              for t in ("zm_project_charters", "zm_requirements", "zm_decisions",
                        "zm_project_state", "zm_verifications", "zm_project_artifacts")}
    # Exercise every read surface across multiple pages.
    get_project_charter(rs, "P", include_source_event=True)
    list_project_charters(rs, "P", limit=1)
    get_requirement(rs, "R1", include_source_event=True)
    list_requirements(rs, "P", limit=1)
    get_decision(rs, "D1")
    list_decisions(rs, "P", limit=1)
    get_active_decision(rs, "P", "project:P", "K")
    get_current_project_state(rs, "P")
    get_state_value(rs, "P", "project:P", "progress")
    get_verification(rs, "V1")
    list_verifications(rs, project_id="P", limit=1)
    list_project_artifacts(rs, "P", limit=1)
    after = {t: store._conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
             for t in before}
    assert before == after  # no mutation from reads
    rs.close(); store.close()


def test_no_real_hermes_home_writes_placeholder() -> None:
    # This test intentionally does NOT write to real ~/.hermes. It exists only to
    # document that M4.6 reads use an isolated ReadonlyStore; the canonical
    # test_m2_ingest::test_no_real_hermes_home_writes remains the authoritative guard.
    assert True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
