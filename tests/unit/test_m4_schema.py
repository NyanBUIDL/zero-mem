"""M4.1 focused tests: project-memory contracts and schema/migration v7.

Covers only M4.1 (deterministic schema foundation + corrected key semantics).
No Charter/Requirement/Decision/State projection logic. All tests use temporary
directories; none write to the real ~/.hermes. No LLM or network calls.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from src.storage.migrations import CURRENT_SCHEMA_VERSION, MIGRATIONS, migrate_7, migrate_8
from src.storage.sqlite_store import (
    SQLiteStore,
    SQLiteStoreConfig,
    MigrationError,
)

# Closed lifecycle enum (authoritative master spec §7.1).
LIFECYCLE_ENUM = {
    "raw", "observed", "candidate", "confirmed", "active",
    "superseded", "conflicted", "archived", "deleted",
}
# Domain states that MUST NOT appear in lifecycle_status.
DOMAIN_STATES = {"proposed", "accepted", "satisfied", "blocked", "rejected"}

M4_TABLES = [
    "zm_project_charters",
    "zm_requirements",
    "zm_decisions",
    "zm_project_state",
    "zm_verifications",
    "zm_project_artifacts",
]
M4_INDEXES = [
    "idx_zm_charters_project",
    "uq_zm_charters_active",
    "idx_zm_requirements_project",
    "idx_zm_decisions_project",
    "idx_zm_decisions_scope",
    "uq_zm_decisions_active",
    "idx_zm_project_state_project",
    "idx_zm_project_state_key",
    "uq_zm_project_state_active",
    "idx_zm_verifications_subject",
    "idx_zm_verifications_project",
    "idx_zm_project_artifacts_project",
]


def _config(tmp_path: Path, name: str = "meta.sqlite") -> SQLiteStoreConfig:
    return SQLiteStoreConfig(path=tmp_path / name)


def _open(tmp_path: Path, name: str = "meta.sqlite") -> SQLiteStore:
    store = SQLiteStore(_config(tmp_path, name))
    store.ensure_schema()
    # Enable FK enforcement for the connection under test.
    store._conn.execute("PRAGMA foreign_keys=ON")
    return store


def _insert(conn: sqlite3.Connection, table: str, **kw) -> None:
    cols = list(kw.keys())
    placeholders = ", ".join("?" for _ in cols)
    conn.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
        [kw[c] for c in cols],
    )


# ---- 1. migration registry v7 -------------------------------------------------

def test_migration_registry_v8() -> None:
    assert 8 in MIGRATIONS
    assert CURRENT_SCHEMA_VERSION == 10
    assert MIGRATIONS[8] is migrate_8
    # Deterministic ascending ordering.
    assert list(MIGRATIONS) == sorted(MIGRATIONS)


# ---- 2. v6 -> v8 --------------------------------------------------------------

def test_v6_to_v8_upgrade(tmp_path: Path) -> None:
    store = SQLiteStore(_config(tmp_path))
    try:
        assert store.get_schema_version() == 0
        v = store.ensure_schema()
        assert v == 10
        assert store.get_schema_version() == 10
        # Ledger rows present for every applied migration (1..CURRENT).
        cur = store._conn.cursor()
        cur.execute("SELECT version FROM zm_migrations ORDER BY version")
        assert [r["version"] for r in cur.fetchall()] == list(
            range(1, CURRENT_SCHEMA_VERSION + 1)
        )
    finally:
        store.close()


def test_all_six_m4_tables_exist(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        for t in M4_TABLES:
            assert store.table_exists(t), f"missing table {t}"
    finally:
        store.close()


def test_expected_indexes_exist(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        for idx in M4_INDEXES:
            assert store.index_exists(idx), f"missing index {idx}"
    finally:
        store.close()


# ---- 3. v7 reopen idempotence -------------------------------------------------

def test_v8_reopen_idempotent(tmp_path: Path) -> None:
    store = _open(tmp_path)
    store.close()
    # Reopen the already-migrated DB: ledger persists on disk, version stays 8.
    store2 = SQLiteStore(_config(tmp_path))
    try:
        assert store2.get_schema_version() == 10
        v = store2.ensure_schema()
        assert v == 10
        # No duplicate tables / double migration leds.
        cur = store2._conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM zm_migrations WHERE version=8")
        assert cur.fetchone()["n"] == 1
        for t in M4_TABLES:
            assert store2.table_exists(t)
    finally:
        store2.close()


# ---- 4. v7 -> v6 downgrade ----------------------------------------------------

def test_v8_to_v7_downgrade(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        assert store.get_schema_version() == 10
        store.downgrade_to(7)
        assert store.get_schema_version() == 7
        # M5.4 derived tables dropped by the one-step downgrade.
        assert not store.table_exists("zm_access_grants")
        assert not store.table_exists("zm_policy_audit")
        # M4 tables must survive the downgrade (still at v7).
        for t in M4_TABLES:
            assert store.table_exists(t), f"M4 table {t} should survive"
        # M2 tables must survive the downgrade.
        assert store.table_exists("zm_meta")
        assert store.table_exists("zm_artifacts")
        assert store.table_exists("zm_lifecycle")
        assert store.table_exists("zm_tombstones")
    finally:
        store.close()


def test_downgrade_rejects_unknown_and_negative(tmp_path: Path) -> None:
    # Self-contained: fresh store; authoritative current version from the registry.
    from src.storage.migrations import CURRENT_SCHEMA_VERSION as CSV
    store = _open(tmp_path)
    try:
        # Unknown/negative downgrade targets are refused with a sanitized error.
        with pytest.raises(Exception) as exc:
            store.downgrade_to(99)  # above current -> not supported
        assert "downgrade_not_supported" in str(exc.value)
        with pytest.raises(Exception) as exc2:
            store.downgrade_to(-1)  # negative
        assert "downgrade_negative" in str(exc2.value)
        # Downgrade to one below current is allowed (sanity of the gate).
        store.downgrade_to(CSV - 1)
        assert store.get_schema_version() == CSV - 1
    finally:
        store.close()
        # Restore v7 so later tests see a clean current schema.
        s2 = SQLiteStore(_config(tmp_path))
        try:
            s2.ensure_schema()
        finally:
            s2.close()


# ---- 5. failed migration rollback + unknown future rejection -------------------

def test_failed_migration_rolls_back(tmp_path: Path, monkeypatch) -> None:
    # Self-contained: snapshot the registry, force migration 7's up() to fail,
    # assert rollback (version unchanged, no v7 tables), then restore registry
    # so no global leak escapes this test.
    from src.storage import migrations as reg

    snapshot = dict(reg.MIGRATIONS)
    try:
        def _boom(conn, note):  # type: ignore[no-untyped-def]
            raise MigrationError("synthetic migration failure")

        monkeypatch.setattr(reg.MIGRATIONS[7], "up", _boom)
        store = SQLiteStore(_config(tmp_path))
        try:
            assert store.get_schema_version() == 0
            with pytest.raises(Exception) as exc:
                store.ensure_schema()
            # Framework surfaces a sanitized apply-up failure (no partial advance).
            assert "apply_up_failed" in str(exc.value)
            assert "migration_error" in str(exc.value)
            assert store.get_schema_version() == 6
            assert not store.table_exists("zm_decisions")
        finally:
            store.close()
    finally:
        reg.MIGRATIONS = snapshot


def test_unknown_future_schema_rejected(tmp_path: Path) -> None:
    # Craft a DB recorded one version ABOVE the code's CURRENT_SCHEMA_VERSION.
    future = CURRENT_SCHEMA_VERSION + 1
    store = SQLiteStore(_config(tmp_path))
    try:
        store.ensure_schema()  # -> CURRENT_SCHEMA_VERSION
        store._conn.execute(
            "INSERT INTO zm_migrations(version, applied_at, note) VALUES (?,'t','fake')",
            (future,),
        )
        store._conn.commit()
    finally:
        store.close()  # close first connection before reopening (avoid WAL cross-connection race)
    reopen = SQLiteStore(_config(tmp_path))
    try:
        with pytest.raises(Exception) as exc:
            reopen.ensure_schema()
        assert "unknown_future_version" in str(exc.value)
    finally:
        reopen.close()


def test_downgrade_does_not_touch_jsonl(tmp_path: Path) -> None:
    # No JSONL is created or modified by migration (canonical source untouched).
    store = _open(tmp_path)
    store.close()
    jsonl_files = list(tmp_path.glob("*.jsonl"))
    assert jsonl_files == [], "migration must not create JSONL"


# ---- 6. lifecycle CHECK vs domain state --------------------------------------

def test_lifecycle_check_accepts_enum(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        conn = store._conn
        for val in LIFECYCLE_ENUM:
            _insert(
                conn, "zm_decisions",
                decision_id=f"d-{val}", project_id="P", lifecycle_status=val,
                state="accepted",
            )
        # All accepted.
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM zm_decisions")
        assert cur.fetchone()["n"] == len(LIFECYCLE_ENUM)
    finally:
        store.close()


def test_lifecycle_check_rejects_domain_states(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        conn = store._conn
        for bad in DOMAIN_STATES:
            with pytest.raises(sqlite3.IntegrityError):
                _insert(
                    conn, "zm_decisions",
                    decision_id=f"d-{bad}", project_id="P", lifecycle_status=bad,
                )
    finally:
        store.close()


def test_generic_state_accepts_domain_values(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        conn = store._conn
        # Domain state goes in `state`, not lifecycle_status; both accepted.
        for dom in ("proposed", "accepted", "satisfied", "blocked", "rejected"):
            _insert(
                conn, "zm_decisions",
                decision_id=f"d-{dom}", project_id="P", lifecycle_status="candidate",
                state=dom,
            )
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM zm_decisions WHERE state IN "
                    "('proposed','accepted','satisfied','blocked','rejected')")
        assert cur.fetchone()["n"] == len(DOMAIN_STATES)
    finally:
        store.close()


# ---- 7 + 8. decision_key / state_key NULL + no trace_id fallback ---------------

def test_explicit_decision_key_stored_unchanged(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        conn = store._conn
        _insert(conn, "zm_decisions", decision_id="d1", project_id="P",
                scope="scope-a", decision_key="dk-1", lifecycle_status="active",
                state="accepted", trace_id="T-does-NOT-become-key")
        row = conn.execute(
            "SELECT decision_key, trace_id FROM zm_decisions WHERE decision_id='d1'"
        ).fetchone()
        assert row["decision_key"] == "dk-1"
        assert row["trace_id"] == "T-does-NOT-become-key"
        assert row["decision_key"] != row["trace_id"]
    finally:
        store.close()


def test_missing_decision_key_remains_null(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        conn = store._conn
        _insert(conn, "zm_decisions", decision_id="d1", project_id="P",
                lifecycle_status="active", state="accepted", trace_id="T1")
        row = conn.execute(
            "SELECT decision_key FROM zm_decisions WHERE decision_id='d1'"
        ).fetchone()
        assert row["decision_key"] is None  # NOT derived from trace_id
    finally:
        store.close()


def test_explicit_state_key_stored_unchanged(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        conn = store._conn
        _insert(conn, "zm_project_state", project_id="P", scope="project:P",
                state_key="schema_version", state_value="7", lifecycle_status="active",
                trace_id="T-does-NOT-become-key")
        row = conn.execute(
            "SELECT state_key, trace_id FROM zm_project_state WHERE project_id='P'"
        ).fetchone()
        assert row["state_key"] == "schema_version"
        assert row["trace_id"] == "T-does-NOT-become-key"
    finally:
        store.close()


def test_missing_state_key_remains_null(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        conn = store._conn
        _insert(conn, "zm_project_state", project_id="P", scope="project:P",
                state_value="x", lifecycle_status="active", trace_id="T1")
        row = conn.execute(
            "SELECT state_key FROM zm_project_state WHERE project_id='P'"
        ).fetchone()
        assert row["state_key"] is None  # NOT derived from trace_id
    finally:
        store.close()


# ---- 9. active-decision uniqueness (non-NULL key only) ------------------------

def test_two_active_same_decision_key_rejected(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        conn = store._conn
        _insert(conn, "zm_decisions", decision_id="a", project_id="P",
                scope="s", decision_key="dk", lifecycle_status="active", state="accepted")
        with pytest.raises(sqlite3.IntegrityError):
            _insert(conn, "zm_decisions", decision_id="b", project_id="P",
                    scope="s", decision_key="dk", lifecycle_status="active", state="accepted")
    finally:
        store.close()


def test_two_active_different_decision_key_allowed(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        conn = store._conn
        _insert(conn, "zm_decisions", decision_id="a", project_id="P",
                scope="s", decision_key="dk1", lifecycle_status="active", state="accepted")
        _insert(conn, "zm_decisions", decision_id="b", project_id="P",
                scope="s", decision_key="dk2", lifecycle_status="active", state="accepted")
        assert conn.execute("SELECT COUNT(*) AS n FROM zm_decisions").fetchone()["n"] == 2
    finally:
        store.close()


def test_multiple_null_decision_key_active_allowed(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        conn = store._conn
        for i in range(3):
            _insert(conn, "zm_decisions", decision_id=f"n{i}", project_id="P",
                    lifecycle_status="active", state="accepted")  # decision_key NULL
        assert conn.execute("SELECT COUNT(*) AS n FROM zm_decisions").fetchone()["n"] == 3
    finally:
        store.close()


def test_historical_non_active_rows_do_not_violate(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        conn = store._conn
        # Two rows with the SAME decision_key but only one active: allowed.
        _insert(conn, "zm_decisions", decision_id="old", project_id="P",
                scope="s", decision_key="dk", lifecycle_status="superseded", state="superseded")
        _insert(conn, "zm_decisions", decision_id="new", project_id="P",
                scope="s", decision_key="dk", lifecycle_status="active", state="accepted")
        assert conn.execute("SELECT COUNT(*) AS n FROM zm_decisions").fetchone()["n"] == 2
    finally:
        store.close()


# ---- 10. active-state uniqueness (non-NULL key only) --------------------------

def test_two_active_same_state_key_rejected(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        conn = store._conn
        _insert(conn, "zm_project_state", project_id="P", scope="project:P",
                state_key="sv", state_value="1", lifecycle_status="active")
        with pytest.raises(sqlite3.IntegrityError):
            _insert(conn, "zm_project_state", project_id="P", scope="project:P",
                    state_key="sv", state_value="2", lifecycle_status="active")
    finally:
        store.close()


def test_different_state_key_allowed(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        conn = store._conn
        _insert(conn, "zm_project_state", project_id="P", scope="project:P",
                state_key="sv1", state_value="1", lifecycle_status="active")
        _insert(conn, "zm_project_state", project_id="P", scope="project:P",
                state_key="sv2", state_value="2", lifecycle_status="active")
        assert conn.execute("SELECT COUNT(*) AS n FROM zm_project_state").fetchone()["n"] == 2
    finally:
        store.close()


def test_multiple_null_state_key_active_allowed(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        conn = store._conn
        for i in range(3):
            _insert(conn, "zm_project_state", project_id="P", scope="project:P",
                    state_value=f"v{i}", lifecycle_status="active")  # state_key NULL
        assert conn.execute("SELECT COUNT(*) AS n FROM zm_project_state").fetchone()["n"] == 3
    finally:
        store.close()


# ---- 11. explicit supersession FK behavior ------------------------------------

def test_supersession_fk_self_reference(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        conn = store._conn
        conn.execute("PRAGMA foreign_keys=ON")
        _insert(conn, "zm_decisions", decision_id="a", project_id="P",
                lifecycle_status="superseded", state="superseded")
        # supersedes_id references an EXISTING row -> allowed.
        _insert(conn, "zm_decisions", decision_id="b", project_id="P",
                lifecycle_status="active", state="accepted", supersedes_id="a")
        # supersedes_id references a NON-EXISTENT row -> FK violation.
        with pytest.raises(sqlite3.IntegrityError):
            _insert(conn, "zm_decisions", decision_id="c", project_id="P",
                    lifecycle_status="active", state="accepted", supersedes_id="ghost")
    finally:
        store.close()


def test_expected_fk_definitions_present(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        conn = store._conn
        # zm_project_artifacts -> zm_artifacts
        fks = conn.execute(
            "PRAGMA foreign_key_list(zm_project_artifacts)"
        ).fetchall()
        targets = {(r["table"], r["to"]) for r in fks}
        assert ("zm_artifacts", "artifact_id") in targets
        # zm_decisions self-FK on supersedes_id
        dfks = conn.execute("PRAGMA foreign_key_list(zm_decisions)").fetchall()
        dtables = {(r["table"], r["from"]) for r in dfks}
        assert ("zm_decisions", "supersedes_id") in dtables
    finally:
        store.close()


# ---- 12. verification schema --------------------------------------------------

def test_verification_record_structure(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        conn = store._conn
        _insert(conn, "zm_verifications",
                verification_id="v1", subject_type="requirement", subject_id="r1",
                project_id="P", method="pytest", command_ref="pytest tests/",
                observed_result="617 passed, 3 skipped", tested_commit="abc123",
                source_event_id="e1", timestamp="2026-08-07T00:00:00Z",
                verification_status="deterministic_verification",
                artifact_references="art-1")
        row = conn.execute(
            "SELECT subject_type, tested_commit, verification_status FROM zm_verifications "
            "WHERE verification_id='v1'"
        ).fetchone()
        assert row["subject_type"] == "requirement"
        assert row["tested_commit"] == "abc123"
        assert row["verification_status"] == "deterministic_verification"
    finally:
        store.close()


# ---- 13. artifact linkage schema (reuse M2 zm_artifacts) -----------------------

def test_project_artifact_linkage(tmp_path: Path) -> None:
    store = _open(tmp_path)
    try:
        conn = store._conn
        conn.execute("PRAGMA foreign_keys=ON")
        # Seed an M2 artifact row (the referenced substrate).
        conn.execute(
            "INSERT INTO zm_artifacts(artifact_id, content_hash, kind, retention, "
            "created_at) VALUES (?,?,?,?,?)",
            ("art-1", "h1", "report", "persistent", "2026-08-07T00:00:00Z"),
        )
        _insert(conn, "zm_project_artifacts", artifact_id="art-1", project_id="P",
                artifact_type="report", version="1", safe_reference="reports/x.md",
                source_event_id="e1", created_at="2026-08-07T00:00:00Z")
        # FK violation if artifact_id absent from zm_artifacts.
        with pytest.raises(sqlite3.IntegrityError):
            _insert(conn, "zm_project_artifacts", artifact_id="ghost", project_id="P",
                    created_at="2026-08-07T00:00:00Z")
    finally:
        store.close()


# ---- 14. no M4.2 projection / no M5 / no LLM / no network ---------------------

def test_no_projection_logic_in_migration_module() -> None:
    # M4.1 must not contain projector/business logic names.
    src = open(migrate_7.__file__, "r", encoding="utf-8").read()
    for forbidden in ("def project", "def ingest", "def reduce", "def promote",
                      "def resolve_conflict", "def accept_decision"):
        assert forbidden not in src, f"unexpected logic in migrate_7: {forbidden}"


def test_no_llm_or_network_imports() -> None:
    src = open(migrate_7.__file__, "r", encoding="utf-8").read()
    for forbidden in ("import openai", "import requests", "import http",
                      "import aiohttp", "urllib.request", "socket.socket"):
        assert forbidden not in src, f"forbidden import in migrate_7: {forbidden}"


def test_no_m5_authorization_logic() -> None:
    src = open(migrate_7.__file__, "r", encoding="utf-8").read()
    for forbidden in ("authorize", "access_policy", "isolation_mode",
                      "cross_profile", "grant_read", "enforce_scope"):
        assert forbidden not in src, f"M5 behavior leaked into M4.1: {forbidden}"


def test_no_real_hermes_home_writes(tmp_path: Path) -> None:
    # The store is created only under tmp_path; real HOME must be untouched.
    store = _open(tmp_path)
    store.close()
    real_home = Path(os.path.expanduser("~"))
    # No sqlite created directly under real HOME root by this test.
    assert not (real_home / "meta.sqlite").exists()
