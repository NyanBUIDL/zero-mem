"""M3.5 — Verification / lifecycle-aware retrieval: deterministic, sanitized, TRUE READ-ONLY.

Covers the M3.5 acceptance criteria from the approved M3 plan:
- exact verification-status filter
- exact lifecycle-status filter
- claim-not-fact (assistant_claim never promoted)
- provenance enrichment (read-only)
- administrative deleted-inspection passthrough (list_deleted / get_tombstone / get_deletion_audit)
- FTS composition with verification/lifecycle filters
- deterministic ordering, pagination with filters, cursor query binding
- true read-only proof (sqlite_master / counts / meta / JSONL unchanged)
- secret safety, no LLM / no network, no real ~/.hermes writes, no ranking, no M3.6/M4 behavior.

Status vocabularies are taken VERBATIM from the verified M1 contract
(src/capture/event_types.py): VerificationStatus = none / direct_tool_output /
user_confirmation / deterministic_verification / approval; LifecycleStatus = raw /
observed / candidate / confirmed / active / superseded / conflicted / archived /
deleted. No invented statuses.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

import pytest

import src.retrieval as r
from src.retrieval.models import QueryError

# Reuse the proven WAL-safe fixtures from the M3.1 suite.
from tests.unit.test_m3_query import (  # noqa: E402
    _make_env,
    _write_jsonl,
    _open_store,
    _checkpoint_and_close,
    Snapshot,
)
from src.storage.ingest import ingest_file  # noqa: E402


# Real verification / lifecycle vocabulary from the verified M1 contract.
V_DETERMINISTIC = "deterministic_verification"
V_USER_CONF = "user_confirmation"
V_NONE = "none"
V_DIRECT = "direct_tool_output"
V_APPROVAL = "approval"

L_ACTIVE = "active"
L_CANDIDATE = "candidate"
L_OBSERVED = "observed"
L_CONFIRMED = "confirmed"
L_CONFLICTED = "conflicted"
L_SUPERSEDED = "superseded"
L_ARCHIVED = "archived"
L_DELETED = "deleted"
L_RAW = "raw"


SECRET = "SK-M3.5-secret-credential-xyz"


def _env(eid, text, **kw):
    """Build an envelope using the verified default statuses unless overridden."""
    return _make_env(eid, sanitized_content={"text": text}, **kw)


def _ingest_verification_corpus(tmp_path: Path):
    """Ingest a representative corpus with varied verification/lifecycle/event_type.

    Uses the verified vocabulary only. Returns (jsonl_path, readonly_store).
    """
    items = [
        # verified_state, deterministic_verification, active
        _env("p0", f"parent decision alpha {SECRET}",
             project_id="P", profile_id="U", knowledge_space_id="KS", session_id="s1",
             verification_status=V_DETERMINISTIC, lifecycle_status=L_ACTIVE,
             event_type="verified_state", confidence="high"),
        # assistant_claim, unverified (none), candidate
        _env("c1", "child claim beta",
             parent_trace_id="tr-p0", project_id="P", session_id="s1",
             verification_status=V_NONE, lifecycle_status=L_CANDIDATE,
             event_type="assistant_claim", confidence="medium"),
        # tool_observation, user_confirmation, observed
        _env("o1", "tool observed gamma",
             project_id="P", session_id="s1",
             verification_status=V_USER_CONF, lifecycle_status=L_OBSERVED,
             event_type="tool_observation", confidence="medium"),
        # user_statement, user_confirmation, confirmed
        _env("u1", "user statement delta",
             project_id="P", session_id="s1",
             verification_status=V_USER_CONF, lifecycle_status=L_CONFIRMED,
             event_type="user_statement", confidence="high"),
        # inference, unverified (none), conflicted
        _env("x1", "conflicted record epsilon",
             project_id="P", session_id="s1",
             verification_status=V_NONE, lifecycle_status=L_CONFLICTED,
             event_type="inference", confidence="low"),
        # decision, deterministic_verification, superseded
        _env("sup1", "superseded old zeta",
             project_id="P", session_id="s1",
             verification_status=V_DETERMINISTIC, lifecycle_status=L_SUPERSEDED,
             event_type="decision", confidence="medium"),
        # decision, deterministic_verification, archived
        _env("arc1", "archived record eta",
             project_id="P", session_id="s1",
             verification_status=V_DETERMINISTIC, lifecycle_status=L_ARCHIVED,
             event_type="decision", confidence="medium"),
        # raw lifecycle
        _env("raw1", "raw observation iota",
             project_id="P", session_id="s1",
             verification_status=V_NONE, lifecycle_status=L_RAW,
             event_type="tool_observation", confidence="low"),
        # project Q (to test scope isolation)
        _env("q1", "other project kappa",
             project_id="Q", session_id="s1",
             verification_status=V_DETERMINISTIC, lifecycle_status=L_ACTIVE,
             event_type="decision", confidence="high"),
        # candidate event used only as a deletion target (keeps c1/others visible)
        _env("v1", "victim to be deleted",
             project_id="P", session_id="s1",
             verification_status=V_DETERMINISTIC, lifecycle_status=L_ACTIVE,
             event_type="verified_state", confidence="high"),
        # deleted target via a proper M2.6 deletion event (deletion block projects tombstone + audit)
        _env("del1", "delete v1", event_type="system_event", lifecycle_status=L_DELETED,
             trace_id="tr-del1", project_id="P", session_id="s1",
             deletion={"target_event_id": "v1"}),
    ]
    jl = tmp_path / "c.jsonl"
    _write_jsonl(jl, items)
    store = _open_store(tmp_path, "m.sqlite")
    ingest_file(store, jl)
    store._conn.commit()
    _checkpoint_and_close(store)
    rs = r.open_readonly(tmp_path / "m.sqlite")
    return jl, rs


def _p_ids(res):
    return [e.event_id for e in res.items]


# ---- exact verification-status filter ------------------------------------
def test_filter_verification_deterministic(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.query_events(rs, r.QueryRequest(project_id="P", verification_status=V_DETERMINISTIC))
    assert sorted(_p_ids(res)) == ["arc1", "p0", "sup1"]


def test_filter_verification_user_confirmation(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.query_events(rs, r.QueryRequest(project_id="P", verification_status=V_USER_CONF))
    assert sorted(_p_ids(res)) == ["o1", "u1"]


def test_filter_verification_none(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.query_events(rs, r.QueryRequest(project_id="P", verification_status=V_NONE))
    assert sorted(_p_ids(res)) == ["c1", "raw1", "x1"]


def test_verified_only_preset_is_exact_filter(tmp_path):
    """'verified_only' means deterministic_verification (the verified state), exact."""
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.query_events(rs, r.QueryRequest(project_id="P", verification_status=V_DETERMINISTIC))
    assert "c1" not in _p_ids(res)  # unverified assistant_claim excluded


# ---- exact lifecycle-status filter ---------------------------------------
def test_filter_lifecycle_active(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.query_events(rs, r.QueryRequest(project_id="P", lifecycle_status=L_ACTIVE))
    assert _p_ids(res) == ["p0"]


def test_filter_lifecycle_confirmed(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.query_events(rs, r.QueryRequest(project_id="P", lifecycle_status=L_CONFIRMED))
    assert _p_ids(res) == ["u1"]


def test_filter_lifecycle_candidate(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.query_events(rs, r.QueryRequest(project_id="P", lifecycle_status=L_CANDIDATE))
    assert _p_ids(res) == ["c1"]


def test_filter_lifecycle_observed(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.query_events(rs, r.QueryRequest(project_id="P", lifecycle_status=L_OBSERVED))
    assert _p_ids(res) == ["o1"]


def test_filter_lifecycle_raw(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.query_events(rs, r.QueryRequest(project_id="P", lifecycle_status=L_RAW))
    assert _p_ids(res) == ["raw1"]


def test_filter_lifecycle_superseded(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.query_events(rs, r.QueryRequest(project_id="P", lifecycle_status=L_SUPERSEDED))
    assert _p_ids(res) == ["sup1"]


def test_filter_lifecycle_conflicted(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.query_events(rs, r.QueryRequest(project_id="P", lifecycle_status=L_CONFLICTED))
    assert _p_ids(res) == ["x1"]


def test_filter_lifecycle_archived(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.query_events(rs, r.QueryRequest(project_id="P", lifecycle_status=L_ARCHIVED))
    assert _p_ids(res) == ["arc1"]


def test_archived_superseded_included_by_default(tmp_path):
    """Archived / superseded / conflicted are NOT auto-hidden unless filtered out."""
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.query_events(rs, r.QueryRequest(project_id="P"))
    ids = _p_ids(res)
    for must in ["arc1", "sup1", "x1"]:
        assert must in ids, (must, ids)
    assert "del1" not in ids


# ---- deleted excluded -----------------------------------------------------
def test_deleted_excluded_by_default(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.query_events(rs, r.QueryRequest(project_id="P"))
    assert "del1" not in _p_ids(res)
    res_all = r.query_events(rs, r.QueryRequest())
    assert "del1" not in _p_ids(res_all)


# ---- invalid status values ------------------------------------------------
def test_invalid_verification_status(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    for bad in ["unverified", "verified", "rejected", "pending", "bogus", "true"]:
        with pytest.raises(QueryError) as ei:
            r.query_events(rs, r.QueryRequest(verification_status=bad))
        assert ei.value.code == "invalid_verification_status", bad


def test_invalid_lifecycle_status(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    for bad in ["mystery", "removed", "expired", "activex"]:
        with pytest.raises(QueryError) as ei:
            r.query_events(rs, r.QueryRequest(lifecycle_status=bad))
        assert ei.value.code == "invalid_lifecycle_status", bad


def test_lifecycle_deleted_rejected_on_normal_path(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    with pytest.raises(QueryError) as ei:
        r.query_events(rs, r.QueryRequest(lifecycle_status=L_DELETED))
    assert ei.value.code == "unsupported_filter"


# ---- combined structured filters (AND semantics) --------------------------
def test_project_plus_verification_filter(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.query_events(rs, r.QueryRequest(project_id="P", verification_status=V_DETERMINISTIC))
    assert sorted(_p_ids(res)) == ["arc1", "p0", "sup1"]


def test_profile_plus_lifecycle_filter(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.query_events(rs, r.QueryRequest(profile_id="U", lifecycle_status=L_ACTIVE))
    assert _p_ids(res) == ["p0"]


def test_event_type_plus_verification_filter(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.query_events(rs, r.QueryRequest(project_id="P", event_type="assistant_claim",
                                            verification_status=V_NONE))
    assert _p_ids(res) == ["c1"]


# ---- claim-not-fact -------------------------------------------------------
def test_assistant_claim_remains_assistant_claim(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    ev = r.get_event(rs, "c1")
    assert ev.event_type == "assistant_claim"
    assert ev.verification_status == V_NONE
    assert "verified_state" != ev.event_type


def test_unverified_assistant_claim_not_promoted(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.query_events(rs, r.QueryRequest(project_id="P", event_type="assistant_claim",
                                            verification_status=V_DETERMINISTIC))
    # An unverified assistant_claim must NOT appear in a verified-only query.
    assert "c1" not in _p_ids(res)


def test_tool_observation_distinct(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    ev = r.get_event(rs, "o1")
    assert ev.event_type == "tool_observation"
    assert ev.verification_status == V_USER_CONF


def test_inference_distinct(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    ev = r.get_event(rs, "x1")
    assert ev.event_type == "inference"
    assert ev.lifecycle_status == L_CONFLICTED


def test_verified_state_distinct(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    ev = r.get_event(rs, "p0")
    assert ev.event_type == "verified_state"
    assert ev.verification_status == V_DETERMINISTIC


# ---- provenance enrichment ------------------------------------------------
def test_provenance_fields_preserved(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    prov = r.get_provenance(rs, "p0")
    assert prov is not None
    assert prov.event_id == "p0"
    assert prov.verification_status == V_DETERMINISTIC
    assert prov.verifier is not None
    # evidence_ref present (trace_id) and recorded_at is an ISO timestamp
    assert prov.evidence_ref == "tr-p0"
    assert prov.recorded_at.endswith("Z") or "T" in prov.recorded_at


def test_provenance_missing_returns_none(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    # 'c1' is a child; provenance may still exist, but ensure get_provenance never raises
    prov = r.get_provenance(rs, "does-not-exist")
    assert prov is None


# ---- stored confidence not recomputed ------------------------------------
def test_confidence_returned_as_stored(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    ev = r.get_event(rs, "p0")
    assert ev.confidence == "high"  # stored verbatim, never reinterpreted
    ev_low = r.get_event(rs, "x1")
    assert ev_low.confidence == "low"


# ---- conflict / supersession read-only behavior ---------------------------
def test_conflict_does_not_choose_winner(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.query_events(rs, r.QueryRequest(project_id="P", lifecycle_status=L_CONFLICTED))
    assert _p_ids(res) == ["x1"]
    ev = r.get_event(rs, "x1")
    assert ev.lifecycle_status == L_CONFLICTED  # conflict preserved, not resolved


def test_superseded_does_not_invent_replacement(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    # The superseded event is returned verbatim; no active replacement is invented.
    res = r.query_events(rs, r.QueryRequest(project_id="P", lifecycle_status=L_SUPERSEDED))
    assert _p_ids(res) == ["sup1"]
    ev = r.get_event(rs, "sup1")
    assert ev.lifecycle_status == L_SUPERSEDED


# ---- administrative deleted-inspection passthrough ------------------------
def test_list_deleted_admin_path(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    # The deleted TARGET is 'v1' (del1 is the deletion event projecting the tombstone).
    deleted = r.list_deleted(rs, scope_type="project_id", scope_id="P")
    assert "v1" in deleted
    # Normal retrieval must still exclude the deleted target.
    assert "v1" not in _p_ids(r.query_events(rs, r.QueryRequest(project_id="P")))


def test_get_tombstone_admin_path(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    # del1 is the deletion event; its tombstone_id equals the deletion event id.
    audit = r.get_deletion_audit(rs, target_event_id="v1")
    assert audit, "expected a deletion-audit row for v1"
    tombstone_id = audit[0]["tombstone_id"]
    assert tombstone_id == "del1"
    ts = r.get_tombstone(rs, tombstone_id)
    assert ts is not None
    assert ts["target_event_id"] == "v1"


def test_get_deletion_audit_admin_path(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    audit = r.get_deletion_audit(rs, target_event_id="v1")
    assert isinstance(audit, list)
    assert audit, "expected a deletion-audit row for v1"
    assert audit[0]["target_event_id"] == "v1"
    assert audit[0]["action"] == "logical_delete"


# ---- FTS composition ------------------------------------------------------
def test_fts_plus_verification_filter(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    # FTS matches content text only; "decision" appears in p0's content ("parent decision alpha").
    res = r.search_filtered(rs, "decision", verification_status=V_DETERMINISTIC)
    assert sorted(h.event_id for h in res.results) == ["p0"]


def test_fts_plus_lifecycle_filter(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.search_filtered(rs, "record", lifecycle_status=L_ARCHIVED)
    assert [h.event_id for h in res.results] == ["arc1"]


def test_fts_plus_verification_excludes_unverified(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.search_filtered(rs, "claim", verification_status=V_DETERMINISTIC)
    # 'child claim beta' (c1) is unverified -> excluded under verified filter
    assert "c1" not in [h.event_id for h in res.results]


def test_fts_composition_invalid_verification_status(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    with pytest.raises(QueryError) as ei:
        r.search_filtered(rs, "decision", verification_status="verified")
    assert ei.value.code == "invalid_verification_status"


# ---- relation result preserves lifecycle / verification metadata ----------
def test_relation_result_preserves_metadata(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    rel = r.get_related(rs, "p0")  # p0 -> c1 (child_of edge)
    # c1 must remain an unverified assistant_claim in the relation target view
    assert rel.items[0].target.event_type == "assistant_claim"
    assert rel.items[0].target.verification_status == V_NONE
    assert rel.items[0].target.lifecycle_status == L_CANDIDATE


# ---- deterministic ordering ----------------------------------------------
def test_deterministic_ordering(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.query_events(rs, r.QueryRequest(project_id="P"))
    ids = _p_ids(res)
    # ordering is (created_at ASC, event_id ASC) — all same TS here -> event_id lexicographic
    assert ids == sorted(ids)
    assert ids == ["arc1", "c1", "o1", "p0", "raw1", "sup1", "u1", "x1"]


def test_ordering_unchanged_by_verification_filter(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    base = _p_ids(r.query_events(rs, r.QueryRequest(project_id="P")))
    filt = _p_ids(r.query_events(rs, r.QueryRequest(project_id="P", verification_status=V_DETERMINISTIC)))
    # filtered subset preserves base order
    assert filt == [e for e in base if e in filt]


# ---- pagination with filters ---------------------------------------------
def test_pagination_with_verification_filter(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    p1 = r.query_events(rs, r.QueryRequest(project_id="P", verification_status=V_DETERMINISTIC), limit=2)
    assert len(p1.items) == 2
    assert p1.next_cursor is not None
    p2 = r.query_events(rs, r.QueryRequest(project_id="P", verification_status=V_DETERMINISTIC),
                        limit=2, cursor=p1.next_cursor)
    all_ids = _p_ids(p1) + _p_ids(p2)
    assert sorted(all_ids) == ["arc1", "p0", "sup1"]
    assert len(set(all_ids)) == len(all_ids)  # no duplicates


def test_pagination_with_lifecycle_filter(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.query_events(rs, r.QueryRequest(project_id="P", lifecycle_status=L_ACTIVE), limit=10)
    assert _p_ids(res) == ["p0"]


# ---- cursor query binding ------------------------------------------------
def test_cursor_query_binding_verification(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    cur = r.query_events(rs, r.QueryRequest(project_id="P", verification_status=V_DETERMINISTIC), limit=1).next_cursor
    # reuse with a different verification status -> rejected
    with pytest.raises(QueryError) as ei:
        r.query_events(rs, r.QueryRequest(project_id="P", verification_status=V_NONE),
                       limit=1, cursor=cur)
    assert ei.value.code == "cursor_query_mismatch"


def test_cursor_query_binding_lifecycle(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    cur = r.query_events(rs, r.QueryRequest(project_id="P", lifecycle_status=L_ACTIVE), limit=1).next_cursor
    with pytest.raises(QueryError) as ei:
        r.query_events(rs, r.QueryRequest(project_id="P", lifecycle_status=L_ARCHIVED),
                       limit=1, cursor=cur)
    assert ei.value.code == "cursor_query_mismatch"


# ---- zero-result success --------------------------------------------------
def test_zero_result_success(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    res = r.query_events(rs, r.QueryRequest(project_id="P", verification_status=V_APPROVAL))
    assert res.items == []
    assert res.next_cursor is None
    # serialization sanity
    json.dumps(asdict(res))


# ---- sanitized errors -----------------------------------------------------
def test_invalid_verification_status_error_code(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    with pytest.raises(QueryError) as ei:
        r.query_events(rs, r.QueryRequest(verification_status="not_a_real_status"))
    assert ei.value.code == "invalid_verification_status"
    assert "raw" not in str(ei.value).lower() or "sqlite" not in str(ei.value).lower()


# ---- secret safety --------------------------------------------------------
def test_secret_absent_from_query_results(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    blob = json.dumps(asdict(r.query_events(rs, r.QueryRequest(project_id="P"))))
    assert SECRET not in blob


def test_secret_absent_from_provenance(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    prov = r.get_provenance(rs, "p0")
    blob = json.dumps(prov.__dict__)
    assert SECRET not in blob


def test_secret_absent_from_cursor(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    cur = r.query_events(rs, r.QueryRequest(project_id="P", verification_status=V_DETERMINISTIC), limit=2).next_cursor
    assert SECRET not in cur


# ---- TRUE READ-ONLY proof -------------------------------------------------
def test_sqlite_unchanged_after_verification_queries(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    snap1 = Snapshot(rs, jl)
    # exercise the full M3.5 surface
    r.query_events(rs, r.QueryRequest(project_id="P", verification_status=V_DETERMINISTIC))
    r.query_events(rs, r.QueryRequest(project_id="P", lifecycle_status=L_ARCHIVED))
    r.query_events(rs, r.QueryRequest(project_id="P"))
    r.get_event(rs, "c1")
    r.get_provenance(rs, "p0")
    r.list_deleted(rs, scope_type="project_id", scope_id="P")
    r.search_filtered(rs, "decision", verification_status=V_DETERMINISTIC)
    r.get_related(rs, "p0")
    snap2 = Snapshot(rs, jl)
    snap1.assert_unchanged(snap2)


def test_lifecycle_tables_unchanged(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    snap1 = Snapshot(rs, jl)
    r.query_events(rs, r.QueryRequest(project_id="P", lifecycle_status=L_CONFLICTED))
    r.query_events(rs, r.QueryRequest(project_id="P", verification_status=V_NONE))
    snap2 = Snapshot(rs, jl)
    assert snap1.counts["zm_lifecycle"] == snap2.counts["zm_lifecycle"]
    assert snap1.counts["zm_provenance"] == snap2.counts["zm_provenance"]


def test_jsonl_unchanged(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    sha1 = Snapshot(rs, jl).jsonl_sha
    r.query_events(rs, r.QueryRequest(project_id="P"))
    sha2 = Snapshot(rs, jl).jsonl_sha
    assert sha1 == sha2


# ---- no real ~/.hermes writes --------------------------------------------
def test_no_real_hermes_home_writes_during_verification(tmp_path, monkeypatch):
    real_home = Path.home() / ".hermes"
    touched = {}
    orig_touch = Path.touch

    def fake_touch(self, *a, **k):
        if "hermes" in str(self) and "Zero-mem" not in str(self):
            touched[str(self)] = True
        return orig_touch(self, *a, **k)

    monkeypatch.setattr(Path, "touch", fake_touch)
    jl, rs = _ingest_verification_corpus(tmp_path)
    r.query_events(rs, r.QueryRequest(project_id="P", verification_status=V_DETERMINISTIC))
    r.get_provenance(rs, "p0")
    assert touched == {}, f"unexpected real ~/.hermes write: {touched}"


# ---- no ranking / no M3.6 / no M4 ---------------------------------------
def test_no_ranking_by_verification(tmp_path):
    """Verified and unverified results are returned in the same stable order (no promotion)."""
    jl, rs = _ingest_verification_corpus(tmp_path)
    ids = _p_ids(r.query_events(rs, r.QueryRequest(project_id="P")))
    # relative order of a verified (p0) vs unverified (c1) follows event_id, not verification
    assert ids.index("c1") < ids.index("p0")


def test_no_m3_6_behavior(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    # No integration/final-acceptance helpers exist in M3.5; assert query layer stays scoped.
    assert hasattr(r, "query_events")
    assert not hasattr(r, "final_acceptance_run")
    assert not hasattr(r, "project_memory_write")


def test_no_m4_behavior(tmp_path):
    jl, rs = _ingest_verification_corpus(tmp_path)
    # M4 is query routing; M3.5 must not include routing decisions.
    assert not hasattr(r, "route_query")
    res = r.query_events(rs, r.QueryRequest(project_id="P"))
    for e in res.items:
        assert not hasattr(e, "route")
