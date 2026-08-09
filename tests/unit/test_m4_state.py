"""M4.4 focused tests: Current Project State reducer (create/update/supersede/
transition/delete/active-uniqueness/conflict/idempotence/transition-safety/
provenance/determinism).

Covers only M4.4. No M4.1 schema change, no M4.5+/M5 behavior, no M3 read API.
All tests use temporary directories; none write to the real ~/.hermes.
No LLM or network calls. Secrets are synthetic and never asserted in errors.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.project_memory import (
    project_state,
    classify_event_for_m4,
    CLASSIFY_STATE,
    CLASSIFY_SKIP,
)
from src.project_memory.contracts import (
    StateOp,
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
    assert store.get_schema_version() == 9
    return store


def _st(op="create", **kw) -> StateOp:
    base = dict(
        op=op, project_id="P",
        state_key="progress", state_value="40%",
        lifecycle_status="active", verification_status="none",
        source_event_id="E1", trace_id="T1", session_id="S1", profile_id="PF1",
        created_at="2026-08-08T00:00:00Z",
    )
    base.update(kw)
    return StateOp(**base)


# ===================== Identity / key =====================


def test_state_explicit_key_preserved(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st())
        row = store._conn.execute(
            "SELECT state_key, scope FROM zm_project_state WHERE lifecycle_status='active'").fetchone()
        assert row["state_key"] == "progress"
        # scope defaults to project:<project_id> when state_key present
        assert row["scope"] == "project:P"
    finally:
        store.close()


def test_state_absent_key_is_null(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st(state_key=None))
        row = store._conn.execute(
            "SELECT state_key, scope FROM zm_project_state").fetchone()
        assert row["state_key"] is None
        assert row["scope"] is None
    finally:
        store.close()


def test_state_trace_id_not_used_as_key(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st(state_key=None, trace_id="T-looks-like-key"))
        row = store._conn.execute(
            "SELECT state_key, trace_id FROM zm_project_state").fetchone()
        assert row["state_key"] is None
        assert row["trace_id"] == "T-looks-like-key"
    finally:
        store.close()


# ===================== State / lifecycle =====================


def test_state_lifecycle_closed_enum_enforced(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        for allowed in ("raw", "observed", "candidate", "confirmed", "active",
                        "superseded", "conflicted", "archived", "deleted"):
            project_state(store._conn, _st(state_key=f"K-{allowed}", lifecycle_status=allowed))
            r = store._conn.execute(
                "SELECT lifecycle_status FROM zm_project_state WHERE state_key=?",
                (f"K-{allowed}",)).fetchone()
            assert r["lifecycle_status"] == allowed
        with pytest.raises(InvalidLifecycleError):
            project_state(store._conn, _st(state_key="BAD", lifecycle_status="proposed"))
    finally:
        store.close()


def test_state_domain_state_separate(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st(lifecycle_status="active", state_value="ready"))
        row = store._conn.execute(
            "SELECT lifecycle_status, state_value FROM zm_project_state WHERE state_key='progress'").fetchone()
        assert row["lifecycle_status"] == "active"
        assert row["state_value"] == "ready"
    finally:
        store.close()


# ===================== Creation / idempotence =====================


def test_state_creation(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        out = project_state(store._conn, _st())
        assert out["action"] == "created"
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_project_state").fetchone()["n"] == 1
    finally:
        store.close()


def test_state_repeated_create_idempotent(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st())
        out = project_state(store._conn, _st())
        assert out["action"] == "noop"
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_project_state").fetchone()["n"] == 1
    finally:
        store.close()


def test_state_no_duplicates(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st())
        project_state(store._conn, _st())
        project_state(store._conn, _st())
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_project_state").fetchone()["n"] == 1
    finally:
        store.close()


# ===================== Update / supersession =====================


def test_state_update_marks_prior_superseded(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st(state_value="40%"))
        out = project_state(store._conn, _st(op="update", state_value="60%"))
        assert out["action"] == "created"
        rows = {r["state_value"]: r["lifecycle_status"] for r in
                store._conn.execute("SELECT * FROM zm_project_state")}
        assert rows == {"40%": "superseded", "60%": "active"}
        # exactly one active row
        n_active = store._conn.execute(
            "SELECT COUNT(*) AS n FROM zm_project_state WHERE lifecycle_status='active'").fetchone()["n"]
        assert n_active == 1
    finally:
        store.close()


def test_state_explicit_supersede_links_prior(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st(state_value="40%"))
        out = project_state(store._conn, _st(op="supersede", state_value="70%"))
        assert out["action"] == "superseded"
        prior = store._conn.execute(
            "SELECT state_value, lifecycle_status FROM zm_project_state WHERE state_value='40%'").fetchone()
        new = store._conn.execute(
            "SELECT state_value, lifecycle_status, supersedes FROM zm_project_state WHERE state_value='70%'").fetchone()
        assert prior["lifecycle_status"] == "superseded"
        assert new["lifecycle_status"] == "active"
        assert new["supersedes"].startswith("state:")
    finally:
        store.close()


def test_state_supersede_missing_target_rolls_back(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        # No prior active state for key 'novel' -> cannot supersede; rollback, no
        # partial row committed.
        with pytest.raises(MissingIdentityError):
            project_state(store._conn, _st(op="supersede", state_key="novel", state_value="x"))
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_project_state").fetchone()["n"] == 0
    finally:
        store.close()


def test_state_supersede_no_key_rejected(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        with pytest.raises(MissingIdentityError):
            project_state(store._conn, _st(op="supersede", state_key=None, state_value="x"))
    finally:
        store.close()


def test_state_supersede_idempotent(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st(state_value="40%"))
        out = project_state(store._conn, _st(op="supersede", state_value="70%"))
        assert out["action"] == "superseded"
        # same supersede again -> noop (no third row)
        out2 = project_state(store._conn, _st(op="supersede", state_value="70%"))
        assert out2["action"] == "noop"
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_project_state").fetchone()["n"] == 2
    finally:
        store.close()


# ===================== Active uniqueness / conflict =====================


def test_state_one_active_per_key(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st(state_key="K", state_value="a"))
        # A second NEW active state for the same (project, scope, key) without
        # explicit supersession is an active-uniqueness conflict (the existing
        # valid active state is retained, no partial second row).
        with pytest.raises(ConflictError):
            project_state(store._conn, _st(state_key="K", lifecycle_status="active", state_value="b"))
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_project_state").fetchone()["n"] == 1
        assert store._conn.execute("SELECT state_value FROM zm_project_state WHERE lifecycle_status='active'").fetchone()["state_value"] == "a"
    finally:
        store.close()


def test_state_active_different_key_allowed(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st(state_key="K1", state_value="a"))
        out = project_state(store._conn, _st(state_key="K2", state_value="b"))
        assert out["action"] == "created"
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_project_state").fetchone()["n"] == 2
    finally:
        store.close()


def test_state_multiple_active_null_key_allowed(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st(state_key=None, state_value="a"))
        out = project_state(store._conn, _st(state_key=None, state_value="b"))
        assert out["action"] == "created"
        n_active = store._conn.execute(
            "SELECT COUNT(*) AS n FROM zm_project_state WHERE lifecycle_status='active'").fetchone()["n"]
        assert n_active == 2
    finally:
        store.close()


def test_state_inactive_history_same_key_allowed(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st(state_key="K", state_value="a"))
        # A superseded historical row with the same key is allowed.
        project_state(store._conn, _st(op="update", state_key="K", state_value="b"))
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_project_state WHERE state_key='K'").fetchone()["n"] == 2
    finally:
        store.close()


# ===================== Explicit conflict preservation =====================


def test_state_explicit_conflict_preserved(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st(state_key="K", state_value="a", lifecycle_status="active"))
        # An explicitly conflicted state with the same key coexists; no winner.
        project_state(store._conn, _st(state_key="K", state_value="z", lifecycle_status="conflicted", source_event_id="E2"))
        rows = {r["state_value"]: r["lifecycle_status"] for r in
                store._conn.execute("SELECT * FROM zm_project_state WHERE state_key='K'")}
        assert rows == {"a": "active", "z": "conflicted"}
    finally:
        store.close()


def test_state_conflict_no_automatic_winner(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st(state_key="K", state_value="a", lifecycle_status="conflicted"))
        project_state(store._conn, _st(state_key="K", state_value="b", lifecycle_status="conflicted"))
        # both preserved, no merge/winner
        n = store._conn.execute("SELECT COUNT(*) AS n FROM zm_project_state WHERE state_key='K'").fetchone()["n"]
        assert n == 2
    finally:
        store.close()


def test_state_conflict_does_not_mutate_active(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st(state_key="K", state_value="a", lifecycle_status="active"))
        # A separate conflicted state on same key must NOT mutate 'a'.
        project_state(store._conn, _st(state_key="K", state_value="b", lifecycle_status="conflicted"))
        a = store._conn.execute("SELECT lifecycle_status FROM zm_project_state WHERE state_value='a'").fetchone()
        assert a["lifecycle_status"] == "active"
    finally:
        store.close()


# ===================== Transition / delete =====================


def test_state_transition_lifecycle(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st(state_value="a", lifecycle_status="active"))
        out = project_state(store._conn, _st(op="transition", state_value="a", lifecycle_status="archived"))
        assert out["action"] == "transitioned"
        r = store._conn.execute("SELECT lifecycle_status FROM zm_project_state WHERE state_value='a'").fetchone()
        assert r["lifecycle_status"] == "archived"
    finally:
        store.close()


def test_state_transition_missing_raises(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        with pytest.raises(MissingIdentityError):
            project_state(store._conn, _st(op="transition", state_key="absent", lifecycle_status="archived"))
    finally:
        store.close()


def test_state_delete_marks_deleted(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st(state_value="a"))
        out = project_state(store._conn, _st(op="delete"))
        assert out["action"] == "deleted"
        r = store._conn.execute("SELECT lifecycle_status FROM zm_project_state WHERE state_value='a'").fetchone()
        assert r["lifecycle_status"] == "deleted"
        # history preserved
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_project_state").fetchone()["n"] == 1
    finally:
        store.close()


# ===================== Safety / boundaries =====================


def test_state_assistant_claim_not_promoted(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        with pytest.raises(PromotionBlockedError):
            project_state(store._conn, _st(state_key="K", derived_from_event_type="assistant_claim", lifecycle_status="active"))
        # non-active assistant-derived state IS allowed
        out = project_state(store._conn, _st(state_key="K", derived_from_event_type="assistant_claim", lifecycle_status="candidate"))
        assert out["action"] == "created"
        assert store._conn.execute("SELECT lifecycle_status FROM zm_project_state").fetchone()["lifecycle_status"] == "candidate"
    finally:
        store.close()


def test_state_no_raw_sqlite_error_leakage(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        try:
            project_state(store._conn, _st(state_key="K", lifecycle_status="proposed"))
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            assert "sqlite3" not in msg
            assert "UNIQUE constraint" not in msg
            assert "FOREIGN KEY" not in msg
    finally:
        store.close()


def test_state_schema_remains_v8(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st())
        assert store.get_schema_version() == 9
    finally:
        store.close()


def test_state_m3_readonly_untouched(tmp_path: Path) -> None:
    from src.retrieval.db import open_readonly
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st())
        rs = open_readonly(store.path)
        try:
            assert rs.get_schema_version() == 9
        finally:
            rs.close()
    finally:
        store.close()


def test_state_no_real_hermes_home_writes(tmp_path: Path) -> None:
    import os
    home = os.path.expanduser("~/.hermes")
    before = set(os.listdir(home)) if os.path.isdir(home) else set()
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st())
    finally:
        store.close()
    after = set(os.listdir(home)) if os.path.isdir(home) else set()
    assert after == before


def test_state_no_llm_or_network_imports() -> None:
    import src.project_memory.projector as p
    import src.project_memory.contracts as c
    for mod in (p, c):
        src_text = open(mod.__file__, "r", encoding="utf-8").read()
        for forbidden in ("import openai", "import requests", "import http.client",
                          "import socket", "import semantic", "from semantic",
                          "import embeddings", "from embeddings"):
            assert forbidden not in src_text, f"forbidden token in {mod.__name__}: {forbidden}"


def test_state_no_other_m4_tables_touched(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st())
        for t in ("zm_project_charters", "zm_requirements", "zm_decisions",
                  "zm_verifications", "zm_project_artifacts"):
            assert store._conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"] == 0
    finally:
        store.close()


def test_state_jsonl_immutability(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st())
        assert list(tmp_path.glob("*.jsonl")) == []
    finally:
        store.close()


# ===================== Determinism / provenance / classify =====================


def _state_build(p: Path) -> set:
    s = _open(p)
    try:
        project_state(s._conn, _st(state_key="K", state_value="40%", lifecycle_status="active"))
        project_state(s._conn, _st(op="update", state_key="K", state_value="60%"))
        project_state(s._conn, _st(state_key="M", state_value="done", lifecycle_status="conflicted"))
        rows = s._conn.execute(
            "SELECT state_key, state_value, lifecycle_status, supersedes "
            "FROM zm_project_state ORDER BY state_key, state_value").fetchall()
        return {(r["state_key"], r["state_value"], r["lifecycle_status"], r["supersedes"]) for r in rows}
    finally:
        s.close()


def test_state_replay_determinism(tmp_path: Path) -> None:
    assert _state_build(tmp_path / "a") == _state_build(tmp_path / "b")


def test_state_incremental_vs_replay_equal(tmp_path: Path) -> None:
    inc = _open(tmp_path / "inc")
    try:
        project_state(inc._conn, _st(state_key="K", state_value="40%", lifecycle_status="active"))
        project_state(inc._conn, _st(op="update", state_key="K", state_value="60%"))
        project_state(inc._conn, _st(state_key="M", state_value="done", lifecycle_status="conflicted"))
        inc_rows = {(r["state_key"], r["state_value"], r["lifecycle_status"], r["supersedes"])
                    for r in inc._conn.execute("SELECT * FROM zm_project_state")}
    finally:
        inc.close()
    replay = _state_build(tmp_path / "rep")
    assert inc_rows == replay


def test_state_provenance_retained(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_state(store._conn, _st(
            source_event_id="EV", trace_id="TR", session_id="SE", profile_id="PR",
            effective_at="2026-08-08T01:00:00Z"))
        row = store._conn.execute(
            "SELECT source_event_id, trace_id, session_id, profile_id, effective_at "
            "FROM zm_project_state WHERE state_key='progress'").fetchone()
        assert row["source_event_id"] == "EV"
        assert row["trace_id"] == "TR"
        assert row["session_id"] == "SE"
        assert row["profile_id"] == "PR"
        assert row["effective_at"] == "2026-08-08T01:00:00Z"
    finally:
        store.close()


def test_classify_state_event(tmp_path: Path) -> None:
    evt = {"event_type": "user_statement", "m4": {"domain": "state", "identity": "K1", "op": "create"}}
    assert classify_event_for_m4(evt) == CLASSIFY_STATE
    # generic event still skips
    assert classify_event_for_m4({"event_type": "assistant_claim"}) == CLASSIFY_SKIP
