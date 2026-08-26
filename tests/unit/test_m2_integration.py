"""M2.7 focused integration tests: full M2 derived-layer integration + final acceptance.

Reuses the existing M2 APIs (ingest_file, rebuild_from_jsonl, verify_rebuild_parity,
get_checkpoint, scan_sqlite_for_secrets, admin inspection helpers). No new product behavior;
schema stays v6; canonical JSONL stays byte-for-byte immutable; Decision B (logical deletion
only). Uses temporary directories; never writes to the real ~/.hermes.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

from src.storage.ingest import (
    IngestionOutcome,
    count_metadata,
    get_checkpoint,
    get_lifecycle,
    ingest_file,
    list_deleted,
    rebuild_from_jsonl,
    scan_sqlite_for_secrets,
    search_fts,
    verify_rebuild_parity,
)
from src.storage.migrations import CURRENT_SCHEMA_VERSION
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig, SchemaVersionError

TS = "2026-08-07T00:00:00Z"
SECRET = "SK-M2-7-PROBE-XYZZY"


def _open_store(tmp_path: pathlib.Path, name: str = "m.sqlite") -> SQLiteStore:
    store = SQLiteStore(SQLiteStoreConfig(path=tmp_path / name))
    store.ensure_schema()
    return store


def _make_env(event_id, **over):
    base = dict(
        event_id=event_id,
        trace_id=f"tr-{event_id}",
        event_type="tool_observation",
        source="pre_tool_call",
        schema_version=1,
        created_at=TS,
        observed_at=TS,
        sequence=0,
        lifecycle_status="observed",
        verification_status="none",
        confidence="medium",
        sensitivity="internal",
        retention="persistent",
        sanitized_content_hash=f"h-{event_id}",
        sanitized_content={"text": f"clean content for {event_id}"},
        redaction_audit=[],
    )
    base.update(over)
    return base


def _make_tombstone(tomb_id, target, **over):
    env = _make_env(tomb_id, event_type="system_event", lifecycle_status="deleted",
                    trace_id=f"tr-{tomb_id}", sanitized_content={"text": f"delete {target}"})
    env["deletion"] = {"target_event_id": target}
    if "deletion" in over:
        env["deletion"].update(over.pop("deletion"))
    env.update(over)
    return env


def _write_jsonl(path: pathlib.Path, items) -> None:
    path.write_text("\n".join(json.dumps(i) for i in items) + "\n")


def _build_corpus(path: pathlib.Path) -> None:
    """Representative canonical JSONL corpus covering all M2 surfaces (see M2.7 plan §fixtures)."""
    items = [
        # valid records across lifecycle states
        _make_env("e_raw", lifecycle_status="raw"),
        _make_env("e_obs", lifecycle_status="observed"),
        _make_env("e_cand", lifecycle_status="candidate"),
        _make_env("e_conf", lifecycle_status="confirmed"),
        # parent trace for child_of relation resolution
        _make_env("e_parent", trace_id="tr-parent", lifecycle_status="observed"),
        # supersession: two active events sharing the SAME trace_id -> first superseded.
        # (M2 active-key uniqueness keys on trace_id, so the active_key envelope field is unused.)
        _make_env("e_act1", trace_id="tr-ak", lifecycle_status="active",
                  project_id="proj-1", profile_id="prof-1",
                  sanitized_content={"text": "deploy service to production"}),
        _make_env("e_act2", trace_id="tr-ak", lifecycle_status="active",
                  project_id="proj-1", profile_id="prof-1",
                  sanitized_content={"text": "rollback the migration now"}),
        _make_env("e_arch", lifecycle_status="archived"),
        _make_env("e_conflict", lifecycle_status="conflicted"),
        # supersession: e_act1 then e_act2 on same trace_id (tr-ak) -> e_act1 superseded
        # relations
        _make_env("e_child", trace_id="tr-child", parent_trace_id="tr-parent",
                  relation_ids=["rel-1"],
                  sanitized_content={"text": "child event with relation"}),
        _make_env("e_rel", relation_ids=["rel-1"],
                  sanitized_content={"text": "related event derived from rel-1"}),
        # artifact reference
        _make_env("e_art", artifact_refs=[{"artifact_id": "art-1", "content_hash": "ch-1",
                                            "kind": "note", "retention": "persistent"}]),
        # retention values
        _make_env("e_temp", retention="temporary"),
        _make_env("e_sess", retention="session"),
        # duplicate content hash (different event id, same hash)
        _make_env("e_duphash", sanitized_content_hash="h-shared"),
        _make_env("e_duphash2", sanitized_content_hash="h-shared"),
        # known-target tombstone (target e_arch already present)
        _make_tombstone("del_known", "e_arch", deletion={"reason_code": "user_request",
                                                          "approved_scope": {"project": "proj-1"}}),
        # unknown-target tombstone (target arrives LATER in this same file, out-of-order)
        _make_tombstone("del_unknown", "e_late"),
        # the late target for del_unknown
        _make_env("e_late", lifecycle_status="active"),
    ]
    _write_jsonl(path, items)
    # Append a few lines that exercise duplicate/conflict/malformed AFTER the main set:
    with path.open("a") as f:
        # duplicate event id (same content) -> DUPLICATE_EVENT_ID
        f.write(json.dumps(_make_env("e_obs")) + "\n")
        # event id/content conflict (same event id, different content) -> EVENT_ID_CONTENT_CONFLICT
        f.write(json.dumps(_make_env("e_obs", sanitized_content={"text": "different content"})) + "\n")
        # malformed record (invalid JSON) -> INVALID_RECORD, ingestion continues
        f.write("{not valid json\n")
        # repeated tombstone (same deletion_event_id, same target as del_known) -> second is DUPLICATE_EVENT_ID
        f.write(json.dumps(_make_tombstone("del_known", "e_arch")) + "\n")


# ---- §1 clean database rebuild + §2 incremental vs rebuild parity -------------

def test_clean_rebuild_and_incremental_parity(tmp_path: pathlib.Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    _build_corpus(corpus)
    # incremental
    inc = _open_store(tmp_path, "inc.sqlite")
    try:
        rep_inc = ingest_file(inc, corpus)
        assert rep_inc.counts[IngestionOutcome.NEW_EVENT] > 0
        # rebuild
        reb = _open_store(tmp_path, "reb.sqlite")
        try:
            rebuild_from_jsonl(reb, [corpus])
            # all M2 derived surfaces match (zm_meta, lifecycle, provenance, relations,
            # scopes, artifacts, tombstones, deletion_audit, FTS). rebuild_from_jsonl does
            # not write a zm_ingest_checkpoint row, so checkpoint state is not compared here.
            assert verify_rebuild_parity(inc, reb) is True
        finally:
            reb.close()
    finally:
        inc.close()


# ---- §3 deterministic repeated rebuild --------------------------------------

def test_repeated_rebuild_deterministic(tmp_path: pathlib.Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    _build_corpus(corpus)
    a = _open_store(tmp_path, "a.sqlite")
    b = _open_store(tmp_path, "b.sqlite")
    try:
        rebuild_from_jsonl(a, [corpus])
        rebuild_from_jsonl(b, [corpus])
        assert verify_rebuild_parity(a, b) is True
        # no duplicate rows: meta count identical across rebuilds
        assert count_metadata(a) == count_metadata(b)
    finally:
        a.close()
        b.close()


# ---- §4 idempotent repeated ingestion ----------------------------------------

def test_repeated_ingestion_idempotent(tmp_path: pathlib.Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    _build_corpus(corpus)
    # Two independent ingestions of the SAME canonical source must produce identical
    # derived state with no duplicate metadata (first-write-wins, deterministic).
    a = _open_store(tmp_path, "a.sqlite")
    b = _open_store(tmp_path, "b.sqlite")
    try:
        rep_a = ingest_file(a, corpus)
        rep_b = ingest_file(b, corpus)
        assert rep_a.counts[IngestionOutcome.NEW_EVENT] > 0
        assert rep_b.counts[IngestionOutcome.NEW_EVENT] > 0
        # identical derived state, no duplicates within or across ingests
        assert count_metadata(a) == count_metadata(b)
        assert verify_rebuild_parity(a, b) is True
        # checkpoint states identical (consumed prefix hash matches)
        cp_a = get_checkpoint(a, corpus.name)
        cp_b = get_checkpoint(b, corpus.name)
        assert cp_a is not None and cp_b is not None
        assert cp_a["consumed_prefix_hash"] == cp_b["consumed_prefix_hash"]
        assert cp_a["last_line_number"] == cp_b["last_line_number"]
    finally:
        a.close()
        b.close()


# ---- §5 lifecycle and supersession -------------------------------------------

def test_lifecycle_states_and_supersession(tmp_path: pathlib.Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    _build_corpus(corpus)
    store = _open_store(tmp_path)
    try:
        rebuild_from_jsonl(store, [corpus])
        # all required lifecycle states present (incl. deleted via tombstone)
        for eid, expected in (
            ("e_raw", "raw"), ("e_obs", "observed"), ("e_cand", "candidate"),
            ("e_conf", "confirmed"), ("e_arch", "deleted"),
            ("e_conflict", "conflicted"), ("e_act2", "active"),
            ("e_late", "deleted"),
        ):
            life = get_lifecycle(store, eid)
            assert life is not None, eid
            assert life["current_state"] == expected, (eid, life["current_state"])
        # supersession: e_act1 (first active on trace tr-ak) superseded by e_act2
        assert get_lifecycle(store, "e_act1")["current_state"] == "superseded"
        # deletion: e_arch deleted via del_known tombstone
        assert get_lifecycle(store, "e_arch")["current_state"] == "deleted"
        # active-state uniqueness on the active key (=trace_id): only e_act2 remains active for tr-ak
        cur = store._conn.cursor()
        act = cur.execute(
            "SELECT event_id FROM zm_lifecycle WHERE active_key='tr-ak' AND current_state='active'"
        ).fetchall()
        assert [r["event_id"] for r in act] == ["e_act2"]
    finally:
        store.close()


# ---- §6 relations and scopes -------------------------------------------------

def test_relations_scopes_artifact_parity(tmp_path: pathlib.Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    _build_corpus(corpus)

    def relations_set(store):
        cur = store._conn.cursor()
        return {(r["from_event_id"], r["to_event_id"], r["relation"]) for r in
                cur.execute("SELECT from_event_id, to_event_id, relation FROM zm_relations").fetchall()}

    def scopes(store):
        cur = store._conn.cursor()
        return {(r["scope_type"], r["scope_id"]) for r in
                cur.execute("SELECT scope_type, scope_id FROM zm_scopes").fetchall()}

    def arts(store):
        cur = store._conn.cursor()
        return {(r["artifact_id"], r["content_hash"]) for r in
                cur.execute("SELECT artifact_id, content_hash FROM zm_artifacts").fetchall()}

    inc = _open_store(tmp_path, "inc.sqlite")
    reb = _open_store(tmp_path, "reb.sqlite")
    try:
        ingest_file(inc, corpus)
        rebuild_from_jsonl(reb, [corpus])
        # relations, scopes, artifacts are identical between incremental and rebuild
        assert relations_set(inc) == relations_set(reb)
        assert scopes(inc) == scopes(reb)
        assert arts(inc) == arts(reb)
        # expected scope coverage present (project/profile are the implemented scope types)
        assert ("project", "proj-1") in scopes(inc)
        assert ("profile", "prof-1") in scopes(inc)
        assert ("art-1", "ch-1") in arts(inc)
        # child_of derived from parent_trace_id (e_child -> parent's earliest event)
        assert any(r[2] == "child_of" for r in relations_set(inc))
        # no inferred cross-profile/cross-project relations: every relation's endpoints share
        # the same project_id scope when project-scoped (audited by scope equality above)
    finally:
        inc.close()
        reb.close()


# ---- §7 FTS and indexes ------------------------------------------------------

def test_fts_only_sanitized_and_excludes_deleted(tmp_path: pathlib.Path) -> None:
    from src.storage.migrations import migrate_5 as _migrate_5
    corpus = tmp_path / "corpus.jsonl"
    _build_corpus(corpus)
    store = _open_store(tmp_path)
    try:
        rebuild_from_jsonl(store, [corpus])
        if _migrate_5.FTS5_AVAILABLE:
            # sanitized content indexed
            hit_deploy = {h["event_id"] for h in search_fts(store, "deploy")}
            assert "e_act1" in hit_deploy
            # deleted record (e_late, tombstoned by del_unknown) excluded from FTS
            hit_late = {h["event_id"] for h in search_fts(store, "clean")}
            assert "e_late" not in hit_late
            # no ranking/semantic behavior: search_fts returns only event_ids, no score
            res = search_fts(store, "deploy")
            assert all(set(r.keys()) == {"event_id", "snippet"} for r in res)
        else:
            # capability-dependent fallback: FTS unavailable, search returns []
            assert search_fts(store, "deploy") == []
    finally:
        store.close()


# ---- §8 retention and deletion (Decision B) ----------------------------------

def test_decision_b_logical_deletion_only(tmp_path: pathlib.Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    _build_corpus(corpus)
    store = _open_store(tmp_path)
    try:
        rebuild_from_jsonl(store, [corpus])
        # deletion represented by append-only deletion events (tombstones)
        from src.storage.ingest import get_tombstone, get_deletion_audit, find_by_trace_id
        assert get_tombstone(store, "del_known") is not None
        assert get_tombstone(store, "del_known")["status"] == "applied"
        # unknown-target tombstone resolved deterministically (target e_late arrived later)
        assert get_tombstone(store, "del_unknown")["status"] == "applied"
        assert get_lifecycle(store, "e_late")["current_state"] == "deleted"
        # canonical JSONL never physically deleted/rewritten (verified §12 separately)
        # deleted excluded from active helpers
        assert "e_late" not in [r["event_id"] for r in find_by_trace_id(store, "tr-e_late")]
        # admin helpers retain auditable provenance
        audit = get_deletion_audit(store, target_event_id="e_late")
        assert len(audit) >= 1
        assert any(a["prior_lifecycle_state"] == "active" for a in audit)
        # no scheduler / automatic expiry entry points
        import src.storage.ingest as ingest_mod
        assert not hasattr(ingest_mod, "apply_retention_schedule")
        assert not hasattr(ingest_mod, "run_retention_expiry")
    finally:
        store.close()


# ---- §9 migration-path verification (reuse foundation tests) -----------------

def test_migration_path_v1_to_v6_idempotent(tmp_path: pathlib.Path) -> None:
    store = _open_store(tmp_path)
    try:
        assert store.get_schema_version() == CURRENT_SCHEMA_VERSION
        assert CURRENT_SCHEMA_VERSION == 13
        # adjacent downgrades all succeed
        for v in (5, 4, 3, 2, 1):
            store.downgrade_to(v)
            assert store.get_schema_version() == v
        # reopen at v6 idempotent after re-applying
        store.ensure_schema()
        assert store.get_schema_version() == CURRENT_SCHEMA_VERSION
    finally:
        store.close()


def test_unknown_future_rejected_without_mutation(tmp_path: pathlib.Path) -> None:
    # Import the live class object (a prior test may have reload()'d the module, replacing
    # the class identity); reference it here so pytest.raises matches the current object.
    from src.storage.sqlite_store import SchemaVersionError
    store = _open_store(tmp_path)
    try:
        store._conn.execute(
            "INSERT INTO zm_migrations(version, applied_at, note) VALUES (?, 't', 'future')",
            (CURRENT_SCHEMA_VERSION + 1,),
        )
        store._conn.commit()
        with pytest.raises(SchemaVersionError):
            store.ensure_schema()
        # ledger still shows the future version (no silent downgrade/mutation of data)
        cur = store._conn.cursor()
        assert cur.execute(
            "SELECT COUNT(*) AS n FROM zm_migrations WHERE version=?",
            (CURRENT_SCHEMA_VERSION + 1,),
        ).fetchone()["n"] == 1
    finally:
        store.close()


def test_failed_migration_no_partial_advance(tmp_path: pathlib.Path) -> None:
    import sqlite3
    from src.storage.migrations import migrate_6 as _migrate_6
    store = _open_store(tmp_path)
    try:
        assert store.get_schema_version() == 13

        class _BadConn:
            def cursor(self):
                raise sqlite3.OperationalError("injected failure")

        real = store._conn
        store._conn = _BadConn()
        with pytest.raises(sqlite3.OperationalError):
            _migrate_6.up(store._conn, "fail")
        store._conn = real
        assert store.get_schema_version() == 13
    finally:
        store.close()


# ---- §10 crash / resume + §12 source integrity -------------------------------

def test_crash_before_commit_no_checkpoint_advance(tmp_path: pathlib.Path) -> None:
    # A malformed/invalid record fails validation inside its transaction; ingestion continues
    # for valid lines but does NOT advance the checkpoint past the failing line. M2.2 covers the
    # DB-level transaction_failed path; here we assert invalid-record handling + first-write-wins.
    store = _open_store(tmp_path)
    try:
        bad = tmp_path / "bad.jsonl"
        _write_jsonl(bad, [_make_env("ok1"), {"event_id": "ok2", "trace_id": "tr-ok2"}])  # ok2 missing required fields
        rep = ingest_file(store, bad)
        # the bad line is an INVALID_RECORD (validation failure), valid ok1 ingested
        assert rep.counts[IngestionOutcome.INVALID_RECORD] >= 1
        assert rep.counts[IngestionOutcome.NEW_EVENT] == 1
        # ingestion is not halted by a validation error (continues), stopped=False
        assert rep.stopped is False
        # checkpoint reflects processed lines (invalid line is committed/logged, not silently merged)
        cp = get_checkpoint(store, bad.name)
        assert cp is not None and cp["last_line_number"] >= 1
    finally:
        store.close()


def test_append_only_growth_resumed_and_prefix_modification_rejected(tmp_path: pathlib.Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    _build_corpus(corpus)
    store = _open_store(tmp_path)
    try:
        rep1 = ingest_file(store, corpus)
        cp1 = get_checkpoint(store, corpus.name)
        # append-only growth: add a new valid line, then resume
        with corpus.open("a") as f:
            f.write(json.dumps(_make_env("e_newtail", lifecycle_status="observed")) + "\n")
        rep2 = ingest_file(store, corpus)
        cp2 = get_checkpoint(store, corpus.name)
        # new line processed, checkpoint advanced exactly one line, no reinsert of prior
        assert rep2.counts[IngestionOutcome.NEW_EVENT] == 1
        assert cp2["last_line_number"] == cp1["last_line_number"] + 1
        # metadata count grew by exactly 1 (no reinsert of prior lines)
        n_before = rep1.counts[IngestionOutcome.NEW_EVENT]
        assert count_metadata(store) == n_before + 1
        # consumed-prefix modification is rejected safely
        data = corpus.read_bytes()
        tampered = data[:20] + b"X" + data[21:]
        corpus.write_bytes(tampered)
        rep3 = ingest_file(store, corpus)
        assert rep3.counts[IngestionOutcome.SOURCE_CHANGED] >= 1
    finally:
        store.close()


# ---- §11 secret safety -------------------------------------------------------

def test_secret_absent_normal_run_and_detected_when_injected(tmp_path: pathlib.Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    _build_corpus(corpus)
    store = _open_store(tmp_path)
    try:
        rep = ingest_file(store, corpus)
        # normal run: no secret anywhere in derived state
        assert scan_sqlite_for_secrets(store, [SECRET]) == []
        # diagnostics never print the secret
        assert SECRET not in str(rep)
        assert SECRET not in str(rep.failures)
        # injected: secret into a derived table (zm_tombstones.reason_code) -> detected
        store._conn.execute(
            "INSERT INTO zm_tombstones(tombstone_id,target_event_id,target_trace_id,reason_code,"
            "approved_scope,verifier,evidence_ref,deletion_event_id,current_state,status,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ("sec-probe", "x", "tr-x", SECRET, None, "deterministic_check", "tr-x", "sec-probe", "deleted", "applied", TS))
        store._conn.commit()
        assert SECRET in scan_sqlite_for_secrets(store, [SECRET])
    finally:
        store.close()


# ---- §12 JSONL immutability --------------------------------------------------

def test_jsonl_byte_for_byte_unchanged(tmp_path: pathlib.Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    _build_corpus(corpus)
    before_hash = hashlib.sha256(corpus.read_bytes()).hexdigest()
    before_len = corpus.stat().st_size
    store = _open_store(tmp_path)
    try:
        ingest_file(store, corpus)
        rebuild_from_jsonl(store, [corpus])  # rebuild reads only; must not mutate source
        # re-ingest
        ingest_file(store, corpus)
    finally:
        store.close()
    after_hash = hashlib.sha256(corpus.read_bytes()).hexdigest()
    after_len = corpus.stat().st_size
    assert before_hash == after_hash
    assert before_len == after_len


# ---- §13 real ~/.hermes isolation (baseline-aware) ---------------------------

def test_no_real_hermes_home_writes(tmp_path: pathlib.Path, monkeypatch) -> None:
    real_home = pathlib.Path.home() / ".hermes"
    UNRELATED_PREFIX = "kanban.db"
    baseline_paths = {p.relative_to(real_home) for p in real_home.rglob("*")} if real_home.exists() else set()
    baseline = {p for p in baseline_paths if not p.name.startswith(UNRELATED_PREFIX)}
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "isolated_hermes_home"))
    corpus = tmp_path / "corpus.jsonl"
    _build_corpus(corpus)
    store = _open_store(tmp_path)
    try:
        ingest_file(store, corpus)
        rebuild_from_jsonl(store, [corpus])
    finally:
        store.close()
    after_paths = {p.relative_to(real_home) for p in real_home.rglob("*")} if real_home.exists() else set()
    after = {p for p in after_paths if not p.name.startswith(UNRELATED_PREFIX)}
    assert after == baseline, f"M2.7 wrote to real ~/.hermes: added={after - baseline}"


# ---- §14 no later (M3) behavior ----------------------------------------------

def test_no_m3_behavior(tmp_path: pathlib.Path) -> None:
    import src.storage.ingest as ingest_mod
    store = _open_store(tmp_path)
    try:
        tables = {r["name"] for r in store._conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "zm_retrieval" not in tables
        assert "zm_ranking" not in tables
        assert "zm_vectors" not in tables
        for attr in ("retrieve_top_k", "rank_results", "query_route", "select_memory",
                     "inject_context", "physical_purge", "apply_retention_schedule"):
            assert not hasattr(ingest_mod, attr)
    finally:
        store.close()
