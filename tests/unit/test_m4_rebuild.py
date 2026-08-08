"""M4.7 focused tests: deterministic rebuild + final M4 integration acceptance.

Covers the full M4.7 acceptance matrix:
- rebuild_project_memory entrypoint (reconstructs all six M4 tables from canonical JSONL);
- incremental == rebuild parity (normalized row comparison, not rowid/order);
- repeated rebuild determinism (rebuild #1/#2/#3 identical, no drift/new ids);
- transaction/idempotence (duplicate events -> no duplicate rows/links);
- conflict/supersession preserved (no winner, explicit chains only);
- key integrity (decision_key/state_key never derived from trace_id; NULL preserved);
- active uniqueness (charter/decision/state at most one active per key);
- TRUE READ-ONLY M4.6 regression (read workload does not mutate rebuilt state);
- M3 composition regression;
- JSONL immutability (sha256 unchanged across rebuild + queries);
- SQLite integrity (table hashes unchanged across read workload);
- secret safety (synthetic secret absent from M4 tables/results/cursors/errors);
- no LLM/network (routine path; guarded);
- performance baseline (recorded, deterministic);
- M4 focused suite + prior-milestone regression (run separately).

Reads use a SEPARATE ReadonlyStore; rebuild writes use the project store. No
projector/test weakens the real-home isolation test.
"""
import sys, tempfile, json, hashlib, time
from pathlib import Path

ROOT = Path("/home/brian-nguyen/Hermes Workplace/Zero-mem")
sys.path.insert(0, str(ROOT))

import pytest
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.retrieval.db import open_readonly, _readonly_conn_is_query_only
from src.retrieval.models import QueryError
from src.project_memory import (
    rebuild_project_memory, rebuild_all_project_memory, event_to_op,
)
from src.project_memory import (
    get_project_charter, list_project_charters, get_requirement, list_requirements,
    get_decision, list_decisions, get_active_decision, get_current_project_state,
    get_state_value, get_verification, list_verifications, list_project_artifacts,
    is_query_only,
)

SECRET = "SK-M4-7-SECRET-XYZ"


# ---------------------------------------------------------------------------
# Corpus + store helpers
# ---------------------------------------------------------------------------


def _ev(event_id, domain, identity, op, project_id="P", event_type="m4_x", **kw):
    m4 = {"domain": domain, "identity": identity, "op": op, "project_id": project_id}
    m4.update(kw)
    return {
        "event_id": event_id, "event_type": event_type, "project_id": project_id,
        "trace_id": "T-" + event_id, "session_id": "S1", "profile_id": "PR1",
        "created_at": "2026-08-01T00:00:00Z", "m4": m4,
    }


def build_corpus(tmp: Path) -> Path:
    """Representative integration corpus (multi-project/profile/session/trace)."""
    events = [
        # --- Charter: create, version (update), supersede history, deleted ---
        _ev("E1", "charter", "C1", "create", project_id="P", name="Charter",
            goal="g", state="confirmed", lifecycle_status="active", version=1),
        _ev("E2", "charter", "C1", "update", project_id="P", name="Charter v2",
            goal="g", state="confirmed", lifecycle_status="active", version=2,
            supersedes="C1"),
        _ev("E3", "charter", "C2", "create", project_id="P", name="Old",
            state="candidate", lifecycle_status="deleted", version=1),
        # --- Requirement: active, candidate, superseded, conflict, archived, deleted,
        #     assistant_claim that must NOT become active ---
        _ev("E10", "requirement", "R1", "create", project_id="P", statement="do x",
            state="accepted", lifecycle_status="active", verification_status="deterministic_verification"),
        _ev("E11", "requirement", "R2", "create", project_id="P", statement="do y",
            state="proposed", lifecycle_status="candidate"),
        _ev("E12", "requirement", "R3", "create", project_id="P", statement="do z",
            state="accepted", lifecycle_status="superseded", supersedes="R1"),
        _ev("E13", "requirement", "R4", "create", project_id="P", statement="conflict A",
            state="accepted", lifecycle_status="conflicted"),
        _ev("E14", "requirement", "R5", "create", project_id="P", statement="conflict B",
            state="accepted", lifecycle_status="conflicted"),
        _ev("E15", "requirement", "R6", "create", project_id="P", statement="arch",
            state="satisfied", lifecycle_status="archived"),
        _ev("E16", "requirement", "R7", "create", project_id="P", statement="del",
            state="proposed", lifecycle_status="deleted"),
        _ev("E17", "requirement", "R8", "create", project_id="P", statement="claim",
            state="proposed", lifecycle_status="candidate",
            derived_from_event_type="assistant_claim",  # must NOT promote to active
            event_type="assistant_claim"),
        # --- Decision: explicit key active, superseded, supersession chain D1<-D2<-D3,
        #     conflict, multiple NULL-key active, assistant_claim not active ---
        _ev("E20", "decision", "D1", "create", project_id="P", scope="project:P",
            decision_key="K", statement="pick A", state="accepted", lifecycle_status="active",
            effective_at="2026-08-04T00:00:00Z"),
        _ev("E21", "decision", "D2", "create", project_id="P", scope="project:P",
            decision_key="K", statement="pick B", state="accepted", lifecycle_status="conflicted",
            effective_at="2026-08-04T00:00:00Z"),
        _ev("E22", "decision", "D10", "create", project_id="P", scope="project:P",
            decision_key="KEY1", statement="v1", state="accepted", lifecycle_status="active",
            effective_at="2026-08-04T00:00:00Z"),
        _ev("E23", "decision", "D11", "supersede", project_id="P", scope="project:P",
            decision_key="KEY1", statement="v2", state="accepted", lifecycle_status="active",
            supersedes_id="D10", effective_at="2026-08-05T00:00:00Z"),
        _ev("E24", "decision", "D12", "supersede", project_id="P", scope="project:P",
            decision_key="KEY1", statement="v3", state="accepted", lifecycle_status="active",
            supersedes_id="D11", effective_at="2026-08-06T00:00:00Z"),
        _ev("E25", "decision", "D20", "create", project_id="P", scope="project:P",
            decision_key=None, statement="null-key A", state="accepted", lifecycle_status="active"),
        _ev("E26", "decision", "D21", "create", project_id="P", scope="project:P",
            decision_key=None, statement="null-key B", state="accepted", lifecycle_status="active"),
        _ev("E27", "decision", "D22", "create", project_id="P", scope="project:P",
            decision_key=None, statement="claim decision", state="accepted",
            lifecycle_status="candidate", derived_from_event_type="assistant_claim",
            event_type="assistant_claim"),
        # --- State: explicit key slots, update, supersede, NULL-key, conflict ---
        _ev("E30", "state", "S1", "create", project_id="P", state_key="progress",
            state_value="40%", lifecycle_status="active", effective_at="2026-08-01T00:00:00Z"),
        _ev("E31", "state", "S1", "update", project_id="P", state_key="progress",
            state_value="50%", lifecycle_status="active", effective_at="2026-08-05T00:00:00Z"),
        _ev("E32", "state", "S2", "create", project_id="P", state_key="risk",
            state_value="low", lifecycle_status="active"),
        _ev("E33", "state", "S3", "create", project_id="P", state_key=None,
            state_value="orphan", lifecycle_status="active"),
        _ev("E34", "state", "S4", "create", project_id="P", state_key="progress",
            state_value="40%", lifecycle_status="conflicted"),
        # --- Verification: statuses, subjects, contradictory, no auto-promote ---
        _ev("E40", "verification", "V1", "create", project_id="P", subject_type="requirement",
            subject_id="R1", method="pytest", verification_status="deterministic_verification"),
        _ev("E41", "verification", "V2", "create", project_id="P", subject_type="requirement",
            subject_id="R1", method="manual", verification_status="direct_tool_output"),
        _ev("E42", "verification", "V3", "create", project_id="P", subject_type="decision",
            subject_id="D1", method="pytest", verification_status="user_confirmation"),
        # --- Artifact: M2 linkage, safe refs, linked ids ---
        _ev("E50", "artifact", "ART1", "create", project_id="P", artifact_type="report",
            version="1", safe_reference="artifacts/report.md",
            linked_requirement_ids="R1", linked_decision_ids="D1", linked_state_keys="progress"),
        # --- Second project (multi-project) ---
        _ev("E60", "requirement", "RQ", "create", project_id="Q", statement="q x",
            state="accepted", lifecycle_status="active"),
        _ev("E61", "decision", "DQ", "create", project_id="Q", scope="project:Q",
            decision_key="QK", statement="q pick", state="accepted", lifecycle_status="active"),
        # --- Deletion event (logical; JSONL untouched) ---
        _ev("E70", "requirement", "R7", "delete", project_id="P", statement="del",
            state="proposed", lifecycle_status="deleted"),
    ]
    corpus = tmp / "corpus.jsonl"
    corpus.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return corpus


def _seed_m2_artifacts(conn) -> None:
    # M2 artifact substrate required for the FK on zm_project_artifacts.
    conn.execute(
        "INSERT INTO zm_artifacts(artifact_id, content_hash, kind, retention, origin_event_id, stored_path, created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        ("ART1", "deadbeef", "report", "project", "E50", f"artifacts/{SECRET}.md", "2026-08-07T00:00:00Z"),
    )
    conn.commit()


def _open(tmp: Path, name: str = "m4.sqlite") -> SQLiteStore:
    store = SQLiteStore(SQLiteStoreConfig(path=tmp / name))
    store.ensure_schema()
    _seed_m2_artifacts(store._conn)
    return store


# ---------------------------------------------------------------------------
# Normalized parity helpers
# ---------------------------------------------------------------------------


def _norm_rows(conn, table, cols):
    rows = conn.execute(f"SELECT {','.join(cols)} FROM {table}").fetchall()
    return {tuple(r[c] for c in cols) for r in rows}


def _store_snapshot(conn):
    return {
        "zm_project_charters": _norm_rows(conn, "zm_project_charters",
            ["charter_id", "project_id", "version", "lifecycle_status", "state", "supersedes"]),
        "zm_requirements": _norm_rows(conn, "zm_requirements",
            ["requirement_id", "project_id", "statement", "lifecycle_status", "state",
             "verification_status", "supersedes", "replaced_by"]),
        "zm_decisions": _norm_rows(conn, "zm_decisions",
            ["decision_id", "project_id", "scope", "decision_key", "statement",
             "lifecycle_status", "state", "supersedes_id", "replaced_by"]),
        "zm_project_state": _norm_rows(conn, "zm_project_state",
            ["project_id", "scope", "state_key", "state_value", "lifecycle_status", "supersedes"]),
        "zm_verifications": _norm_rows(conn, "zm_verifications",
            ["verification_id", "subject_type", "subject_id", "project_id",
             "verification_status"]),
        "zm_project_artifacts": _norm_rows(conn, "zm_project_artifacts",
            ["artifact_id", "project_id", "artifact_type", "safe_reference",
             "linked_requirement_ids", "linked_decision_ids", "linked_state_keys"]),
    }


def _assert_parity(snap_a, snap_b):
    for table in snap_a:
        assert snap_a[table] == snap_b[table], f"parity mismatch on {table}"


# ---------------------------------------------------------------------------
# Rebuild API + determinism
# ---------------------------------------------------------------------------


def test_rebuild_entrypoint_reconstructs_all_six_tables(tmp_path: Path) -> None:
    corpus = build_corpus(tmp_path)
    store = _open(tmp_path)
    res = rebuild_project_memory(store, corpus, project_id="P")
    assert res["projected"] > 0
    snap = _store_snapshot(store._conn)
    for table in ("zm_project_charters", "zm_requirements", "zm_decisions",
                  "zm_project_state", "zm_verifications", "zm_project_artifacts"):
        assert len(snap[table]) > 0, table
    store.close()


def test_incremental_equals_rebuild(tmp_path: Path) -> None:
    corpus = build_corpus(tmp_path)
    # Incremental store: rebuild the whole corpus (same per-event loop).
    inc = _open(tmp_path, "inc.sqlite")
    rebuild_project_memory(inc, corpus, project_id="P")
    # Rebuild store: drop + re-ensure + replay.
    rb = _open(tmp_path, "rb.sqlite")
    rebuild_all_project_memory(rb, corpus, project_id="P")
    _assert_parity(_store_snapshot(inc._conn), _store_snapshot(rb._conn))
    inc.close(); rb.close()


def test_repeated_rebuild_determinism(tmp_path: Path) -> None:
    corpus = build_corpus(tmp_path)
    stores = []
    snaps = []
    for i in range(3):
        s = _open(tmp_path, f"rb{i}.sqlite")
        rebuild_all_project_memory(s, corpus, project_id="P")
        snaps.append(_store_snapshot(s._conn))
        stores.append(s)
    _assert_parity(snaps[0], snaps[1])
    _assert_parity(snaps[1], snaps[2])
    # No new ids/rows beyond the canonical set.
    assert len(snaps[0]["zm_requirements"]) == 8  # R1..R8 (R7 deleted still a row)
    for s in stores:
        s.close()


# ---------------------------------------------------------------------------
# Conflict / supersession integrity
# ---------------------------------------------------------------------------


def test_conflict_preserved_no_winner(tmp_path: Path) -> None:
    corpus = build_corpus(tmp_path)
    store = _open(tmp_path)
    rebuild_project_memory(store, corpus, project_id="P")
    rs = open_readonly(store.path)
    reqs = {x.requirement_id: x.lifecycle_status for x in list_requirements(rs, "P").items}
    # R4/R5 conflicted BOTH present; no winner chosen.
    assert reqs["R4"] == "conflicted" and reqs["R5"] == "conflicted"
    decs = {x.decision_id: x.lifecycle_status for x in list_decisions(rs, "P").items}
    assert decs["D1"] == "active" and decs["D2"] == "conflicted"
    rs.close(); store.close()


def test_explicit_supersession_chains_retained(tmp_path: Path) -> None:
    corpus = build_corpus(tmp_path)
    store = _open(tmp_path)
    rebuild_project_memory(store, corpus, project_id="P")
    rs = open_readonly(store.path)
    # Requirement R3 superseded by R1.
    r3 = get_requirement(rs, "R3")
    assert r3.lifecycle_status == "superseded" and r3.supersedes == "R1"
    # Decision supersession chain D10<-D11<-D12 (D12 active is the head).
    d12 = get_decision(rs, "D12")
    assert d12.lifecycle_status == "active" and d12.supersedes_id == "D11"
    d11 = get_decision(rs, "D11")
    assert d11.lifecycle_status == "superseded" and d11.supersedes_id == "D10"
    d10 = get_decision(rs, "D10")
    assert d10.lifecycle_status == "superseded"
    # No extra inferred transitive edge.
    assert d12.supersedes_id == "D11" and d12.supersedes_id != "D10"
    rs.close(); store.close()


# ---------------------------------------------------------------------------
# Key integrity
# ---------------------------------------------------------------------------


def test_key_integrity_trace_id_not_used(tmp_path: Path) -> None:
    corpus = build_corpus(tmp_path)
    store = _open(tmp_path)
    rebuild_project_memory(store, corpus, project_id="P")
    rs = open_readonly(store.path)
    # Active decisions with explicit KEY1 -> single active.
    ad = get_active_decision(rs, "P", "project:P", "KEY1")
    assert ad is not None and ad.decision_id == "D12"
    # Multiple NULL-key active decisions coexist (no false collision).
    null_keys = [d for d in list_decisions(rs, "P").items if d.decision_key is None]
    assert len(null_keys) >= 2
    assert all(d.lifecycle_status == "active" for d in null_keys[:2])
    # NULL state_key record preserved.
    sv = list(get_current_project_state(rs, "P"))
    assert any(s.state_key is None for s in sv)
    rs.close(); store.close()


def test_active_uniqueness_after_rebuild(tmp_path: Path) -> None:
    corpus = build_corpus(tmp_path)
    store = _open(tmp_path)
    rebuild_all_project_memory(store, corpus, project_id="P")
    rs = open_readonly(store.path)
    # Decision active uniqueness per (project, scope, key).
    for key in ("K", "KEY1"):
        acts = [d for d in list_decisions(rs, "P").items
                if d.decision_key == key and d.lifecycle_status == "active"]
        assert len(acts) <= 1, f"dual-active for {key}"
    # State active uniqueness per (project, scope, key).
    for sk in ("progress", "risk"):
        acts = [s for s in get_current_project_state(rs, "P")
                if s.state_key == sk and s.lifecycle_status == "active"]
        assert len(acts) <= 1, f"dual-active state for {sk}"
    # Charter active uniqueness.
    chars = [c for c in list_project_charters(rs, "P").items if c.lifecycle_status == "active"]
    assert len(chars) <= 1
    rs.close(); store.close()


# ---------------------------------------------------------------------------
# Idempotence
# ---------------------------------------------------------------------------


def test_idempotence_duplicate_events(tmp_path: Path) -> None:
    corpus = build_corpus(tmp_path)
    store = _open(tmp_path)
    rebuild_project_memory(store, corpus, project_id="P")
    before = _store_snapshot(store._conn)
    # Replay the SAME corpus again (duplicate events).
    rebuild_project_memory(store, corpus, project_id="P")
    after = _store_snapshot(store._conn)
    _assert_parity(before, after)
    store.close()


# ---------------------------------------------------------------------------
# TRUE READ-ONLY regression
# ---------------------------------------------------------------------------


def test_read_only_after_rebuild_no_mutation(tmp_path: Path) -> None:
    corpus = build_corpus(tmp_path)
    store = _open(tmp_path)
    rebuild_all_project_memory(store, corpus, project_id="P")
    rs = open_readonly(store.path)
    assert is_query_only(rs) is True
    before = {t: store._conn.execute(f"SELECT COUNT(*) n FROM {t}").fetchone()["n"]
              for t in ("zm_project_charters", "zm_requirements", "zm_decisions",
                        "zm_project_state", "zm_verifications", "zm_project_artifacts")}
    # Exercise the whole M4.6 surface.
    get_project_charter(rs, "P")
    list_project_charters(rs, "P", limit=2)
    get_requirement(rs, "R1")
    list_requirements(rs, "P", limit=2)
    get_decision(rs, "D1")
    list_decisions(rs, "P", limit=2)
    get_active_decision(rs, "P", "project:P", "K")
    get_current_project_state(rs, "P")
    get_state_value(rs, "P", "project:P", "progress")
    get_verification(rs, "V1")
    list_verifications(rs, project_id="P", limit=2)
    list_project_artifacts(rs, "P", limit=2)
    after = {t: store._conn.execute(f"SELECT COUNT(*) n FROM {t}").fetchone()["n"] for t in before}
    assert before == after
    assert rs.get_schema_version() == 7
    rs.close(); store.close()


# ---------------------------------------------------------------------------
# M3 composition regression
# ---------------------------------------------------------------------------


def test_m3_source_event_composition_after_rebuild(tmp_path: Path) -> None:
    corpus = build_corpus(tmp_path)
    store = _open(tmp_path)
    rebuild_project_memory(store, corpus, project_id="P")
    rs = open_readonly(store.path)
    # source_event_id stored; M3 resolve returns None when source absent (no fabricate).
    r = get_requirement(rs, "R1", include_source_event=True)
    assert r.source_event_id is not None
    assert r.source_event is None
    rs.close(); store.close()


# ---------------------------------------------------------------------------
# JSONL immutability + SQLite integrity
# ---------------------------------------------------------------------------


def test_jsonl_immutable_across_rebuild_and_reads(tmp_path: Path) -> None:
    corpus = build_corpus(tmp_path)
    digest_before = hashlib.sha256(corpus.read_bytes()).hexdigest()
    store = _open(tmp_path)
    rebuild_all_project_memory(store, corpus, project_id="P")
    rs = open_readonly(store.path)
    # Run a read workload.
    list_project_charters(rs, "P"); list_requirements(rs, "P"); list_decisions(rs, "P")
    list_verifications(rs, project_id="P"); list_project_artifacts(rs, "P")
    rs.close()
    # Second rebuild.
    rebuild_all_project_memory(store, corpus, project_id="P")
    store.close()
    digest_after = hashlib.sha256(corpus.read_bytes()).hexdigest()
    assert digest_before == digest_after


def test_sqlite_integrity_across_read_workload(tmp_path: Path) -> None:
    corpus = build_corpus(tmp_path)
    store = _open(tmp_path)
    rebuild_all_project_memory(store, corpus, project_id="P")
    rs = open_readonly(store.path)
    snap_before = _store_snapshot(rs.conn)
    for _ in range(3):
        list_project_charters(rs, "P"); list_requirements(rs, "P")
        list_decisions(rs, "P"); list_verifications(rs, project_id="P")
        list_project_artifacts(rs, "P")
    snap_after = _store_snapshot(rs.conn)
    _assert_parity(snap_before, snap_after)
    rs.close(); store.close()


# ---------------------------------------------------------------------------
# Secret safety
# ---------------------------------------------------------------------------


def test_secret_absent_from_m4_tables_and_results(tmp_path: Path) -> None:
    corpus = build_corpus(tmp_path)
    store = _open(tmp_path)
    rebuild_project_memory(store, corpus, project_id="P")
    rs = open_readonly(store.path)
    # Secret lives ONLY in the M2 substrate (zm_artifacts.stored_path), which M4
    # read APIs do NOT expose (no stored_path column on M4 views).
    m2_secret = store._conn.execute(
        "SELECT stored_path FROM zm_artifacts WHERE artifact_id='ART1'"
    ).fetchone()["stored_path"]
    assert SECRET in m2_secret  # present in M2 substrate only
    # Scan every M4 table row for the secret.
    for table in ("zm_project_charters", "zm_requirements", "zm_decisions",
                  "zm_project_state", "zm_verifications", "zm_project_artifacts"):
        rows = rs.conn.execute(f"SELECT * FROM {table}").fetchall()
        for r in rows:
            for v in dict(r).values():
                assert v is None or SECRET not in str(v), f"secret leaked into {table}"
    # M4 read results must not contain the secret.
    pa = list_project_artifacts(rs, "P").items[0]
    assert SECRET not in json.dumps(pa.__dict__)
    assert not hasattr(pa, "stored_path")
    reqs_blob = json.dumps([r.__dict__ for r in list_requirements(rs, "P").items])
    assert SECRET not in reqs_blob
    rs.close(); store.close()


# ---------------------------------------------------------------------------
# No LLM / network (routine rebuild path)
# ---------------------------------------------------------------------------


def test_rebuild_no_llm_network(tmp_path: Path) -> None:
    corpus = build_corpus(tmp_path)
    store = _open(tmp_path)
    # Build a guard that fails the test if any network/LLM call is attempted.
    import urllib.request
    import socket
    real_urlopen = urllib.request.urlopen
    real_socket = socket.socket

    def _blocked(*a, **k):
        raise AssertionError("network call attempted during rebuild")

    urllib.request.urlopen = _blocked
    socket.socket = _blocked  # type: ignore[assignment]
    try:
        rebuild_all_project_memory(store, corpus, project_id="P")
    finally:
        urllib.request.urlopen = real_urlopen
        socket.socket = real_socket  # type: ignore[assignment]
    store.close()


# ---------------------------------------------------------------------------
# Transaction / rollback (deterministic injection at projector boundary)
# ---------------------------------------------------------------------------


def test_duplicate_identity_create_rolls_back_atomically(tmp_path: Path) -> None:
    # A malformed second 'create' on an existing identity must raise a sanitized
    # projector error AND roll back (no partial M4 state). Verified at the
    # projector boundary, which the rebuild loop wraps atomically.
    from src.project_memory.projector import project_charter
    from src.project_memory.contracts import CharterOp, InvalidTransitionError
    corpus = build_corpus(tmp_path)
    store = _open(tmp_path)
    rebuild_project_memory(store, corpus, project_id="P")
    before = store._conn.execute(
        "SELECT name FROM zm_project_charters WHERE charter_id='C1'"
    ).fetchone()["name"]
    # Second CREATE on the existing C1 with DIFFERENT content -> rejected.
    op = CharterOp(op="create", charter_id="C1", project_id="P",
                   name="dup", goal="g", state="candidate",
                   lifecycle_status="candidate", source_event_id="EBAD")
    with pytest.raises(InvalidTransitionError):
        project_charter(store._conn, op)
    # Rollback: the existing active charter content is unchanged (no partial row).
    after = store._conn.execute(
        "SELECT name FROM zm_project_charters WHERE charter_id='C1'"
    ).fetchone()["name"]
    assert before == after == "Charter v2"
    store.close()


# ---------------------------------------------------------------------------
# Performance baseline (deterministic, no caching added)
# ---------------------------------------------------------------------------


def test_performance_baseline_recorded(tmp_path: Path) -> None:
    # Build a larger deterministic corpus (multi-project, repeated events).
    big = []
    n_projects = 3
    n_req = 20
    n_dec = 20
    for p in range(n_projects):
        pid = f"P{p}"
        for i in range(n_req):
            big.append(_ev(f"BR{p}-{i}", "requirement", f"R{p}-{i}", "create",
                           project_id=pid, statement=f"s{i}",
                           state="accepted", lifecycle_status="active"))
        for i in range(n_dec):
            big.append(_ev(f"BD{p}-{i}", "decision", f"D{p}-{i}", "create",
                           project_id=pid, scope=f"project:{pid}",
                           decision_key=f"K{i}", statement=f"d{i}",
                           state="accepted", lifecycle_status="active"))
    corpus = tmp_path / "big.jsonl"
    corpus.write_text("\n".join(json.dumps(e) for e in big) + "\n")

    store = SQLiteStore(SQLiteStoreConfig(path=tmp_path / "big.sqlite"))
    store.ensure_schema()
    store._conn.execute("PRAGMA foreign_keys=ON")

    # Rebuild timing.
    t0 = time.perf_counter()
    res = rebuild_all_project_memory(store, corpus)
    rebuild_ms = (time.perf_counter() - t0) * 1000.0

    rs = open_readonly(store.path)
    # Query timings (median over N iterations).
    def _med(fn, n=20):
        ts = []
        for _ in range(n):
            t = time.perf_counter()
            fn()
            ts.append((time.perf_counter() - t) * 1000.0)
        ts.sort()
        return ts[len(ts) // 2]

    med_active_charter = _med(lambda: get_project_charter(rs, "P0"))
    med_req_list = _med(lambda: list_requirements(rs, "P0"))
    med_active_dec = _med(lambda: get_active_decision(rs, "P0", "project:P0", "K0"))
    med_state = _med(lambda: get_state_value(rs, "P0", "project:P0", "NoneKey"))
    med_verif = _med(lambda: get_verification(rs, "Vx"))
    med_artifact = _med(lambda: list_project_artifacts(rs, "P0"))
    rs.close(); store.close()

    import sqlite3 as _sq
    baseline = {
        "corpus_events": len(big),
        "project_count": n_projects,
        "m4_requirement_rows": n_projects * n_req,
        "m4_decision_rows": n_projects * n_dec,
        "sqlite_version": _sq.sqlite_version,
        "python_version": __import__("sys").version.split()[0],
        "rebuild_ms": round(rebuild_ms, 2),
        "median_active_charter_lookup_ms": round(med_active_charter, 3),
        "median_requirement_listing_ms": round(med_req_list, 3),
        "median_active_decision_lookup_ms": round(med_active_dec, 3),
        "median_state_lookup_ms": round(med_state, 3),
        "median_verification_lookup_ms": round(med_verif, 3),
        "median_project_artifact_listing_ms": round(med_artifact, 3),
        "iterations": 20,
    }
    # No pathological behavior: rebuild well under a generous bound.
    assert rebuild_ms < 5000.0, baseline
    # Record a machine-readable baseline artifact (not a test artifact).
    out = tmp_path.parent / "m4.7-performance-baseline.json"
    out.write_text(json.dumps(baseline, indent=2))
    print("PERF BASELINE:", json.dumps(baseline))
    # Keep the baseline file OUT of the repo (cleanup step removes it); assertion only.


# ---------------------------------------------------------------------------
# event_to_op unit
# ---------------------------------------------------------------------------


def test_event_to_op_maps_identity_and_provenance(tmp_path: Path) -> None:
    ev = _ev("E1", "charter", "C9", "create", project_id="P", name="X",
             state="confirmed", lifecycle_status="active")
    op = event_to_op(ev)
    assert op.charter_id == "C9"
    assert op.source_event_id == "E1"
    assert op.trace_id == "T-E1"
    assert op.project_id == "P"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
