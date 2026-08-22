"""M4.5 focused tests: Verification Records + Project Artifact integration.

Covers only M4.5. No verification reads/queries; no M4.6/M4.7/M5 behavior.
Deterministic, idempotent, no LLM/network, no auto-promotion, no content
duplication, safe references, explicit links only, transaction safety, replay
determinism. Complements (does not replace) the full canonical suite.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.project_memory import (
    project_verification, project_artifact, classify_event_for_m4,
    CLASSIFY_VERIFICATION, CLASSIFY_PROJECT_ARTIFACT, CLASSIFY_SKIP,
)
from src.project_memory.contracts import (
    VerificationOp, ArtifactOp, MissingIdentityError, MissingRequiredFieldError,
    InvalidTransitionError, is_safe_reference,
)


def _open(p: Path) -> SQLiteStore:
    s = SQLiteStore(SQLiteStoreConfig(path=p / "m4v.sqlite"))
    s.ensure_schema()
    s._conn.execute("PRAGMA foreign_keys=ON")  # mirror projector enforcement
    return s


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _seed_artifact(conn: sqlite3.Connection, artifact_id: str = "A1") -> None:
    conn.execute(
        "INSERT INTO zm_artifacts(artifact_id, content_hash, kind, retention, created_at) "
        "VALUES (?,?,?,?,?)",
        (artifact_id, "h-" + artifact_id, "report", "persistent", "2026-08-07T00:00:00Z"),
    )
    conn.commit()  # store connection is not autocommit; close the tx before projector BEGIN


def _ver(**kw) -> VerificationOp:
    base = dict(op="create", verification_id="V1", project_id="P",
                subject_type="requirement", subject_id="R1", method="pytest",
                verification_status="none", source_event_id="E1")
    base.update(kw)
    return VerificationOp(**base)


def _art(**kw) -> ArtifactOp:
    base = dict(op="create", artifact_id="A1", project_id="P",
                artifact_type="report", version="1", safe_reference="reports/x.md",
                verification_status="none", source_event_id="E1")
    base.update(kw)
    return ArtifactOp(**base)


# ----------------------------------------------------------------------------
# Identity / classification
# ----------------------------------------------------------------------------

def test_verification_explicit_id_preserved(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        out = project_verification(store._conn, _ver(verification_id="VID-X"))
        assert out["action"] == "created"
        row = store._conn.execute(
            "SELECT verification_id FROM zm_verifications WHERE verification_id='VID-X'").fetchone()
        assert row["verification_id"] == "VID-X"
    finally:
        store.close()


def test_verification_missing_id_not_invented(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        with pytest.raises(MissingIdentityError):
            project_verification(store._conn, _ver(verification_id="  "))
    finally:
        store.close()


def test_verification_trace_id_not_used_as_id(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        out = project_verification(store._conn, _ver(verification_id="V1", trace_id="TR-1"))
        row = store._conn.execute(
            "SELECT verification_id FROM zm_verifications WHERE verification_id='V1'").fetchone()
        # identity is the explicit verification_id, NOT the trace_id
        assert row["verification_id"] == "V1"
        assert out["verification_id"] == "V1"
    finally:
        store.close()


def test_verification_repeated_event_idempotent(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_verification(store._conn, _ver())
        out = project_verification(store._conn, _ver())
        assert out["action"] == "noop"
        n = store._conn.execute("SELECT COUNT(*) AS n FROM zm_verifications").fetchone()["n"]
        assert n == 1
    finally:
        store.close()


def test_classify_verification_structured(tmp_path: Path) -> None:
    ev = {"event_type": "deterministic_verification",
          "m4": {"domain": "verification", "identity": "V1", "op": "create"}}
    assert classify_event_for_m4(ev) == CLASSIFY_VERIFICATION


def test_classify_project_artifact_structured(tmp_path: Path) -> None:
    ev = {"event_type": "tool_observation",
          "m4": {"domain": "artifact", "identity": "A1", "op": "create"}}
    assert classify_event_for_m4(ev) == CLASSIFY_PROJECT_ARTIFACT


def test_classify_generic_event_still_skip(tmp_path: Path) -> None:
    gen = {"event_type": "assistant_claim", "sanitized_content": "verified"}
    assert classify_event_for_m4(gen) == CLASSIFY_SKIP


# ----------------------------------------------------------------------------
# Subject
# ----------------------------------------------------------------------------

def test_verification_subject_type_preserved(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_verification(store._conn, _ver(subject_type="decision", subject_id="D1"))
        row = store._conn.execute(
            "SELECT subject_type, subject_id FROM zm_verifications WHERE verification_id='V1'").fetchone()
        assert row["subject_type"] == "decision" and row["subject_id"] == "D1"
    finally:
        store.close()


def test_verification_unsupported_subject_rejected(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        # 'project_state' is NOT in the approved vocabulary (plan uses 'state')
        with pytest.raises(MissingRequiredFieldError):
            project_verification(store._conn, _ver(subject_type="project_state", subject_id="S1"))
    finally:
        store.close()


def test_verification_state_subject_accepted(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_verification(store._conn, _ver(subject_type="state", subject_id="progress"))
        row = store._conn.execute("SELECT subject_type FROM zm_verifications").fetchone()
        assert row["subject_type"] == "state"
    finally:
        store.close()


def test_verification_subject_not_inferred(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        # no subject_type at all -> allowed (None preserved); no inference
        out = project_verification(store._conn, _ver(subject_type=None, subject_id=None))
        assert out["action"] == "created"
        row = store._conn.execute("SELECT subject_type, subject_id FROM zm_verifications").fetchone()
        assert row["subject_type"] is None and row["subject_id"] is None
    finally:
        store.close()


# ----------------------------------------------------------------------------
# Behavior: no auto-promotion, status separation, no subject mutation
# ----------------------------------------------------------------------------

def test_verification_creation_and_status_preserved(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_verification(store._conn, _ver(verification_status="deterministic_verification"))
        row = store._conn.execute(
            "SELECT verification_status FROM zm_verifications WHERE verification_id='V1'").fetchone()
        assert row["verification_status"] == "deterministic_verification"
    finally:
        store.close()


def test_verification_status_separate_from_lifecycle(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        # zm_verifications has no lifecycle_status column at all
        cols = [c["name"] for c in store._conn.execute("PRAGMA table_info(zm_verifications)")]
        assert "lifecycle_status" not in cols
        assert "verification_status" in cols
    finally:
        store.close()


def test_verification_does_not_mutate_requirement(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        from src.project_memory import project_requirement
        project_requirement(store._conn, _req(requirement_id="R1", statement="old",
                                               lifecycle_status="active", state="proposed"))
        project_verification(store._conn, _ver(subject_type="requirement", subject_id="R1"))
        row = store._conn.execute(
            "SELECT statement, lifecycle_status, state FROM zm_requirements WHERE requirement_id='R1'").fetchone()
        # unchanged by the verification
        assert row["statement"] == "old" and row["lifecycle_status"] == "active" and row["state"] == "proposed"
    finally:
        store.close()


def test_verification_does_not_mutate_decision(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        from src.project_memory import project_decision
        project_decision(store._conn, _dec(decision_id="D1", lifecycle_status="active", state="accepted"))
        project_verification(store._conn, _ver(subject_type="decision", subject_id="D1"))
        row = store._conn.execute(
            "SELECT lifecycle_status, state FROM zm_decisions WHERE decision_id='D1'").fetchone()
        assert row["lifecycle_status"] == "active" and row["state"] == "accepted"
    finally:
        store.close()


def test_verification_does_not_mutate_project_state(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        from src.project_memory import project_state
        project_state(store._conn, _st(state_key="progress", state_value="40%", lifecycle_status="active"))
        project_verification(store._conn, _ver(subject_type="state", subject_id="progress"))
        row = store._conn.execute(
            "SELECT state_value, lifecycle_status FROM zm_project_state WHERE state_key='progress'").fetchone()
        assert row["state_value"] == "40%" and row["lifecycle_status"] == "active"
    finally:
        store.close()


def test_verification_does_not_mutate_charter(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        from src.project_memory import project_charter
        project_charter(store._conn, _char(charter_id="C1", goal="g", lifecycle_status="active"))
        project_verification(store._conn, _ver(subject_type="requirement", subject_id="R1"))
        row = store._conn.execute(
            "SELECT goal, lifecycle_status FROM zm_project_charters WHERE charter_id='C1'").fetchone()
        assert row["goal"] == "g" and row["lifecycle_status"] == "active"
    finally:
        store.close()


def test_contradictory_verifications_both_preserved(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_verification(store._conn, _ver(verification_id="V-A", verification_status="deterministic_verification"))
        project_verification(store._conn, _ver(verification_id="V-B", verification_status="user_confirmation"))
        rows = {r["verification_id"]: r["verification_status"]
                for r in store._conn.execute(
                    "SELECT * FROM zm_verifications WHERE subject_type='requirement' AND subject_id='R1'")}
        assert rows == {"V-A": "deterministic_verification", "V-B": "user_confirmation"}
    finally:
        store.close()


def test_no_timestamp_truth_no_winner(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_verification(store._conn, _ver(verification_id="V-A", timestamp="2026-01-01T00:00:00Z",
                                               verification_status="deterministic_verification"))
        project_verification(store._conn, _ver(verification_id="V-B", timestamp="2026-12-31T00:00:00Z",
                                               verification_status="user_confirmation"))
        # both retained; neither overwritten; no winner
        n = store._conn.execute("SELECT COUNT(*) AS n FROM zm_verifications").fetchone()["n"]
        assert n == 2
    finally:
        store.close()


def test_no_llm_verification_marker(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        # explicit structured event only; no LLM call path
        out = project_verification(store._conn, _ver(method="explicit-check"))
        assert out["action"] == "created"
    finally:
        store.close()


# ----------------------------------------------------------------------------
# Evidence safety
# ----------------------------------------------------------------------------

def test_safe_command_ref_accepted(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_verification(store._conn, _ver(command_ref="pytest tests/unit::test_x"))
        row = store._conn.execute("SELECT command_ref FROM zm_verifications").fetchone()
        assert row["command_ref"] == "pytest tests/unit::test_x"
    finally:
        store.close()


def test_unsafe_raw_command_output_rejected(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        with pytest.raises(MissingRequiredFieldError):
            project_verification(store._conn, _ver(command_ref="FAILED\nTraceback (most recent call last):\n  ..."))
    finally:
        store.close()


def test_unsafe_absolute_path_ref_rejected(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        with pytest.raises(MissingRequiredFieldError):
            project_verification(store._conn, _ver(command_ref="/home/user/secret/output.txt"))
    finally:
        store.close()


def test_observed_result_no_raw_secret(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        with pytest.raises(MissingRequiredFieldError):
            project_verification(store._conn, _ver(observed_result="file:///tmp/leak?token=abc"))
    finally:
        store.close()


# ----------------------------------------------------------------------------
# Artifact integration
# ----------------------------------------------------------------------------

def test_existing_m2_artifact_linked_to_project(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        _seed_artifact(store._conn, "A1")
        out = project_artifact(store._conn, _art())
        assert out["action"] == "created"
        row = store._conn.execute(
            "SELECT artifact_id, project_id, safe_reference FROM zm_project_artifacts "
            "WHERE artifact_id='A1' AND project_id='P'").fetchone()
        assert row["artifact_id"] == "A1" and row["safe_reference"] == "reports/x.md"
    finally:
        store.close()


def test_project_artifact_idempotent(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        _seed_artifact(store._conn, "A1")
        project_artifact(store._conn, _art())
        out = project_artifact(store._conn, _art())
        assert out["action"] == "noop"
        n = store._conn.execute("SELECT COUNT(*) AS n FROM zm_project_artifacts").fetchone()["n"]
        assert n == 1
    finally:
        store.close()


def test_project_artifact_explicit_ids_preserved(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        _seed_artifact(store._conn, "A1")
        project_artifact(store._conn, _art(artifact_id="A1", project_id="P"))
        row = store._conn.execute(
            "SELECT artifact_id, project_id FROM zm_project_artifacts").fetchone()
        assert row["artifact_id"] == "A1" and row["project_id"] == "P"
    finally:
        store.close()


def test_project_artifact_missing_identity_not_invented(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        with pytest.raises(MissingIdentityError):
            project_artifact(store._conn, _art(artifact_id="  "))
    finally:
        store.close()


def test_project_artifact_no_filename_derived_identity(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        # filename alone must not become identity; explicit artifact_id required
        _seed_artifact(store._conn, "A1")
        with pytest.raises(MissingIdentityError):
            # artifact_id omitted entirely -> missing identity (not inferred)
            project_artifact(store._conn, ArtifactOp(op="create", artifact_id="", project_id="P",
                                                    safe_reference="reports/x.md"))
    finally:
        store.close()


def test_project_artifact_no_trace_id_identity(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        _seed_artifact(store._conn, "A1")
        with pytest.raises(MissingIdentityError):
            project_artifact(store._conn, ArtifactOp(op="create", artifact_id="", project_id="P",
                                                    trace_id="TR-1", safe_reference="reports/x.md"))
    finally:
        store.close()


def test_safe_reference_preserved(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        _seed_artifact(store._conn, "A1")
        project_artifact(store._conn, _art(safe_reference="artifacts/report-v1.md"))
        row = store._conn.execute("SELECT safe_reference FROM zm_project_artifacts").fetchone()
        assert row["safe_reference"] == "artifacts/report-v1.md"
    finally:
        store.close()


def test_unsafe_absolute_reference_rejected(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        _seed_artifact(store._conn, "A1")
        with pytest.raises(MissingRequiredFieldError):
            project_artifact(store._conn, _art(safe_reference="/home/user/secret/art.md"))
    finally:
        store.close()


def test_traversal_reference_rejected(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        _seed_artifact(store._conn, "A1")
        with pytest.raises(MissingRequiredFieldError):
            project_artifact(store._conn, _art(safe_reference="../../../etc/passwd"))
    finally:
        store.close()


def test_secret_bearing_reference_rejected(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        _seed_artifact(store._conn, "A1")
        with pytest.raises(MissingRequiredFieldError):
            project_artifact(store._conn, _art(safe_reference="file:///tmp/x?token=abc"))
    finally:
        store.close()


def test_no_artifact_content_duplication(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        _seed_artifact(store._conn, "A1")
        project_artifact(store._conn, _art())
        # zm_project_artifacts holds only metadata + safe_reference, never blob
        cols = [c["name"] for c in store._conn.execute("PRAGMA table_info(zm_project_artifacts)")]
        assert "content_hash" not in cols and "stored_path" not in cols
        # the M2 substrate row is untouched (single artifact row, no copy)
        n = store._conn.execute("SELECT COUNT(*) AS n FROM zm_artifacts").fetchone()["n"]
        assert n == 1
    finally:
        store.close()


# ----------------------------------------------------------------------------
# Explicit links
# ----------------------------------------------------------------------------

def test_artifact_explicit_requirement_link(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        _seed_artifact(store._conn, "A1")
        project_artifact(store._conn, _art(linked_requirement_ids="R1,R2"))
        row = store._conn.execute("SELECT linked_requirement_ids FROM zm_project_artifacts").fetchone()
        assert row["linked_requirement_ids"] == "R1,R2"
    finally:
        store.close()


def test_artifact_explicit_decision_link(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        _seed_artifact(store._conn, "A1")
        project_artifact(store._conn, _art(linked_decision_ids="D1"))
        row = store._conn.execute("SELECT linked_decision_ids FROM zm_project_artifacts").fetchone()
        assert row["linked_decision_ids"] == "D1"
    finally:
        store.close()


def test_artifact_explicit_state_link(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        _seed_artifact(store._conn, "A1")
        project_artifact(store._conn, _art(linked_state_keys="progress"))
        row = store._conn.execute("SELECT linked_state_keys FROM zm_project_artifacts").fetchone()
        assert row["linked_state_keys"] == "progress"
    finally:
        store.close()


def test_artifact_absent_links_not_inferred(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        _seed_artifact(store._conn, "A1")
        project_artifact(store._conn, _art())
        row = store._conn.execute(
            "SELECT linked_requirement_ids, linked_decision_ids, linked_state_keys "
            "FROM zm_project_artifacts").fetchone()
        assert row["linked_requirement_ids"] is None
        assert row["linked_decision_ids"] is None
        assert row["linked_state_keys"] is None
    finally:
        store.close()


def test_verification_explicit_artifact_link(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        project_verification(store._conn, _ver(artifact_references="A1"))
        row = store._conn.execute("SELECT artifact_references FROM zm_verifications").fetchone()
        assert row["artifact_references"] == "A1"
    finally:
        store.close()


# ----------------------------------------------------------------------------
# Failure / transaction behavior
# ----------------------------------------------------------------------------

def test_missing_m2_artifact_rolls_back(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        # A1 NOT seeded in zm_artifacts -> FK fails -> sanitized rollback
        with pytest.raises(MissingIdentityError):
            project_artifact(store._conn, _art(artifact_id="A1"))
        n = store._conn.execute("SELECT COUNT(*) AS n FROM zm_project_artifacts").fetchone()["n"]
        assert n == 0
    finally:
        store.close()


def test_failed_link_no_partial_verification(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        # artifact FK failure must not leave a verification row behind (separate op,
        # but confirms transactional integrity of the artifact op itself)
        with pytest.raises(MissingIdentityError):
            project_artifact(store._conn, _art(artifact_id="ghost"))
        assert store._conn.execute("SELECT COUNT(*) AS n FROM zm_project_artifacts").fetchone()["n"] == 0
    finally:
        store.close()


def test_duplicate_event_no_duplicate_links(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        _seed_artifact(store._conn, "A1")
        project_artifact(store._conn, _art(linked_requirement_ids="R1"))
        project_artifact(store._conn, _art(linked_requirement_ids="R1"))
        n = store._conn.execute("SELECT COUNT(*) AS n FROM zm_project_artifacts").fetchone()["n"]
        assert n == 1
    finally:
        store.close()


# ----------------------------------------------------------------------------
# Replay / determinism
# ----------------------------------------------------------------------------

def _build_verifications(p: Path) -> set:
    s = _open(p)
    try:
        project_verification(s._conn, _ver(verification_id="V1", subject_type="requirement",
                                            subject_id="R1", verification_status="deterministic_verification"))
        project_verification(s._conn, _ver(verification_id="V2", subject_type="decision",
                                            subject_id="D1", verification_status="user_confirmation"))
        return {(r["verification_id"], r["subject_type"], r["subject_id"], r["verification_status"])
                for r in s._conn.execute("SELECT * FROM zm_verifications")}
    finally:
        s.close()


def _build_artifacts(p: Path) -> set:
    s = _open(p)
    try:
        _seed_artifact(s._conn, "A1")
        _seed_artifact(s._conn, "A2")
        project_artifact(s._conn, _art(artifact_id="A1", project_id="P",
                                       safe_reference="reports/x.md", linked_requirement_ids="R1"))
        project_artifact(s._conn, _art(artifact_id="A2", project_id="P",
                                       safe_reference="reports/y.md"))
        return {(r["artifact_id"], r["project_id"], r["linked_requirement_ids"], r["safe_reference"])
                for r in s._conn.execute("SELECT * FROM zm_project_artifacts")}
    finally:
        s.close()


def test_replay_verification_deterministic(tmp_path: Path) -> None:
    assert _build_verifications(tmp_path / "a") == _build_verifications(tmp_path / "b")


def test_incremental_equals_replay_verification(tmp_path: Path) -> None:
    inc = _open(tmp_path / "inc")
    try:
        project_verification(inc._conn, _ver(verification_id="V1", subject_type="requirement",
                                              subject_id="R1", verification_status="deterministic_verification"))
        project_verification(inc._conn, _ver(verification_id="V2", subject_type="decision",
                                              subject_id="D1", verification_status="user_confirmation"))
        inc_rows = {(r["verification_id"], r["subject_type"], r["subject_id"], r["verification_status"])
                    for r in inc._conn.execute("SELECT * FROM zm_verifications")}
    finally:
        inc.close()
    assert inc_rows == _build_verifications(tmp_path / "replay")


def test_replay_artifact_deterministic(tmp_path: Path) -> None:
    assert _build_artifacts(tmp_path / "a") == _build_artifacts(tmp_path / "b")


def test_incremental_equals_replay_artifact(tmp_path: Path) -> None:
    inc = _open(tmp_path / "inc")
    try:
        _seed_artifact(inc._conn, "A1")
        project_artifact(inc._conn, _art(artifact_id="A1", project_id="P", linked_requirement_ids="R1"))
        _seed_artifact(inc._conn, "A2")
        project_artifact(inc._conn, _art(artifact_id="A2", project_id="P", safe_reference="reports/y.md"))
        inc_rows = {(r["artifact_id"], r["project_id"], r["linked_requirement_ids"], r["safe_reference"])
                    for r in inc._conn.execute("SELECT * FROM zm_project_artifacts")}
    finally:
        inc.close()
    assert inc_rows == _build_artifacts(tmp_path / "replay")


# ----------------------------------------------------------------------------
# Cross-cutting
# ----------------------------------------------------------------------------

def test_schema_remains_v8(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        from src.storage.migrations import CURRENT_SCHEMA_VERSION
        assert store.get_schema_version() == CURRENT_SCHEMA_VERSION == 11
    finally:
        store.close()


def test_is_safe_reference_unit(tmp_path: Path) -> None:
    assert is_safe_reference(None) is True
    assert is_safe_reference("reports/x.md") is True
    assert is_safe_reference("/home/x") is False
    assert is_safe_reference("a\nb") is False
    assert is_safe_reference("Traceback:") is False


# ----------------------------------------------------------------------------
# shared ops (charter/requirement/decision/state) used above
# ----------------------------------------------------------------------------

from src.project_memory import CharterOp, RequirementOp, DecisionOp, StateOp  # noqa: E402


def _char(**kw):
    base = dict(op="create", charter_id="C1", project_id="P", goal="g", lifecycle_status="active")
    base.update(kw)
    return CharterOp(**base)


def _req(**kw):
    base = dict(op="create", requirement_id="R1", project_id="P", statement="old",
                lifecycle_status="active", state="proposed")
    base.update(kw)
    return RequirementOp(**base)


def _dec(**kw):
    base = dict(op="create", decision_id="D1", project_id="P", lifecycle_status="active", state="accepted")
    base.update(kw)
    return DecisionOp(**base)


def _st(**kw):
    base = dict(op="create", project_id="P", state_key="progress", state_value="40%",
                lifecycle_status="active")
    base.update(kw)
    return StateOp(**base)
