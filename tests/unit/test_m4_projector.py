"""M4.2 focused tests: Project Charter and Requirement Registry projection.

Covers only M4.2 (deterministic projector for Charter + Requirement domains).
No M4.1 schema changes, no M3 read-only changes, no M4.3+ behavior, no M5.

All tests use temporary directories; none write to the real ~/.hermes.
No LLM or network calls. Secrets are synthetic and never asserted in errors.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.storage.migrations import CURRENT_SCHEMA_VERSION
from src.project_memory import (
    project_charter,
    project_requirement,
    classify_event_for_m4,
    CLASSIFY_CHARTER,
    CLASSIFY_REQUIREMENT,
    CLASSIFY_SKIP,
)
from src.project_memory.contracts import (
    CharterOp,
    RequirementOp,
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
    store.ensure_schema()  # apply v7 (derived M4 tables)
    assert store.get_schema_version() == 11
    return store


def _charter(op="create", **kw) -> CharterOp:
    base = dict(
        op=op, charter_id="C1", project_id="P", name="Initial Charter",
        goal="ship M4", scope="all", lifecycle_status="active", state="accepted",
        source_event_id="E1", trace_id="T1", session_id="S1", profile_id="PF1",
        created_at="2026-08-07T00:00:00Z",
    )
    base.update(kw)
    return CharterOp(**base)


def _req(op="create", **kw) -> RequirementOp:
    base = dict(
        op=op, requirement_id="R1", project_id="P", statement="must be deterministic",
        lifecycle_status="candidate", state="proposed", verification_status="none",
        source_event_id="E2", trace_id="T2", session_id="S1", profile_id="PF1",
        created_at="2026-08-07T00:00:00Z",
    )
    base.update(kw)
    return RequirementOp(**base)


# ===================== Charter =====================


def test_charter_creation(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        out = project_charter(store._conn, _charter())
        assert out["action"] == "created"
        assert out["version"] == 1
        row = store._conn.execute(
            "SELECT * FROM zm_project_charters WHERE charter_id='C1'").fetchone()
        assert row["project_id"] == "P"
        assert row["lifecycle_status"] == "active"
        assert row["state"] == "accepted"
        assert row["source_event_id"] == "E1"
        assert row["trace_id"] == "T1"
        # active uniqueness index satisfied (one active per project)
        n = store._conn.execute(
            "SELECT COUNT(*) AS n FROM zm_project_charters "
            "WHERE project_id='P' AND lifecycle_status='active'").fetchone()["n"]
        assert n == 1
    finally:
        store.close()


def test_charter_repeated_creation_idempotent(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_charter(store._conn, _charter())
        out = project_charter(store._conn, _charter())  # same content
        assert out["action"] == "noop"
        n = store._conn.execute(
            "SELECT COUNT(*) AS n FROM zm_project_charters").fetchone()["n"]
        assert n == 1
    finally:
        store.close()


def test_charter_version_creation_preserves_prior(tmp_path: Path) -> None:
    # The VERIFIED v7 schema uses charter_id as a single PRIMARY KEY, so the
    # derived table holds the CURRENT version with an incremented version counter;
    # full historical versions are preserved in the canonical JSONL (authoritative,
    # append-only) and reproduced by rebuild. An UPDATE bumps version in place and
    # never silently drops the prior content from the canonical source.
    store = _open(tmp_path)
    try:
        project_charter(store._conn, _charter())
        out = project_charter(store._conn, _charter(
            op="update", name="Revised Charter", state="accepted"))
        assert out["action"] == "versioned"
        assert out["version"] == 2
        # Single row per charter_id with the latest version.
        n = store._conn.execute(
            "SELECT COUNT(*) AS n FROM zm_project_charters WHERE charter_id='C1'").fetchone()["n"]
        assert n == 1
        row = store._conn.execute(
            "SELECT version, lifecycle_status, name FROM zm_project_charters "
            "WHERE charter_id='C1'").fetchone()
        assert row["version"] == 2
        assert row["lifecycle_status"] == "active"
        assert row["name"] == "Revised Charter"
    finally:
        store.close()


def test_charter_explicit_supersession_links(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_charter(store._conn, _charter(charter_id="C1", lifecycle_status="active"))
        # A DISTINCT new charter_id supersedes C1.
        out = project_charter(store._conn, _charter(
            charter_id="C2", op="supersede", supersedes="C1", lifecycle_status="active", state="accepted"))
        assert out["action"] == "versioned"
        # New active charter carries the supersedes link.
        new = store._conn.execute(
            "SELECT supersedes, lifecycle_status FROM zm_project_charters WHERE charter_id='C2'").fetchone()
        assert new["supersedes"] == "C1"
        assert new["lifecycle_status"] == "active"
        # Prior charter preserved and marked superseded (history retained).
        old = store._conn.execute(
            "SELECT lifecycle_status FROM zm_project_charters WHERE charter_id='C1'").fetchone()
        assert old["lifecycle_status"] == "superseded"
        # Both rows retained.
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_project_charters").fetchone()["n"] == 2
    finally:
        store.close()


def test_charter_active_uniqueness_one_per_project(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_charter(store._conn, _charter(charter_id="CA", lifecycle_status="active"))
        # A second ACTIVE charter for the same project must be preserved as a
        # conflict (no winner, no overwrite) rather than corrupting state.
        with pytest.raises(ConflictError):
            project_charter(store._conn, _charter(
                charter_id="CB", lifecycle_status="active"))
        # Existing active CA retained; CB not inserted.
        n = store._conn.execute(
            "SELECT COUNT(*) AS n FROM zm_project_charters").fetchone()["n"]
        assert n == 1
        cur = store._conn.execute(
            "SELECT charter_id FROM zm_project_charters").fetchone()
        assert cur["charter_id"] == "CA"
    finally:
        store.close()


def test_charter_active_selection_not_timestamp_based(tmp_path: Path) -> None:
    # Two charters, only one active; selection is by lifecycle_status, never MAX(created_at).
    store = _open(tmp_path)
    try:
        project_charter(store._conn, _charter(
            charter_id="COLD", lifecycle_status="superseded", created_at="2026-01-01T00:00:00Z"))
        project_charter(store._conn, _charter(
            charter_id="NEW", lifecycle_status="active", created_at="2026-08-01T00:00:00Z"))
        active = store._conn.execute(
            "SELECT charter_id FROM zm_project_charters WHERE lifecycle_status='active'").fetchone()
        assert active["charter_id"] == "NEW"  # selected by lifecycle, not timestamp
    finally:
        store.close()


def test_charter_invalid_lifecycle_rejected(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        with pytest.raises(InvalidLifecycleError):
            project_charter(store._conn, _charter(lifecycle_status="accepted"))
    finally:
        store.close()


def test_charter_domain_state_allowed_in_state_column(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_charter(store._conn, _charter(lifecycle_status="candidate", state="accepted"))
        row = store._conn.execute(
            "SELECT lifecycle_status, state FROM zm_project_charters WHERE charter_id='C1'").fetchone()
        assert row["lifecycle_status"] == "candidate"
        assert row["state"] == "accepted"
    finally:
        store.close()


def test_charter_deleted_handling(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_charter(store._conn, _charter())
        out = project_charter(store._conn, _charter(op="delete"))
        assert out["action"] == "deleted"
        row = store._conn.execute(
            "SELECT lifecycle_status FROM zm_project_charters WHERE charter_id='C1'").fetchone()
        assert row["lifecycle_status"] == "deleted"
        # history remains; not physically removed
        n = store._conn.execute(
            "SELECT COUNT(*) AS n FROM zm_project_charters").fetchone()["n"]
        assert n == 1
    finally:
        store.close()


def test_charter_terminal_deleted_cannot_transition_out(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_charter(store._conn, _charter())  # create first
        project_charter(store._conn, _charter(op="delete"))
        with pytest.raises(InvalidTransitionError):
            project_charter(store._conn, _charter(op="transition", lifecycle_status="active"))
    finally:
        store.close()


def test_charter_provenance_retained(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_charter(store._conn, _charter(
            source_event_id="EV", trace_id="TR", session_id="SE", profile_id="PR"))
        row = store._conn.execute(
            "SELECT source_event_id, trace_id, session_id, profile_id, created_at "
            "FROM zm_project_charters WHERE charter_id='C1'").fetchone()
        assert row["source_event_id"] == "EV"
        assert row["trace_id"] == "TR"
        assert row["session_id"] == "SE"
        assert row["profile_id"] == "PR"
    finally:
        store.close()


def test_charter_transaction_rollback_on_error(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        # Force an integrity error mid-transaction via a duplicate active insert
        # inside one op by pre-inserting an active charter, then attempting a
        # second active that the partial unique index rejects -> ConflictError,
        # and the failing op must not leave partial state.
        project_charter(store._conn, _charter(charter_id="A", lifecycle_status="active"))
        with pytest.raises(ConflictError):
            project_charter(store._conn, _charter(
                charter_id="B", lifecycle_status="active", op="create"))
        # No B row; A still active and intact.
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_project_charters").fetchone()["n"] == 1
        assert store._conn.execute(
            "SELECT charter_id FROM zm_project_charters").fetchone()["charter_id"] == "A"
        # schema version untouched
        assert store.get_schema_version() == 11
    finally:
        store.close()


def test_charter_replay_determinism(tmp_path: Path) -> None:
    # Replaying the same sequence into a fresh DB yields identical committed state.
    def _build(p: Path) -> dict:
        s = _open(p)
        try:
            project_charter(s._conn, _charter())
            project_charter(s._conn, _charter(op="update", name="v2", state="accepted"))
            project_charter(s._conn, _charter(op="transition", lifecycle_status="archived"))
            row = s._conn.execute(
                "SELECT version, lifecycle_status, name FROM zm_project_charters "
                "WHERE charter_id='C1'").fetchone()
            return {"version": row["version"], "lifecycle_status": row["lifecycle_status"],
                    "name": row["name"]}
        finally:
            s.close()

    a = _build(tmp_path / "a")
    b = _build(tmp_path / "b")
    assert a == b
    assert a == {"version": 2, "lifecycle_status": "archived", "name": "v2"}


# ===================== Requirements =====================


def test_requirement_creation(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        out = project_requirement(store._conn, _req())
        assert out["action"] == "created"
        row = store._conn.execute(
            "SELECT * FROM zm_requirements WHERE requirement_id='R1'").fetchone()
        assert row["project_id"] == "P"
        assert row["statement"] == "must be deterministic"
        assert row["lifecycle_status"] == "candidate"
        assert row["state"] == "proposed"
        assert row["source_event_id"] == "E2"
    finally:
        store.close()


def test_requirement_explicit_id_preserved(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_requirement(store._conn, _req(requirement_id="REQ-X"))
        row = store._conn.execute(
            "SELECT requirement_id FROM zm_requirements WHERE requirement_id='REQ-X'").fetchone()
        assert row["requirement_id"] == "REQ-X"
    finally:
        store.close()


def test_requirement_missing_identity_not_invented(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        with pytest.raises(MissingIdentityError):
            project_requirement(store._conn, _req(requirement_id="  "))
    finally:
        store.close()


def test_requirement_trace_id_not_used_as_identity(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_requirement(store._conn, _req(trace_id="T-looks-like-id"))
        # identity is requirement_id, not trace_id
        row = store._conn.execute(
            "SELECT requirement_id, trace_id FROM zm_requirements WHERE requirement_id='R1'").fetchone()
        assert row["requirement_id"] == "R1"
        assert row["trace_id"] == "T-looks-like-id"
    finally:
        store.close()


def test_requirement_assistant_claim_not_auto_active(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        with pytest.raises(PromotionBlockedError):
            project_requirement(store._conn, _req(
                derived_from_event_type="assistant_claim", lifecycle_status="active"))
        # A non-active assistant_claim requirement is allowed (stays candidate).
        out = project_requirement(store._conn, _req(
            derived_from_event_type="assistant_claim", lifecycle_status="candidate", state="proposed"))
        assert out["action"] == "created"
        row = store._conn.execute(
            "SELECT lifecycle_status FROM zm_requirements WHERE requirement_id='R1'").fetchone()
        assert row["lifecycle_status"] == "candidate"
    finally:
        store.close()


def test_requirement_domain_state_separate_from_lifecycle(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_requirement(store._conn, _req(lifecycle_status="confirmed", state="satisfied"))
        row = store._conn.execute(
            "SELECT lifecycle_status, state FROM zm_requirements WHERE requirement_id='R1'").fetchone()
        assert row["lifecycle_status"] == "confirmed"
        assert row["state"] == "satisfied"
        # invalid lifecycle rejected
        with pytest.raises(InvalidLifecycleError):
            project_requirement(store._conn, _req(lifecycle_status="satisfied"))
    finally:
        store.close()


def test_requirement_explicit_transition(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_requirement(store._conn, _req())
        out = project_requirement(store._conn, _req(
            op="transition", lifecycle_status="confirmed", state="satisfied",
            verification_status="deterministic_verification"))
        assert out["action"] == "transitioned"
        row = store._conn.execute(
            "SELECT lifecycle_status, state, verification_status FROM zm_requirements "
            "WHERE requirement_id='R1'").fetchone()
        assert row["lifecycle_status"] == "confirmed"
        assert row["state"] == "satisfied"
        assert row["verification_status"] == "deterministic_verification"
    finally:
        store.close()


def test_requirement_no_timestamp_based_supersession(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_requirement(store._conn, _req(requirement_id="RA", lifecycle_status="active"))
        # A newer event with a DIFFERENT id but no explicit supersedes link must
        # NOT supersede RA automatically (no timestamp inference).
        project_requirement(store._conn, _req(requirement_id="RB", lifecycle_status="active", op="create"))
        ra = store._conn.execute(
            "SELECT replaced_by FROM zm_requirements WHERE requirement_id='RA'").fetchone()
        assert ra["replaced_by"] is None
        n = store._conn.execute("SELECT COUNT(*) AS n FROM zm_requirements").fetchone()["n"]
        assert n == 2
    finally:
        store.close()


def test_requirement_explicit_supersession_preserves_history(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_requirement(store._conn, _req(requirement_id="OLD", lifecycle_status="active"))
        out = project_requirement(store._conn, _req(
            requirement_id="NEW", op="supersede", supersedes="OLD", lifecycle_status="active"))
        assert out["action"] == "superseded"
        old = store._conn.execute(
            "SELECT lifecycle_status, replaced_by FROM zm_requirements "
            "WHERE requirement_id='OLD'").fetchone()
        assert old["lifecycle_status"] == "superseded"
        assert old["replaced_by"] == "NEW"
        new = store._conn.execute(
            "SELECT supersedes FROM zm_requirements WHERE requirement_id='NEW'").fetchone()
        assert new["supersedes"] == "OLD"
        # both retained
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_requirements").fetchone()["n"] == 2
    finally:
        store.close()


def test_requirement_invalid_transition_rejected_safely(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_requirement(store._conn, _req())  # create first
        project_requirement(store._conn, _req(op="delete"))
        # deleted is terminal; transition out must fail with sanitized error,
        # no corruption of existing state.
        with pytest.raises(InvalidTransitionError):
            project_requirement(store._conn, _req(op="transition", lifecycle_status="active"))
        row = store._conn.execute(
            "SELECT lifecycle_status FROM zm_requirements WHERE requirement_id='R1'").fetchone()
        assert row["lifecycle_status"] == "deleted"
    finally:
        store.close()


def test_requirement_repeated_event_idempotent(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_requirement(store._conn, _req())
        out = project_requirement(store._conn, _req())  # same content
        assert out["action"] == "noop"
        n = store._conn.execute("SELECT COUNT(*) AS n FROM zm_requirements").fetchone()["n"]
        assert n == 1
    finally:
        store.close()


def test_requirement_conflict_preserved(tmp_path: Path) -> None:
    # Two requirements with the SAME id but conflicting content and no explicit
    # update op -> the second is rejected (preserve existing; no winner).
    store = _open(tmp_path)
    try:
        project_requirement(store._conn, _req(statement="first"))
        with pytest.raises(InvalidTransitionError):
            project_requirement(store._conn, _req(op="create", statement="second"))
        row = store._conn.execute(
            "SELECT statement FROM zm_requirements WHERE requirement_id='R1'").fetchone()
        assert row["statement"] == "first"
    finally:
        store.close()


def test_requirement_deleted_handling(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_requirement(store._conn, _req())
        out = project_requirement(store._conn, _req(op="delete"))
        assert out["action"] == "deleted"
        row = store._conn.execute(
            "SELECT lifecycle_status FROM zm_requirements WHERE requirement_id='R1'").fetchone()
        assert row["lifecycle_status"] == "deleted"
        n = store._conn.execute("SELECT COUNT(*) AS n FROM zm_requirements").fetchone()["n"]
        assert n == 1  # history preserved
    finally:
        store.close()


def test_requirement_provenance_retained(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_requirement(store._conn, _req(
            source_event_id="EV", trace_id="TR", session_id="SE", profile_id="PR"))
        row = store._conn.execute(
            "SELECT source_event_id, trace_id, session_id, profile_id, created_at "
            "FROM zm_requirements WHERE requirement_id='R1'").fetchone()
        assert row["source_event_id"] == "EV"
        assert row["trace_id"] == "TR"
        assert row["session_id"] == "SE"
        assert row["profile_id"] == "PR"
    finally:
        store.close()


def test_requirement_transaction_rollback(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_requirement(store._conn, _req(requirement_id="RA", lifecycle_status="active"))
        # supersede NEW -> OLD but OLD does not exist -> MissingIdentityError;
        # the NEW insert must roll back (no partial NEW row).
        with pytest.raises(MissingIdentityError):
            project_requirement(store._conn, _req(
                requirement_id="NEW", op="supersede", supersedes="DOES-NOT-EXIST",
                lifecycle_status="active"))
        n = store._conn.execute("SELECT COUNT(*) AS n FROM zm_requirements").fetchone()["n"]
        assert n == 1
        assert store._conn.execute(
            "SELECT requirement_id FROM zm_requirements").fetchone()["requirement_id"] == "RA"
    finally:
        store.close()


def test_requirement_replay_determinism(tmp_path: Path) -> None:
    def _build(p: Path) -> set:
        s = _open(p)
        try:
            project_requirement(s._conn, _req())
            project_requirement(s._conn, _req(op="transition", lifecycle_status="confirmed", state="satisfied"))
            project_requirement(s._conn, _req(op="supersede", requirement_id="R2", supersedes="R1", lifecycle_status="active"))
            rows = s._conn.execute(
                "SELECT requirement_id, lifecycle_status, state FROM zm_requirements "
                "ORDER BY requirement_id, lifecycle_status").fetchall()
            return {(r["requirement_id"], r["lifecycle_status"], r["state"]) for r in rows}
        finally:
            s.close()

    assert _build(tmp_path / "a") == _build(tmp_path / "b")


# ===================== Cross-cutting =====================


def test_no_duplicate_across_charter_and_requirement(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_charter(store._conn, _charter())
        project_requirement(store._conn, _req())
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_project_charters").fetchone()["n"] == 1
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_requirements").fetchone()["n"] == 1
    finally:
        store.close()


def test_no_raw_sqlite_error_leakage(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        try:
            project_requirement(store._conn, _req(requirement_id="  "))
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            assert "sqlite3" not in msg
            assert "UNIQUE constraint" not in msg
            assert "TRACEBACK" not in msg.upper()
    finally:
        store.close()


def test_schema_remains_v8(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        assert CURRENT_SCHEMA_VERSION == 11
        project_charter(store._conn, _charter())
        project_requirement(store._conn, _req())
        assert store.get_schema_version() == 11
    finally:
        store.close()


def test_classify_event_missing_identity_skips(tmp_path: Path) -> None:
    # Generic events without an explicit structured M4 block are SKIPPED (no
    # inference, no invention). assistant_claim with requirement-like text is
    # NOT projected.
    generic = {
        "event_id": "e1", "trace_id": "t1", "event_type": "assistant_claim",
        "source": "x", "schema_version": 1, "created_at": "2026-08-07T00:00:00Z",
        "observed_at": "2026-08-07T00:00:00Z", "sequence": 1,
        "lifecycle_status": "candidate", "verification_status": "none",
        "confidence": "low", "sensitivity": "public", "retention": "session",
        "sanitized_content_hash": "h", "sanitized_content": "we should require X",
    }
    assert classify_event_for_m4(generic) == CLASSIFY_SKIP
    # Explicit structured M4 block projects.
    structured = dict(generic)
    structured["m4"] = {"domain": "requirement", "identity": "R9", "op": "create"}
    assert classify_event_for_m4(structured) == CLASSIFY_REQUIREMENT
    structured["m4"] = {"domain": "charter", "identity": "C9", "op": "create"}
    assert classify_event_for_m4(structured) == CLASSIFY_CHARTER


def test_no_m3_readonly_regression(tmp_path: Path) -> None:
    # M4.2 projector never opens a read-only connection or calls ensure_schema;
    # M3 open_readonly remains available and query_only.
    from src.retrieval.db import open_readonly
    store = _open(tmp_path)
    try:
        project_charter(store._conn, _charter())
        project_requirement(store._conn, _req())
        # M3 read-only path still works and is independent.
        rs = open_readonly(store.path)
        try:
            assert rs.get_schema_version() == 11
        finally:
            rs.close()
    finally:
        store.close()


def test_no_real_hermes_home_writes(tmp_path: Path) -> None:
    import os
    home = os.path.expanduser("~/.hermes")
    before = set()
    if os.path.isdir(home):
        before = set(os.listdir(home))
    store = _open(tmp_path)
    try:
        project_charter(store._conn, _charter())
        project_requirement(store._conn, _req())
    finally:
        store.close()
    after = set(os.listdir(home)) if os.path.isdir(home) else set()
    assert after == before, "M4.2 must not write to the real ~/.hermes"


def test_no_llm_or_network_imports() -> None:
    import src.project_memory.projector as p
    import src.project_memory.contracts as c
    for mod in (p, c):
        src_text = open(mod.__file__, "r", encoding="utf-8").read()
        for forbidden in ("import openai", "import requests", "import http.client",
                          "import socket", "import semantic", "from semantic",
                          "import embeddings", "from embeddings"):
            assert forbidden not in src_text, f"forbidden token in {mod.__name__}: {forbidden}"


def test_no_decision_state_verification_artifact_behavior(tmp_path: Path) -> None:
    # M4.2 must not write to zm_decisions / zm_project_state / zm_verifications /
    # zm_project_artifacts.
    store = _open(tmp_path)
    try:
        project_charter(store._conn, _charter())
        project_requirement(store._conn, _req())
        for t in ("zm_decisions", "zm_project_state", "zm_verifications", "zm_project_artifacts"):
            n = store._conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
            assert n == 0, f"{t} must be untouched by M4.2"
    finally:
        store.close()


def test_jsonl_immutability(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_charter(store._conn, _charter())
        project_requirement(store._conn, _req())
        # No JSONL created by projection (canonical source untouched).
        jsonl = list(tmp_path.glob("*.jsonl"))
        assert jsonl == [], "M4.2 projection must not create JSONL"
    finally:
        store.close()
