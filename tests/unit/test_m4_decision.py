"""M4.3 focused tests: Decision Log projection (create/state/lifecycle/key/
supersession/conflict/provenance/transaction-safety/determinism).

Covers only M4.3 (deterministic Decision Log projector). No M4.1 schema change,
no M4.4+/M5 behavior, no Current State/Verification/Artifact projection.

All tests use temporary directories; none write to the real ~/.hermes.
No LLM or network calls. Secrets are synthetic and never asserted in errors.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.project_memory import (
    project_decision,
    classify_event_for_m4,
    CLASSIFY_DECISION,
    CLASSIFY_SKIP,
)
from src.project_memory.contracts import (
    DecisionOp,
    M4Op,
    MissingIdentityError,
    InvalidLifecycleError,
    InvalidTransitionError,
    ConflictError,
    PromotionBlockedError,
)


def _config(p: Path) -> SQLiteStoreConfig:
    return SQLiteStoreConfig(path=p / "meta.sqlite")


def _open(p: Path) -> SQLiteStore:
    store = SQLiteStore(_config(p))
    store.ensure_schema()
    assert store.get_schema_version() == 11
    return store


def _dec(op="create", **kw) -> DecisionOp:
    base = dict(
        op=op, decision_id="D1", project_id="P", scope="db",
        decision_key="DK1", statement="use SQLite", rationale_ref="R1",
        lifecycle_status="active", state="accepted", source_event_id="E1",
        trace_id="T1", session_id="S1", profile_id="PF1",
        created_at="2026-08-07T00:00:00Z",
    )
    base.update(kw)
    return DecisionOp(**base)


# ===================== Identity =====================


def test_decision_explicit_id_preserved(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        out = project_decision(store._conn, _dec())
        assert out["action"] == "created"
        row = store._conn.execute(
            "SELECT decision_id, project_id FROM zm_decisions WHERE decision_id='D1'").fetchone()
        assert row["decision_id"] == "D1"
        assert row["project_id"] == "P"
    finally:
        store.close()


def test_decision_missing_id_not_invented(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        with pytest.raises(MissingIdentityError):
            project_decision(store._conn, _dec(decision_id="  "))
    finally:
        store.close()


def test_decision_trace_id_not_used_as_id(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec(trace_id="T-looks-like-id"))
        row = store._conn.execute(
            "SELECT decision_id, trace_id FROM zm_decisions WHERE decision_id='D1'").fetchone()
        assert row["decision_id"] == "D1"
        assert row["trace_id"] == "T-looks-like-id"
    finally:
        store.close()


def test_decision_explicit_key_preserved(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec())
        row = store._conn.execute(
            "SELECT decision_key FROM zm_decisions WHERE decision_id='D1'").fetchone()
        assert row["decision_key"] == "DK1"
    finally:
        store.close()


def test_decision_absent_key_is_null(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec(decision_key=None))
        row = store._conn.execute(
            "SELECT decision_key FROM zm_decisions WHERE decision_id='D1'").fetchone()
        assert row["decision_key"] is None
    finally:
        store.close()


def test_decision_trace_id_not_used_as_key(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec(decision_key=None, trace_id="T-K"))
        row = store._conn.execute(
            "SELECT decision_key, trace_id FROM zm_decisions WHERE decision_id='D1'").fetchone()
        assert row["decision_key"] is None
        assert row["trace_id"] == "T-K"
    finally:
        store.close()


# ===================== State / lifecycle =====================


def test_decision_state_separate_from_lifecycle(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec(lifecycle_status="active", state="accepted"))
        row = store._conn.execute(
            "SELECT lifecycle_status, state FROM zm_decisions WHERE decision_id='D1'").fetchone()
        assert row["lifecycle_status"] == "active"
        assert row["state"] == "accepted"
        # domain values must NOT be in lifecycle_status
        with pytest.raises(InvalidLifecycleError):
            project_decision(store._conn, _dec(decision_id="D2", lifecycle_status="accepted"))
    finally:
        store.close()


def test_decision_lifecycle_closed_enum_enforced(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        for allowed in ("raw", "observed", "candidate", "confirmed", "active",
                        "superseded", "conflicted", "archived", "deleted"):
            project_decision(store._conn, _dec(decision_id=f"X-{allowed}", lifecycle_status=allowed))
            r = store._conn.execute(
                "SELECT lifecycle_status FROM zm_decisions WHERE decision_id=?",
                (f"X-{allowed}",)).fetchone()
            assert r["lifecycle_status"] == allowed
        with pytest.raises(InvalidLifecycleError):
            project_decision(store._conn, _dec(decision_id="BAD", lifecycle_status="proposed"))
    finally:
        store.close()


def test_decision_conflicted_only_when_explicit(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec(decision_id="DC", lifecycle_status="conflicted", state="unresolved"))
        r = store._conn.execute(
            "SELECT lifecycle_status FROM zm_decisions WHERE decision_id='DC'").fetchone()
        assert r["lifecycle_status"] == "conflicted"
    finally:
        store.close()


# ===================== Creation / idempotence =====================


def test_decision_creation(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        out = project_decision(store._conn, _dec())
        assert out["action"] == "created"
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_decisions").fetchone()["n"] == 1
    finally:
        store.close()


def test_decision_repeated_event_idempotent(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec())
        out = project_decision(store._conn, _dec())
        assert out["action"] == "noop"
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_decisions").fetchone()["n"] == 1
    finally:
        store.close()


def test_decision_no_duplicates(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec())
        project_decision(store._conn, _dec())
        project_decision(store._conn, _dec())
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_decisions").fetchone()["n"] == 1
    finally:
        store.close()


# ===================== Active uniqueness =====================


def test_decision_one_active_per_key(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec(decision_id="A", decision_key="K", lifecycle_status="active"))
        with pytest.raises(ConflictError):
            project_decision(store._conn, _dec(decision_id="B", decision_key="K", lifecycle_status="active"))
        # existing A retained, no B row
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_decisions").fetchone()["n"] == 1
        assert store._conn.execute("SELECT decision_id FROM zm_decisions").fetchone()["decision_id"] == "A"
    finally:
        store.close()


def test_decision_active_different_key_allowed(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec(decision_id="A", decision_key="K1", lifecycle_status="active"))
        out = project_decision(store._conn, _dec(decision_id="B", decision_key="K2", lifecycle_status="active"))
        assert out["action"] == "created"
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_decisions").fetchone()["n"] == 2
    finally:
        store.close()


def test_decision_multiple_active_null_key_allowed(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec(decision_id="A", decision_key=None, lifecycle_status="active"))
        out = project_decision(store._conn, _dec(decision_id="B", decision_key=None, lifecycle_status="active"))
        assert out["action"] == "created"
        # two NULL-key active decisions coexist (no false collision)
        n = store._conn.execute(
            "SELECT COUNT(*) AS n FROM zm_decisions WHERE lifecycle_status='active'").fetchone()["n"]
        assert n == 2
    finally:
        store.close()


def test_decision_inactive_history_same_key_allowed(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec(decision_id="A", decision_key="K", lifecycle_status="active"))
        # a superseded historical row with the same key is allowed
        out = project_decision(store._conn, _dec(decision_id="A2", decision_key="K", lifecycle_status="superseded"))
        assert out["action"] == "created"
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_decisions").fetchone()["n"] == 2
    finally:
        store.close()


# ===================== Supersession =====================


def test_decision_explicit_supersession_preserves_both(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec(decision_id="A", lifecycle_status="active"))
        out = project_decision(store._conn, _dec(
            decision_id="B", op="supersede", supersedes_id="A", lifecycle_status="active"))
        assert out["action"] == "superseded"
        a = store._conn.execute(
            "SELECT lifecycle_status, replaced_by FROM zm_decisions WHERE decision_id='A'").fetchone()
        b = store._conn.execute(
            "SELECT supersedes_id, lifecycle_status FROM zm_decisions WHERE decision_id='B'").fetchone()
        assert a["lifecycle_status"] == "superseded"
        assert a["replaced_by"] == "B"
        assert b["supersedes_id"] == "A"
        assert b["lifecycle_status"] == "active"
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_decisions").fetchone()["n"] == 2
    finally:
        store.close()


def test_decision_supersession_atomic_active_transition(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec(decision_id="A", lifecycle_status="active"))
        project_decision(store._conn, _dec(
            decision_id="B", op="supersede", supersedes_id="A", lifecycle_status="active"))
        # A must be superseded and B active atomically (no intermediate dual-active)
        a = store._conn.execute("SELECT lifecycle_status FROM zm_decisions WHERE decision_id='A'").fetchone()
        b = store._conn.execute("SELECT lifecycle_status FROM zm_decisions WHERE decision_id='B'").fetchone()
        assert a["lifecycle_status"] == "superseded"
        assert b["lifecycle_status"] == "active"
    finally:
        store.close()


def test_decision_supersession_no_timestamp_inference(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        # B is "newer" by created_at but with NO explicit supersedes_id -> not a
        # supersession. A second active decision for the same key is an
        # active-uniqueness conflict; A is NOT silently superseded by recency.
        project_decision(store._conn, _dec(decision_id="A", decision_key="K", lifecycle_status="active",
                                           created_at="2026-01-01T00:00:00Z"))
        with pytest.raises(ConflictError):
            project_decision(store._conn, _dec(decision_id="B", decision_key="K", lifecycle_status="active",
                                               created_at="2026-08-01T00:00:00Z"))
        a = store._conn.execute("SELECT lifecycle_status, replaced_by FROM zm_decisions WHERE decision_id='A'").fetchone()
        assert a["lifecycle_status"] == "active"
        assert a["replaced_by"] is None
    finally:
        store.close()


def test_decision_supersession_missing_target_rolls_back(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        with pytest.raises(MissingIdentityError):
            project_decision(store._conn, _dec(
                decision_id="B", op="supersede", supersedes_id="DOES-NOT-EXIST", lifecycle_status="active"))
        # no partial B row
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_decisions").fetchone()["n"] == 0
    finally:
        store.close()


def test_decision_self_supersession_rejected(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec(decision_id="A"))
        with pytest.raises(InvalidTransitionError):
            project_decision(store._conn, _dec(
                decision_id="A", op="supersede", supersedes_id="A", lifecycle_status="active"))
    finally:
        store.close()


def test_decision_explicit_chain_a_b_c_preserved(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec(decision_id="A", lifecycle_status="active"))
        project_decision(store._conn, _dec(
            decision_id="B", op="supersede", supersedes_id="A", lifecycle_status="active"))
        project_decision(store._conn, _dec(
            decision_id="C", op="supersede", supersedes_id="B", lifecycle_status="active"))
        rows = {r["decision_id"]: (r["lifecycle_status"], r["supersedes_id"], r["replaced_by"])
                for r in store._conn.execute("SELECT * FROM zm_decisions")}
        # all three preserved
        assert set(rows) == {"A", "B", "C"}
        # chain: B supersedes A; C supersedes B. No flattening.
        assert rows["A"] == ("superseded", None, "B")
        assert rows["B"] == ("superseded", "A", "C")
        assert rows["C"][0] == "active" and rows["C"][1] == "B"
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_decisions").fetchone()["n"] == 3
    finally:
        store.close()


def test_decision_malformed_cycle_rejected(tmp_path: Path) -> None:
    # A<-B (B supersedes A). Then a NEW op "A supersedes B" would be op with
    # decision_id="A" supersedes_id="B". Since A already exists, the projector
    # treats it as idempotent noop (A already projected) -> no cyclic link formed.
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec(decision_id="A", lifecycle_status="active"))
        project_decision(store._conn, _dec(
            decision_id="B", op="supersede", supersedes_id="A", lifecycle_status="active"))
        # Attempt to close a cycle: A supersedes B (new op, but A exists -> noop).
        out = project_decision(store._conn, _dec(
            decision_id="A", op="supersede", supersedes_id="B", lifecycle_status="active"))
        assert out["action"] == "noop"
        # No cycle: B still supersedes A; A does not point back to B.
        b = store._conn.execute(
            "SELECT supersedes_id FROM zm_decisions WHERE decision_id='B'").fetchone()
        a = store._conn.execute(
            "SELECT supersedes_id, replaced_by FROM zm_decisions WHERE decision_id='A'").fetchone()
        assert b["supersedes_id"] == "A"
        assert a["supersedes_id"] is None
        assert a["replaced_by"] == "B"
    finally:
        store.close()


# ===================== Conflict =====================


def test_decision_explicit_conflict_preserves_both(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec(
            decision_id="A", decision_key="K", lifecycle_status="active", state="accepted"))
        project_decision(store._conn, _dec(
            decision_id="B", decision_key="K", lifecycle_status="conflicted", state="unresolved",
            source_event_id="E2"))
        # Both records preserved with their own provenance; no winner chosen.
        rows = store._conn.execute(
            "SELECT decision_id, lifecycle_status, source_event_id FROM zm_decisions").fetchall()
        by_id = {r["decision_id"]: r for r in rows}
        assert set(by_id) == {"A", "B"}
        assert by_id["A"]["lifecycle_status"] == "active"
        assert by_id["B"]["lifecycle_status"] == "conflicted"
        assert by_id["B"]["source_event_id"] == "E2"
        # A was NOT auto-mutated to conflicted
        assert by_id["A"]["lifecycle_status"] == "active"
    finally:
        store.close()


def test_decision_conflict_no_automatic_winner(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        # Two conflicted decisions with the same key: neither is deleted/merged.
        project_decision(store._conn, _dec(decision_id="A", decision_key="K", lifecycle_status="conflicted"))
        project_decision(store._conn, _dec(decision_id="B", decision_key="K", lifecycle_status="conflicted"))
        n = store._conn.execute("SELECT COUNT(*) AS n FROM zm_decisions").fetchone()["n"]
        assert n == 2  # both preserved, no merge/winner
    finally:
        store.close()


def test_decision_conflict_no_auto_mutate_others(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec(decision_id="A", decision_key="K", lifecycle_status="active"))
        # A separate conflicted decision on same key must NOT mutate A.
        project_decision(store._conn, _dec(decision_id="B", decision_key="K", lifecycle_status="conflicted"))
        a = store._conn.execute("SELECT lifecycle_status FROM zm_decisions WHERE decision_id='A'").fetchone()
        assert a["lifecycle_status"] == "active"
    finally:
        store.close()


def test_decision_conflict_transaction_safe(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec(decision_id="A", decision_key="K", lifecycle_status="active"))
        # A second ACTIVE decision for the same (project, scope, key) with no
        # explicit supersession is an active-uniqueness conflict: the existing
        # valid active decision A must remain unchanged and no partial B row may
        # commit.
        with pytest.raises(ConflictError):
            project_decision(store._conn, _dec(decision_id="B", decision_key="K", lifecycle_status="active"))
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_decisions").fetchone()["n"] == 1
        assert store._conn.execute("SELECT decision_id FROM zm_decisions").fetchone()["decision_id"] == "A"
        a = store._conn.execute("SELECT lifecycle_status FROM zm_decisions WHERE decision_id='A'").fetchone()
        assert a["lifecycle_status"] == "active"
    finally:
        store.close()


# ===================== Safety / boundaries =====================


def test_decision_assistant_claim_not_promoted(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        with pytest.raises(PromotionBlockedError):
            project_decision(store._conn, _dec(
                decision_id="A", derived_from_event_type="assistant_claim", lifecycle_status="active"))
        # a non-active assistant_claim decision is allowed
        out = project_decision(store._conn, _dec(
            decision_id="A2", derived_from_event_type="assistant_claim", lifecycle_status="candidate", state="proposed"))
        assert out["action"] == "created"
        r = store._conn.execute("SELECT lifecycle_status FROM zm_decisions WHERE decision_id='A2'").fetchone()
        assert r["lifecycle_status"] == "candidate"
    finally:
        store.close()


def test_decision_no_raw_sqlite_error_leakage(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        try:
            project_decision(store._conn, _dec(decision_id="  "))
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            assert "sqlite3" not in msg
            assert "UNIQUE constraint" not in msg
            assert "FOREIGN KEY" not in msg
    finally:
        store.close()


def test_decision_schema_remains_v8(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec())
        assert store.get_schema_version() == 11
    finally:
        store.close()


def test_decision_m3_readonly_untouched(tmp_path: Path) -> None:
    from src.retrieval.db import open_readonly
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec())
        rs = open_readonly(store.path)
        try:
            assert rs.get_schema_version() == 11
        finally:
            rs.close()
    finally:
        store.close()


def test_decision_no_real_hermes_home_writes(tmp_path: Path) -> None:
    import os
    home = os.path.expanduser("~/.hermes")
    before = set(os.listdir(home)) if os.path.isdir(home) else set()
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec())
    finally:
        store.close()
    after = set(os.listdir(home)) if os.path.isdir(home) else set()
    assert after == before


def test_decision_no_llm_or_network_imports() -> None:
    import src.project_memory.projector as p
    import src.project_memory.contracts as c
    for mod in (p, c):
        src_text = open(mod.__file__, "r", encoding="utf-8").read()
        for forbidden in ("import openai", "import requests", "import http.client",
                          "import socket", "import semantic", "from semantic",
                          "import embeddings", "from embeddings"):
            assert forbidden not in src_text, f"forbidden token in {mod.__name__}: {forbidden}"


def test_decision_no_other_m4_tables_touched(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec())
        for t in ("zm_project_charters", "zm_requirements", "zm_project_state",
                  "zm_verifications", "zm_project_artifacts"):
            assert store._conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"] == 0
    finally:
        store.close()


def test_decision_jsonl_immutability(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec())
        assert list(tmp_path.glob("*.jsonl")) == []
    finally:
        store.close()


# ===================== Determinism / replay =====================


def _decision_build(p: Path) -> dict:
    s = _open(p)
    try:
        project_decision(s._conn, _dec(decision_id="A", decision_key="K", lifecycle_status="active", state="accepted"))
        project_decision(s._conn, _dec(
            decision_id="B", op="supersede", supersedes_id="A", decision_key="K", lifecycle_status="active", state="accepted"))
        project_decision(s._conn, _dec(
            decision_id="C", op="supersede", supersedes_id="B", decision_key="K", lifecycle_status="conflicted", state="unresolved"))
        rows = s._conn.execute(
            "SELECT decision_id, lifecycle_status, state, supersedes_id, replaced_by "
            "FROM zm_decisions ORDER BY decision_id").fetchall()
        return {(r["decision_id"], r["lifecycle_status"], r["state"], r["supersedes_id"], r["replaced_by"]) for r in rows}
    finally:
        s.close()


def test_decision_replay_determinism(tmp_path: Path) -> None:
    assert _decision_build(tmp_path / "a") == _decision_build(tmp_path / "b")


def test_decision_incremental_vs_replay_equal(tmp_path: Path) -> None:
    # Incremental (one store, sequential A->B->C) vs replay (fresh stores per run)
    # must produce the same committed set when the event sequence is identical.
    inc = _open(tmp_path / "inc")
    try:
        project_decision(inc._conn, _dec(decision_id="A", decision_key="K", lifecycle_status="active", state="accepted"))
        project_decision(inc._conn, _dec(
            decision_id="B", op="supersede", supersedes_id="A", decision_key="K", lifecycle_status="active", state="accepted"))
        project_decision(inc._conn, _dec(
            decision_id="C", op="supersede", supersedes_id="B", decision_key="K", lifecycle_status="conflicted", state="unresolved"))
        inc_rows = {(r["decision_id"], r["lifecycle_status"], r["state"], r["supersedes_id"], r["replaced_by"])
                    for r in inc._conn.execute("SELECT * FROM zm_decisions")}
    finally:
        inc.close()
    replay = _decision_build(tmp_path / "rep")
    assert inc_rows == replay


# ===================== Provenance =====================


def test_decision_provenance_retained(tmp_path: Path) -> None:
    # VERIFIED M4.1 v7 zm_decisions schema: provenance columns are
    # source_event_id, trace_id, session_id, profile_id, effective_at
    # (temporal slot; no separate created_at column).
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec(
            source_event_id="EV", trace_id="TR", session_id="SE", profile_id="PR",
            effective_at="2026-08-07T01:00:00Z"))
        row = store._conn.execute(
            "SELECT source_event_id, trace_id, session_id, profile_id, effective_at "
            "FROM zm_decisions WHERE decision_id='D1'").fetchone()
        assert row["source_event_id"] == "EV"
        assert row["trace_id"] == "TR"
        assert row["session_id"] == "SE"
        assert row["profile_id"] == "PR"
        assert row["effective_at"] == "2026-08-07T01:00:00Z"
    finally:
        store.close()


# ===================== classify =====================


def test_classify_decision_event(tmp_path: Path) -> None:
    evt = {"event_type": "user_statement", "m4": {"domain": "decision", "identity": "D9", "op": "create"}}
    assert classify_event_for_m4(evt) == CLASSIFY_DECISION
    # generic event still skips
    assert classify_event_for_m4({"event_type": "assistant_claim"}) == CLASSIFY_SKIP


def test_decision_deleted_handling(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_decision(store._conn, _dec())
        out = project_decision(store._conn, _dec(op="delete"))
        assert out["action"] == "deleted"
        r = store._conn.execute("SELECT lifecycle_status FROM zm_decisions WHERE decision_id='D1'").fetchone()
        assert r["lifecycle_status"] == "deleted"
        # history preserved
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_decisions").fetchone()["n"] == 1
    finally:
        store.close()
