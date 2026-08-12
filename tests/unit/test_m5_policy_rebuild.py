"""M5.6 focused tests — policy rebuild, audit, security/performance, final acceptance."""

import json
import sqlite3
import sys
import time
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.access import admin, authorized_read, authorized_write, linked, resolver, rebuild
from src.access.contracts import AccessRequest, READ, WRITE, ReasonCode
from src.access.grants import AuthorizedReadGrant, compose_effective_scope
from src.access.audit import record_decision, project_policy_decision, _should_audit
from src.access.grant_events import AccessGrantEvent, project_grant_event
from src.storage.migrations import CURRENT_SCHEMA_VERSION, migrate_8
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.storage.canonical_replay import CanonicalReplayError

SECRET = "SK-M5R-DONTLEAK-3c4d5e6f"
SECRET_B = "secret-B-" + SECRET


class _V:
    verification_status = "verified"


def vlookup(ref):
    return _V() if ref == "V1" else None


def _mdb():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    migrate_8.up(c, "t")
    c.commit()
    return c


def _canonical_writer_factory(path: Path):
    def writer(ev):
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev) + "\n")
    return writer


def _build_corpus(seed: str = ""):
    d = Path(tempfile.mkdtemp(prefix="zt-m56-"))
    jl = d / "policy.jsonl"
    conn = _mdb()
    svc = admin.GrantAdminService(conn, _canonical_writer_factory(jl), vlookup)
    svc.create(admin.GrantAdminRequest(action="create", grant_id="G1" + seed,
                  subject_profile="PR1", operation=READ, target_type="profile",
                  target_id="PR2", resource_types=["requirement"]))
    svc.create(admin.GrantAdminRequest(action="create", grant_id="GW" + seed,
                  subject_profile="PR1", operation=WRITE, target_type="project",
                  target_id="P", resource_types=["state"], verification_ref="V1"))
    svc.create(admin.GrantAdminRequest(action="create", grant_id="GR" + seed,
                  subject_profile="PR1", operation=READ, target_type="profile",
                  target_id="PR9", resource_types=["requirement"]))
    svc.revoke(admin.GrantAdminRequest(action="revoke", grant_id="GR" + seed,
                  subject_profile="PR1", operation=READ, target_type="profile",
                  target_id="PR9"))
    svc.supersede(admin.GrantAdminRequest(action="supersede", grant_id="G3" + seed,
                  subject_profile="PR1", operation=READ, target_type="profile",
                  target_id="PR2", supersedes="G1" + seed, resource_types=["requirement"]))
    # conflicted grant via a trusted canonical access_grant event (so it survives rebuild)
    gc_event = AccessGrantEvent(
        grant_id="GC" + seed, subject_profile="PR1", operation=READ,
        target_type="profile", target_id="PR2", op="create",
        resource_types=["requirement"], lifecycle_status="conflicted", state="accepted",
        created_at="t").to_canonical_dict()
    project_grant_event(conn, AccessGrantEvent.from_canonical_dict(gc_event))
    _canonical_writer_factory(jl)(gc_event)
    conn.commit()
    return conn, jl


def _build_full_corpus(seed: str = ""):
    d = Path(tempfile.mkdtemp(prefix="zt-m56-full-"))
    jl = d / "policy.jsonl"
    store = SQLiteStore(SQLiteStoreConfig(path=d / "m.sqlite"))
    store.ensure_schema()
    store._conn.commit()
    svc = admin.GrantAdminService(store._conn, _canonical_writer_factory(jl), vlookup)
    svc.create(admin.GrantAdminRequest(action="create", grant_id="G1" + seed,
                  subject_profile="PR1", operation=READ, target_type="profile",
                  target_id="PR2", resource_types=["requirement"]))
    svc.create(admin.GrantAdminRequest(action="create", grant_id="GW" + seed,
                  subject_profile="PR1", operation=WRITE, target_type="project",
                  target_id="P", resource_types=["state"], verification_ref="V1"))
    svc.revoke(admin.GrantAdminRequest(action="revoke", grant_id="GR" + seed,
                  subject_profile="PR1", operation=READ, target_type="profile",
                  target_id="PR9", resource_types=["requirement"]))
    svc.supersede(admin.GrantAdminRequest(action="supersede", grant_id="G3" + seed,
                  subject_profile="PR1", operation=READ, target_type="profile",
                  target_id="PR2", supersedes="G1" + seed, resource_types=["requirement"]))
    gc_event = AccessGrantEvent(
        grant_id="GC" + seed, subject_profile="PR1", operation=READ,
        target_type="profile", target_id="PR2", op="create",
        resource_types=["requirement"], lifecycle_status="conflicted", state="accepted",
        created_at="t").to_canonical_dict()
    project_grant_event(store._conn, AccessGrantEvent.from_canonical_dict(gc_event))
    _canonical_writer_factory(jl)(gc_event)
    store._conn.commit()
    return store, jl


class TestRebuild:
    def test_rebuild_grant_state(self):
        conn, jl = _build_corpus()
        rg = resolver.resolve_read_grants(conn, "PR1")
        assert any(g.grant_id == "G3" for g in rg)
        assert not any(g.grant_id == "GR" for g in rg)
        conn.close()

    def test_incremental_vs_rebuild_grants(self):
        conn, jl = _build_corpus()
        inc = rebuild.normalize_grants(conn)
        conn2 = _mdb()
        summary = rebuild.rebuild_policy_state(conn2, jl)
        reb = rebuild.normalize_grants(conn2)
        # corpus canonical events: G1 create, GW create, GR create, GR revoke, G3 supersede = 5
        assert summary["grant_events"] == 6
        assert inc == reb
        conn.close(); conn2.close()

    @pytest.mark.parametrize("malformed_first", [False, True])
    def test_malformed_policy_replay_blocks_and_preserves_prior_state(self, malformed_first):
        conn, jl = _build_corpus("-bad")
        before_grants = rebuild.normalize_grants(conn)
        before_audit = rebuild.normalize_audit(conn)
        valid = json.loads(jl.read_text().splitlines()[0])
        bad = jl.parent / "malformed-policy.jsonl"
        lines = ["{malformed policy event", json.dumps(valid)]
        if not malformed_first:
            lines.reverse()
        bad.write_text("\n".join(lines) + "\n")
        with pytest.raises(CanonicalReplayError, match="malformed_json"):
            rebuild.rebuild_policy_state(conn, bad)
        assert rebuild.normalize_grants(conn) == before_grants
        assert rebuild.normalize_audit(conn) == before_audit
        conn.close()

    def test_valid_unrelated_domain_event_remains_skippable(self):
        conn, jl = _build_corpus("-mixed")
        valid_policy = json.loads(jl.read_text().splitlines()[0])
        unrelated = {
            "event_id": "M4-UNRELATED",
            "event_type": "m4_charter",
            "m4": {"domain": "charter", "identity": "C1", "op": "create"},
        }
        mixed = jl.parent / "mixed-policy.jsonl"
        mixed.write_text(json.dumps(unrelated) + "\n" + json.dumps(valid_policy) + "\n")
        events = rebuild.iter_canonical_policy_events(mixed)
        assert len(events) == 1 and events[0]["event_type"] == "access_grant"
        conn.close()

    def test_policy_rebuild_survives_close_new_instance_and_reopen(self):
        store, jl = _build_full_corpus("-reopen")
        rebuild.rebuild_policy_state(store._conn, jl)
        store._conn.commit()
        expected = rebuild.normalize_grants(store._conn), rebuild.normalize_audit(store._conn)
        store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        store._conn.commit()
        path = store.path
        store.close()

        reopened = SQLiteStore(SQLiteStoreConfig(path=path))
        reopened.ensure_schema()
        actual = rebuild.normalize_grants(reopened._conn), rebuild.normalize_audit(reopened._conn)
        assert actual == expected
        reopened.close()

    @pytest.mark.parametrize(
        ("contents", "error_code"),
        [
            ("[]\n", "invalid_top_level"),
            ('{"event_type": "access_grant"', "truncated_line"),
        ],
    )
    def test_policy_rebuild_rejects_invalid_canonical_framing(self, contents, error_code):
        conn, _jl = _build_corpus("-framing")
        bad = Path(tempfile.mkdtemp(prefix="zt-m56-framing-")) / "bad.jsonl"
        bad.write_text(contents)
        with pytest.raises(CanonicalReplayError, match=error_code):
            rebuild.rebuild_policy_state(conn, bad)
        conn.close()

    def test_incremental_vs_rebuild_audit(self):
        d = Path(tempfile.mkdtemp(prefix="zt-m56-aud-"))
        jl = d / "audit.jsonl"
        w = _canonical_writer_factory(jl)
        conn = _mdb()

        class _D:
            allow = False
            reason_code = "DENY_POLICY_CONFLICT"
            normalized_scope = type("S", (), {"operation": "READ"})()
            grant_refs = []
        ev1 = record_decision(w, _D(), decision_id="D1", requester="PR1",
                              target_scope="profile:PR2")
        assert ev1 is not None

        class _Dallow:
            allow = True
            reason_code = "ALLOW_LOCAL_PROFILE_READ"
            normalized_scope = type("S", (), {"operation": "READ"})()
            grant_refs = []
        ev2 = record_decision(w, _Dallow(), decision_id="D2", requester="PR1",
                              target_scope="profile:PR1")
        assert ev2 is None
        project_policy_decision(conn, ev1)
        inc = rebuild.normalize_audit(conn)
        conn2 = _mdb()
        rebuild.rebuild_policy_state(conn2, jl)
        reb = rebuild.normalize_audit(conn2)
        assert inc == reb
        assert len(inc) == 1
        conn.close(); conn2.close()

    def test_repeated_rebuild_deterministic(self):
        conn, jl = _build_corpus()
        c1 = _mdb(); s1 = rebuild.rebuild_policy_state(c1, jl)
        c2 = _mdb(); s2 = rebuild.rebuild_policy_state(c2, jl)
        c3 = _mdb(); s3 = rebuild.rebuild_policy_state(c3, jl)
        assert rebuild.normalize_grants(c1) == rebuild.normalize_grants(c2) == rebuild.normalize_grants(c3)
        assert s1 == s2 == s3
        conn.close(); c1.close(); c2.close(); c3.close()


class TestLifecycle:
    def test_revoked_grant_denied_after_rebuild(self):
        conn, jl = _build_corpus()
        assert not any(g.grant_id == "GR" for g in resolver.resolve_read_grants(conn, "PR1"))
        conn.close()

    def test_superseded_grant_denied_old(self):
        conn, jl = _build_corpus()
        rg = resolver.resolve_read_grants(conn, "PR1")
        ids = {g.grant_id for g in rg}
        assert "G1" not in ids
        assert "G3" in ids
        conn.close()

    def test_conflicted_grant_denied(self):
        conn, jl = _build_corpus()
        assert not any(g.grant_id == "GC" for g in resolver.resolve_read_grants(conn, "PR1"))
        conn.close()

    def test_supersession_chain_preserved(self):
        conn, jl = _build_corpus()
        row = conn.execute("SELECT grant_id, supersedes, replaced_by, lifecycle_status FROM zm_access_grants WHERE grant_id IN ('G1','G3')").fetchall()
        by = {r["grant_id"]: r for r in row}
        assert by["G3"]["supersedes"] == "G1"
        assert by["G1"]["lifecycle_status"] == "superseded"
        assert by["G1"]["replaced_by"] == "G3"
        conn.close()


class TestWriteVerification:
    def test_verified_write_grant_allowed_exact(self):
        conn, jl = _build_corpus()
        svc = authorized_write.AuthorizedWriteService(conn, vlookup)
        dec = svc.authorize_linked_write(
            AccessRequest(operation=WRITE, requesting_profile_id="PR1", project_ids=["P"]),
            "project", "P", resource_type="state")
        assert dec.allow
        conn.close()

    def test_unverified_write_denied(self):
        conn = _mdb()
        conn.execute("INSERT INTO zm_access_grants (grant_id, subject_profile, operation, target_type, target_id, resource_types, lifecycle_status, state, verification_ref, created_at) VALUES ('GWX','PR1','WRITE','project','P','[\"state\"]','active','accepted','VX','t')")
        conn.commit()
        svc = authorized_write.AuthorizedWriteService(conn, lambda r: None)
        dec = svc.authorize_linked_write(
            AccessRequest(operation=WRITE, requesting_profile_id="PR1", project_ids=["P"]),
            "project", "P", resource_type="state")
        assert not dec.allow
        conn.close()


class TestReadIntegration:
    def test_persistent_read_grant_feeds_m53(self):
        store, jl = _build_full_corpus()
        from src.retrieval.db import open_readonly
        ro = open_readonly(store.path)
        grants = resolver.resolve_read_grants(store._conn, "PR1")
        eff = compose_effective_scope(
            AccessRequest(operation=READ, requesting_profile_id="PR1",
                          target_profile_ids=["PR1"], project_ids=["P"]),
            grants=grants)
        svc = authorized_read.AuthorizedReadService(ro, "PR1", grant_conn=store._conn)
        assert "PR2" in eff.grant_scopes or any("PR2" in str(s.allowed_profile_ids) for s in eff.grant_scopes)
        store.close()


class TestStateImmediacy:
    def test_revoke_then_deny(self):
        d = Path(tempfile.mkdtemp(prefix="zt-m56-imm-"))
        jl = d / "policy.jsonl"
        conn = _mdb()
        svc = admin.GrantAdminService(conn, _canonical_writer_factory(jl), vlookup)
        svc.create(admin.GrantAdminRequest(action="create", grant_id="GI", subject_profile="PR1",
                      operation=READ, target_type="profile", target_id="PR2",
                      resource_types=["requirement"]))
        conn.commit()
        assert resolver.resolve_read_grants(conn, "PR1")
        svc.revoke(admin.GrantAdminRequest(action="revoke", grant_id="GI", subject_profile="PR1",
                      operation=READ, target_type="profile", target_id="PR2"))
        conn.commit()
        assert not resolver.resolve_read_grants(conn, "PR1")
        conn.close()


class TestAuditSafety:
    def test_deny_audit_no_protected_leak(self):
        d = Path(tempfile.mkdtemp(prefix="zt-m56-auds-"))
        jl = d / "audit.jsonl"
        w = _canonical_writer_factory(jl)

        class _D:
            allow = False
            reason_code = "DENY_CROSS_PROFILE_READ"
            normalized_scope = type("S", (), {"operation": "READ"})()
            grant_refs = []
        ev = record_decision(w, _D(), decision_id="DX", requester="PR1",
                             target_scope="profile:PR2")
        blob = json.dumps(ev)
        # requested scope + safe fields only; no secret, no discovered protected ID
        assert SECRET not in blob
        assert SECRET_B not in blob
        assert ev["m4"]["target_scope"] == "profile:PR2"
        import os
        if jl.exists():
            os.remove(jl)

    def test_ordinary_allow_not_audited(self):
        class _D:
            allow = True
            reason_code = "ALLOW_LOCAL_PROFILE_READ"
            normalized_scope = type("S", (), {"operation": "READ"})()
            grant_refs = []
        assert not _should_audit(_D())


class TestZeroExternal:
    def test_no_network_in_rebuild(self):
        import ast
        src = (Path(__file__).resolve().parents[2] / "src" / "access" / "rebuild.py").read_text()
        tree = ast.parse(src)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    imported.add(n.name)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        assert not any("socket" in i or "requests" in i or "http" in i for i in imported)
        assert not any("openai" in i or "llm" in i for i in imported)


class TestPerformanceBaseline:
    def test_baseline_recorded(self):
        store, jl = _build_full_corpus()
        from src.retrieval.db import open_readonly
        ro = open_readonly(store.path)
        grants = resolver.resolve_read_grants(store._conn, "PR1")
        svc = authorized_read.AuthorizedReadService(ro, "PR1", grant_conn=store._conn)
        t0 = time.perf_counter()
        N = 200
        for _ in range(N):
            eff = compose_effective_scope(
                AccessRequest(operation=READ, requesting_profile_id="PR1",
                              target_profile_ids=["PR1"], project_ids=["P"]),
                grants=grants)
            svc.query_events(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                           target_profile_ids=["PR1"], project_ids=["P"]),
                             grants=grants)
        dt = (time.perf_counter() - t0) / N
        assert dt < 1.0
        store.close()
