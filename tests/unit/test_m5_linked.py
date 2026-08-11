"""M5.5 focused tests — linked-resource authorization boundary hardening.

Core invariant: AUTHORIZED SOURCE does NOT imply AUTHORIZED TARGET.

Synthetic secrets are used; they must never appear in results/errors/provenance.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.access import admin, authorized_read, authorized_write, linked, resolver
from src.access.contracts import AccessRequest, ReasonCode, READ, WRITE
from src.access.grants import AuthorizedReadGrant, compose_effective_scope
from src.storage.migrations import CURRENT_SCHEMA_VERSION, migrate_8
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig

from tests.unit.test_m3_query import _make_env, _write_jsonl, _open_store, _checkpoint_and_close

SECRET = "SK-M5L-DONTLEAK-7a1b2c3d"
SECRET_B = "secret-B-content-" + SECRET
SECRET_Q = "secret-Q-content-" + SECRET
RT_REQ = '["requirement"]'
RT_STATE = '["state"]'


def _mdb():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    migrate_8.up(conn, "t")
    conn.commit()
    return conn


def _vlookup(ref):
    class _V:
        def __init__(self, s):
            self.verification_status = s
    if ref == "V1":
        return _V("verified")
    if ref == "V2":
        return _V("unverified")
    return None


def _grant(subject, operation, target_type, target_id, resource_types=None, state="active",
          lifecycle_status="active", grant_id=None, supersedes=None):
    return AuthorizedReadGrant(
        grant_id=grant_id or f"G-{subject}-{target_id}-{operation}",
        subject_profile=subject,
        operation=operation,
        target_type=target_type,
        target_id=target_id,
        resource_types=list(resource_types or ["requirement"]),
        state=state,
        lifecycle_status=lifecycle_status,
        supersedes=supersedes,
    )


def _build_corpus(tmp_path):
    jl = tmp_path / "corpus.jsonl"
    # Targets ingested BEFORE sources so the M2 relation projection can link edges.
    _write_jsonl(jl, [
        # b1 (PR2/P) is the target of a1's outgoing link
        _make_env("b1", trace_id="tr-b", project_id="P", profile_id="PR2",
                  sanitized_content={"text": SECRET_B}, source_event_id="a1"),
        # b2 (PR2/Q) unrelated project
        _make_env("b2", trace_id="tr-b2", project_id="Q", profile_id="PR2",
                  sanitized_content={"text": SECRET_Q}),
        # a1 (PR1/P) source: links OUT to b1; parent of c1
        _make_env("a1", trace_id="tr-a", project_id="P", sanitized_content={"text": "a1 local"},
                  relation_ids=["b1"]),
        # a2 (PR1/P) links to a1 (same-scope)
        _make_env("a2", trace_id="tr-a2", project_id="P", sanitized_content={"text": "a2 local"},
                  relation_ids=["a1"]),
        # c1 (PR2/P) child of a1 (parent_trace_id)
        _make_env("c1", trace_id="tr-c", project_id="P", profile_id="PR2",
                  sanitized_content={"text": "child of a1"},
                  parent_trace_id="tr-a"),
    ])
    store = _open_store(tmp_path)
    from src.storage.ingest import rebuild_from_jsonl
    rebuild_from_jsonl(store, [jl])
    _checkpoint_and_close(store)
    return SQLiteStore(SQLiteStoreConfig(path=tmp_path / "m.sqlite"))


class TestRelationTraversal:
    def test_a_to_a_same_scope_allowed(self, tmp_path):
        store = _build_corpus(tmp_path)
        svc = authorized_read.AuthorizedReadService(store, "PR1")
        res = svc.get_related(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                            target_profile_ids=["PR1"], project_ids=["P"]), "a2")
        assert res.allowed
        assert res.denied is False
        store.close()

    def test_a_to_b_cross_profile_denied(self, tmp_path):
        store = _build_corpus(tmp_path)
        svc = authorized_read.AuthorizedReadService(store, "PR1")
        res = svc.get_related(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                            target_profile_ids=["PR1"], project_ids=["P"]), "a1",
                               relation_type="derived_from")
        assert not res.allowed
        assert res.denied
        assert SECRET_B not in str(res.items)
        store.close()

    def test_a_to_b_exact_read_grant_allowed(self, tmp_path):
        store = _build_corpus(tmp_path)
        grants = [_grant("PR1", READ, "profile", "PR2", ["requirement"])]
        svc = authorized_read.AuthorizedReadService(store, "PR1", grant_conn=store._conn)
        res = svc.get_related(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                            target_profile_ids=["PR1"], project_ids=["P"]), "a1",
                               relation_type="derived_from", grants=grants)
        assert res.allowed
        store.close()

    def test_a_p_to_b_q_denied(self, tmp_path):
        store = _build_corpus(tmp_path)
        grants = [_grant("PR1", READ, "profile", "PR2", ["requirement"])]
        svc = authorized_read.AuthorizedReadService(store, "PR1", grant_conn=store._conn)
        res = svc.get_related(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                            target_profile_ids=["PR1"], project_ids=["P"]), "a1",
                               grants=grants)
        ids = {getattr(i.target, "event_id", None) for i in res.items}
        assert "b2" not in ids
        store.close()

    def test_incoming_checked(self, tmp_path):
        store = _build_corpus(tmp_path)
        svc = authorized_read.AuthorizedReadService(store, "PR1")
        res = svc.get_incoming(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                             target_profile_ids=["PR1"], project_ids=["P"]), "a1")
        assert not res.allowed
        store.close()

    def test_outgoing_checked(self, tmp_path):
        store = _build_corpus(tmp_path)
        svc = authorized_read.AuthorizedReadService(store, "PR1")
        res = svc.get_outgoing(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                              target_profile_ids=["PR1"], project_ids=["P"]), "a1")
        assert not res.allowed
        store.close()


class TestParentChild:
    def test_authorized_parent_to_unauthorized_child_denied(self, tmp_path):
        store = _build_corpus(tmp_path)
        svc = authorized_read.AuthorizedReadService(store, "PR1")
        res = svc.get_children(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                              target_profile_ids=["PR1"], project_ids=["P"]), "a1")
        assert not res.allowed
        store.close()

    def test_authorized_child_to_unauthorized_parent_denied(self, tmp_path):
        store = _build_corpus(tmp_path)
        svc = authorized_read.AuthorizedReadService(store, "PR1")
        res = svc.get_parent(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                            target_profile_ids=["PR1"], project_ids=["P"]), "c1")
        assert not res.allowed
        store.close()

    def test_exact_grant_permits_exact_child_scope(self, tmp_path):
        store = _build_corpus(tmp_path)
        grants = [_grant("PR1", READ, "profile", "PR2", ["requirement"])]
        svc = authorized_read.AuthorizedReadService(store, "PR1", grant_conn=store._conn)
        res = svc.get_children(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                             target_profile_ids=["PR1"], project_ids=["P"]), "a1",
                               grants=grants)
        assert res.allowed
        store.close()


class TestSourceEvent:
    def test_m4_authorized_source_authorized_allowed(self, tmp_path):
        store = _build_corpus(tmp_path)
        conn = store._conn
        conn.execute("INSERT INTO zm_requirements (requirement_id, project_id, profile_id, lifecycle_status, state, source_event_id, created_at) VALUES ('R1','P','PR1','active','accepted','a1','t')")
        conn.commit()
        svc = authorized_read.AuthorizedReadService(store, "PR1", grant_conn=conn)
        from src.project_memory import reader as m4
        view = m4.get_requirement(linked._as_readonly(conn), "R1", include_source_event=True)
        eff = svc._gate(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                      target_profile_ids=["PR1"], project_ids=["P"]))
        linked.harden_m4_source_event(eff, svc, view)
        assert view.source_event is not None
        store.close()

    def test_m4_source_event_cannot_bypass_scope(self, tmp_path):
        store = _build_corpus(tmp_path)
        conn = store._conn
        conn.execute("INSERT INTO zm_requirements (requirement_id, project_id, profile_id, lifecycle_status, state, source_event_id, created_at) VALUES ('R2','P','PR1','active','accepted','b1','t')")
        conn.commit()
        svc = authorized_read.AuthorizedReadService(store, "PR1", grant_conn=conn)
        from src.project_memory import reader as m4
        view = m4.get_requirement(linked._as_readonly(conn), "R2", include_source_event=True)
        eff = svc._gate(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                      target_profile_ids=["PR1"], project_ids=["P"]))
        linked.harden_m4_source_event(eff, svc, view)
        assert view.source_event is None
        store.close()

    def test_source_event_existence_not_leaked(self, tmp_path):
        store = _build_corpus(tmp_path)
        conn = store._conn
        conn.execute("INSERT INTO zm_requirements (requirement_id, project_id, profile_id, lifecycle_status, state, source_event_id, created_at) VALUES ('R2','P','PR1','active','accepted','b1','t')")
        conn.commit()
        svc = authorized_read.AuthorizedReadService(store, "PR1", grant_conn=conn)
        from src.project_memory import reader as m4
        view = m4.get_requirement(linked._as_readonly(conn), "R2", include_source_event=True)
        eff = svc._gate(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                      target_profile_ids=["PR1"], project_ids=["P"]))
        linked.harden_m4_source_event(eff, svc, view)
        assert view.source_event is None
        store.close()


class TestSupersession:
    def test_supersession_cannot_bypass_scope(self):
        conn = _mdb()
        conn.execute("INSERT INTO zm_access_grants (grant_id, subject_profile, operation, target_type, target_id, lifecycle_status, state, supersedes, created_at) VALUES ('G0','PR1','READ','profile','PR2','superseded','accepted',NULL,'t0')")
        conn.execute("INSERT INTO zm_access_grants (grant_id, subject_profile, operation, target_type, target_id, lifecycle_status, state, supersedes, replaced_by, created_at) VALUES ('G','PR1','READ','profile','PR1','active','accepted','G0','G','t1')")
        conn.commit()
        rg = resolver.resolve_read_grants(conn, "PR1")
        ids = {g.grant_id for g in rg}
        assert "G" in ids
        assert not any(g.grant_id == "G0" and g.target_id == "PR2" for g in rg if g.lifecycle_status == "active")
        conn.close()


class TestVerificationArtifact:
    def test_requirement_link_does_not_authorize_verification(self, tmp_path):
        store = _build_corpus(tmp_path)
        conn = store._conn
        conn.execute("INSERT INTO zm_requirements (requirement_id, project_id, profile_id, lifecycle_status, state, linked_verification_ids, source_event_id, created_at) VALUES ('R1','P','PR1','active','accepted','V-X','a1','t')")
        conn.commit()
        grants = [_grant("PR1", READ, "project", "P", ["requirement"])]
        svc = authorized_read.AuthorizedReadService(store, "PR1", grant_conn=conn)
        res = svc.m4_requirement_verifications(
            AccessRequest(operation=READ, requesting_profile_id="PR1", project_ids=["P"]), "P", "R1",
            grants=grants)
        assert not res.allowed or res.items == []
        store.close()

    def test_artifact_link_does_not_authorize_requirement(self, tmp_path):
        store = _build_corpus(tmp_path)
        conn = store._conn
        conn.execute("INSERT INTO zm_requirements (requirement_id, project_id, profile_id, lifecycle_status, state, linked_artifact_ids, source_event_id, created_at) VALUES ('R1','P','PR1','active','accepted','ART-X','a1','t')")
        conn.commit()
        grants = [_grant("PR1", READ, "project", "P", ["requirement"])]
        svc = authorized_read.AuthorizedReadService(store, "PR1", grant_conn=conn)
        res = svc.m4_requirement_artifacts(
            AccessRequest(operation=READ, requesting_profile_id="PR1", project_ids=["P"]), "P", "R1",
            grants=grants)
        assert not res.allowed or res.items == []
        store.close()


class TestResourceType:
    def test_requirements_only_grant_cannot_expose_decision(self):
        conn = _mdb()
        conn.execute("INSERT INTO zm_access_grants (grant_id, subject_profile, operation, target_type, target_id, resource_types, lifecycle_status, state, created_at) VALUES ('G','PR1','READ','project','P',?, 'active','accepted','t')", (RT_REQ,))
        conn.commit()
        rg = resolver.resolve_read_grants(conn, "PR1")
        g = rg[0]
        assert g.resource_types == ["requirement"]
        from src.access.contracts import AccessRequest as AR
        eff = compose_effective_scope(AR(operation=READ, requesting_profile_id="PR1", project_ids=["P"],
                                         resource_type="decision"), grants=rg)
        assert "decision" not in eff.grant_resource_types.get("P", [])
        conn.close()


class TestProfileProjectSpace:
    def test_bp_grant_cannot_expose_bq(self):
        conn = _mdb()
        conn.execute("INSERT INTO zm_access_grants (grant_id, subject_profile, operation, target_type, target_id, resource_types, lifecycle_status, state, created_at) VALUES ('G','PR1','READ','profile','PR2',?, 'active','accepted','t')", (RT_REQ,))
        conn.commit()
        rg = resolver.resolve_read_grants(conn, "PR1")
        g = rg[0]
        assert g.target_id == "PR2"
        assert g.target_type == "profile"
        from src.access.contracts import AccessRequest as AR
        eff = compose_effective_scope(AR(operation=READ, requesting_profile_id="PR1",
                                         target_profile_ids=["PR3"]), grants=rg)
        assert not eff.allow
        conn.close()

    def test_same_project_cannot_cross_profile(self):
        conn = _mdb()
        conn.execute("INSERT INTO zm_access_grants (grant_id, subject_profile, operation, target_type, target_id, resource_types, lifecycle_status, state, created_at) VALUES ('G','PR1','READ','project','P',?, 'active','accepted','t')", (RT_REQ,))
        conn.commit()
        rg = resolver.resolve_read_grants(conn, "PR1")
        from src.access.contracts import AccessRequest as AR
        eff = compose_effective_scope(AR(operation=READ, requesting_profile_id="PR1",
                                         target_profile_ids=["PR1"], project_ids=["P"]), grants=rg)
        assert eff.allow
        conn.close()


class TestGlobalIsolation:
    def test_global_cannot_bridge_protected_profile(self, tmp_path):
        store = _build_corpus(tmp_path)
        svc = authorized_read.AuthorizedReadService(store, "PR1")
        res = svc.get_related(AccessRequest(operation=READ, requesting_profile_id="PR1"), "a1")
        assert not res.allowed
        store.close()

    def test_isolated_mode_remains_closed(self, tmp_path):
        store = _build_corpus(tmp_path)
        svc = authorized_read.AuthorizedReadService(store, "PR1")
        res = svc.get_related(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                            isolated_mode=True), "a1")
        assert not res.allowed
        store.close()


class TestGrantState:
    def test_active_grant_allows_exact_link(self):
        conn = _mdb()
        conn.execute("INSERT INTO zm_access_grants (grant_id, subject_profile, operation, target_type, target_id, resource_types, lifecycle_status, state, created_at) VALUES ('G','PR1','READ','profile','PR2',?, 'active','accepted','t')", (RT_REQ,))
        conn.commit()
        assert resolver.resolve_read_grants(conn, "PR1")

    def test_revoked_grant_denies(self):
        conn = _mdb()
        conn.execute("INSERT INTO zm_access_grants (grant_id, subject_profile, operation, target_type, target_id, resource_types, lifecycle_status, state, created_at) VALUES ('G','PR1','READ','profile','PR2',?, 'active','revoked','t')", (RT_REQ,))
        conn.commit()
        assert not resolver.resolve_read_grants(conn, "PR1")

    def test_superseded_grant_denies(self):
        conn = _mdb()
        conn.execute("INSERT INTO zm_access_grants (grant_id, subject_profile, operation, target_type, target_id, resource_types, lifecycle_status, state, created_at) VALUES ('G','PR1','READ','profile','PR2',?, 'superseded','accepted','t')", (RT_REQ,))
        conn.commit()
        assert not resolver.resolve_read_grants(conn, "PR1")

    def test_deleted_grant_denies(self):
        conn = _mdb()
        conn.execute("INSERT INTO zm_access_grants (grant_id, subject_profile, operation, target_type, target_id, resource_types, lifecycle_status, state, created_at) VALUES ('G','PR1','READ','profile','PR2',?, 'deleted','accepted','t')", (RT_REQ,))
        conn.commit()
        assert not resolver.resolve_read_grants(conn, "PR1")

    def test_conflicted_grant_denies(self):
        conn = _mdb()
        conn.execute("INSERT INTO zm_access_grants (grant_id, subject_profile, operation, target_type, target_id, resource_types, lifecycle_status, state, created_at) VALUES ('G','PR1','READ','profile','PR2',?, 'conflicted','accepted','t')", (RT_REQ,))
        conn.commit()
        assert not resolver.resolve_read_grants(conn, "PR1")


class TestLinkedWrite:
    def test_read_grant_cannot_authorize_linked_write(self):
        conn = _mdb()
        conn.execute("INSERT INTO zm_access_grants (grant_id, subject_profile, operation, target_type, target_id, resource_types, lifecycle_status, state, created_at) VALUES ('G','PR1','READ','project','P',?, 'active','accepted','t')", (RT_REQ,))
        conn.commit()
        svc = authorized_write.AuthorizedWriteService(conn, _vlookup)
        dec = svc.authorize_linked_write(
            AccessRequest(operation=WRITE, requesting_profile_id="PR1", project_ids=["P"]),
            "project", "P")
        assert not dec.allow

    def test_linked_write_requires_independent_write_grant(self):
        conn = _mdb()
        conn.execute("INSERT INTO zm_access_grants (grant_id, subject_profile, operation, target_type, target_id, resource_types, lifecycle_status, state, verification_ref, created_at) VALUES ('GW','PR1','WRITE','project','P',?, 'active','accepted','V1','t')", (RT_STATE,))
        conn.commit()
        svc = authorized_write.AuthorizedWriteService(conn, _vlookup)
        dec = svc.authorize_linked_write(
            AccessRequest(operation=WRITE, requesting_profile_id="PR1", project_ids=["P"]),
            "project", "P", resource_type="state")
        assert dec.allow

    def test_denied_linked_write_does_not_invoke_writer(self):
        conn = _mdb()
        conn.execute("INSERT INTO zm_access_grants (grant_id, subject_profile, operation, target_type, target_id, resource_types, lifecycle_status, state, created_at) VALUES ('G','PR1','READ','project','P',?, 'active','accepted','t')", (RT_REQ,))
        conn.commit()
        svc = authorized_write.AuthorizedWriteService(conn, _vlookup)
        calls = []
        def writer(r):
            calls.append(1)
            return "M"
        dec, res = authorized_write.authorize_then_write(
            AccessRequest(operation=WRITE, requesting_profile_id="PR1", project_ids=["P"]),
            conn, _vlookup, writer)
        assert not dec.allow
        assert res is None and calls == []


class TestGrantAdminSeparation:
    def test_resource_link_cannot_invoke_grant_admin(self, tmp_path):
        store = _build_corpus(tmp_path)
        svc = authorized_read.AuthorizedReadService(store, "PR1")
        assert not hasattr(svc, "create_grant")
        assert not hasattr(svc, "revoke_grant")
        assert not hasattr(svc, "supersede_grant")
        res = svc.get_related(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                            target_profile_ids=["PR1"], project_ids=["P"]), "a1")
        assert not res.allowed
        store.close()

    def test_normal_access_request_cannot_convert_to_grant_admin(self):
        req = AccessRequest(operation=READ, requesting_profile_id="PR1")
        assert not hasattr(req, "action")
        assert not hasattr(req, "grant_id")


class TestSecurity:
    def test_denial_leaks_no_target_existence(self, tmp_path):
        store = _build_corpus(tmp_path)
        svc = authorized_read.AuthorizedReadService(store, "PR1")
        res = svc.get_related(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                            target_profile_ids=["PR1"], project_ids=["P"]), "a1")
        assert not res.allowed
        blob = str(res)
        assert SECRET_B not in blob
        assert "sqlite" not in blob.lower()
        assert "traceback" not in blob.lower()
        store.close()

    def test_unauthorized_synthetic_secret_absent(self, tmp_path):
        store = _build_corpus(tmp_path)
        svc = authorized_read.AuthorizedReadService(store, "PR1")
        res = svc.get_related(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                            target_profile_ids=["PR1"], project_ids=["P"]), "a1")
        assert SECRET_B not in str(res.items)
        store.close()

    def test_sqlite_read_workload_unchanged(self, tmp_path):
        store = _build_corpus(tmp_path)
        before = store._conn.execute("SELECT COUNT(*) FROM zm_access_grants").fetchone()[0]
        svc = authorized_read.AuthorizedReadService(store, "PR1")
        svc.get_related(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                      target_profile_ids=["PR1"], project_ids=["P"]), "a1")
        after = store._conn.execute("SELECT COUNT(*) FROM zm_access_grants").fetchone()[0]
        assert before == after
        store.close()

    def test_jsonl_unchanged(self, tmp_path):
        store = _build_corpus(tmp_path)
        jl = tmp_path / "corpus.jsonl"
        import hashlib
        h0 = hashlib.sha256(jl.read_bytes()).hexdigest()
        svc = authorized_read.AuthorizedReadService(store, "PR1")
        svc.get_related(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                      target_profile_ids=["PR1"], project_ids=["P"]), "a1")
        h1 = hashlib.sha256(jl.read_bytes()).hexdigest()
        assert h0 == h1
        store.close()

    def test_schema_remains_v8(self):
        assert CURRENT_SCHEMA_VERSION == 10
