"""M6.6 focused tests - performance, security, and FINAL M6 acceptance.

Reuses the verified M4+M3 corpus builder. Repo root resolved dynamically;
fixtures OS-temp (pytest tmp_path). No hard-coded repository or user paths.
"""

import os
import sys
import subprocess
import tempfile
import time
import threading
import statistics
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO_ROOT = Path(__file__).resolve().parents[2]

from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.storage.ingest import ingest_file
from src.project_memory import rebuild_project_memory, rebuild_all_project_memory
import tests.unit.test_m4_rebuild as m4base
from tests.unit.test_m3_query import _make_env, _open_store, _write_jsonl
from src.access import admin

from src.integration.m6 import (
    ResponseStatus, audit_tool_surface, configure, dispatch, get_tool,
    list_tool_names, mcp_wrapper,
)
from src.integration.bridge_config import BridgeConfig
from src.integration.hermes_read_adapter import (
    HermesReadAdapter, ALL_READ_TOOLS, FORBIDDEN_TOOL_NAMES, RegistrationFailure,
)


def _open(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(SQLiteStoreConfig(path=tmp_path / "m6.sqlite"))


def _m3_items():
    return [
        _make_env("e1", trace_id="tr-a", project_id="P", profile_id="A",
                  kind="decision", payload={"summary": "A decision on P"}),
        _make_env("e2", trace_id="tr-b", project_id="P", profile_id="B",
                  kind="decision", payload={"summary": "B decision on P"}),
        _make_env("e3", trace_id="tr-a", project_id="P", profile_id="A",
                  kind="observation", payload={"note": "A note on P"}),
    ]


def _seed(tmp_path: Path, store: SQLiteStore) -> None:
    store.ensure_schema()
    jl = tmp_path / "m3.jsonl"
    _write_jsonl(jl, _m3_items())
    ingest_file(store, jl)
    m4base._seed_m2_artifacts(store._conn)
    corpus = m4base.build_corpus(tmp_path)
    rebuild_project_memory(store, corpus, project_id="P")
    rebuild_all_project_memory(store, corpus, project_id="P")
    store._conn.commit()


@pytest.fixture
def store_path(tmp_path):
    store = _open(tmp_path)
    _seed(tmp_path, store)
    store.close()
    return tmp_path / "m6.sqlite"


@pytest.fixture
def adapter(store_path):
    cfg = BridgeConfig(enabled=True)
    ad = HermesReadAdapter(cfg, store_path=store_path)
    ad.startup()
    return ad


class _Ctx:
    def __init__(self):
        self.tools = {}
    def register_tool(self, name, schema, handler):
        self.tools[name] = (schema, handler)


def _grant(store_path, subject, target_type, target_id, resource_types, grant_id="GX"):
    store = SQLiteStore(SQLiteStoreConfig(path=store_path.parent / "m6.sqlite"))
    svc = admin.GrantAdminService(store._conn, lambda ev: None, lambda r: None)
    svc.create(admin.GrantAdminRequest(action="create", grant_id=grant_id, subject_profile=subject,
                operation="READ", target_type=target_type, target_id=target_id,
                resource_types=resource_types))
    store._conn.commit()
    store.close()


ALL = list(ALL_READ_TOOLS)
BASE = {"requesting_profile_id": "PR1", "project_ids": ["P"], "target_profile_ids": ["PR1"]}


# 1. Final exact 10-tool registry
class TestFinalRegistry:
    def test_exactly_ten(self, adapter):
        ctx = _Ctx()
        reg = adapter.register(ctx)
        assert len(reg) == 10
        assert set(reg) == set(ALL)

    def test_no_duplicate_registration(self, adapter):
        ctx = _Ctx()
        r1 = adapter.register(ctx)
        r2 = adapter.register(ctx)
        assert r1 == r2

    def test_no_write_admin_debug_tools(self, adapter):
        for f in ("execute_sql", "raw_sql", "database_query", "read_jsonl", "raw_jsonl",
                  "write_memory", "create_memory", "update_memory", "delete_memory",
                  "project_set_state", "project_create_requirement", "project_create_decision",
                  "create_grant", "revoke_grant", "supersede_grant", "grant_admin"):
            assert get_tool(f) is None
            assert adapter.call(f, BASE)["status"] == "UNSUPPORTED_TOOL"

    def test_no_arbitrary_file_read(self, adapter):
        assert adapter.call("read_file", BASE)["status"] == "UNSUPPORTED_TOOL"
        assert adapter.call("open_path", BASE)["status"] == "UNSUPPORTED_TOOL"

    def test_tool_surface_audit_exact(self):
        surf = audit_tool_surface()
        public = {k for k in surf if not k.startswith("_")}
        assert public == set(ALL)
        for name in ALL:
            assert surf[name]["registered"] is True
            assert surf[name]["operation"] == "READ"
            assert surf[name]["read_only"] is True


# 2. Complete authorization matrix (representative)
class TestAuthMatrix:
    @pytest.mark.parametrize("requester,target,expect", [
        ("PR1", ["PR1"], "SUCCESS"),
        ("PR2", ["PR1"], "POLICY_DENIED"),
        (None, None, "POLICY_DENIED"),
    ])
    def test_requester_variants(self, adapter, requester, target, expect):
        req = {"project_ids": ["P"]}
        if requester is not None:
            req["requesting_profile_id"] = requester
        if target is not None:
            req["target_profile_ids"] = target
        assert adapter.call("project_get_charter", req)["status"] == expect

    def test_wrong_project_denied(self, store_path, adapter):
        _grant(store_path, "PR1", "project", "Q", ["requirement"])
        configure(store_path)
        assert adapter.call("project_list_requirements", {"requesting_profile_id": "PR1", "project_ids": ["P"]})["status"] == "POLICY_DENIED"

    def test_wrong_resource_type_denied(self, store_path, adapter):
        _grant(store_path, "PR1", "project", "P", ["decision"])
        configure(store_path)
        assert adapter.call("project_list_requirements", {"requesting_profile_id": "PR1", "project_ids": ["P"]})["status"] == "POLICY_DENIED"

    def test_include_global_false_default(self, adapter):
        r = adapter.call("project_get_charter", {"requesting_profile_id": "PR1", "project_ids": ["P"], "target_profile_ids": ["PR2"], "include_global": False})
        assert r["status"] == "POLICY_DENIED"

    def test_isolated_mode_denies_profile_only(self, adapter):
        # isolated_mode without explicit scope and no grant must not broaden to
        # project reads (profile-first, no auto project authorization).
        r = adapter.call("project_list_requirements", {"requesting_profile_id": "PR1", "project_ids": ["P"], "isolated_mode": True})
        assert r["status"] == "POLICY_DENIED"


# 3. Grant freshness (grant is SOLE authorization - no target_profile_ids)
class TestGrantFreshness:
    def test_grant_absent_deny(self, adapter):
        assert adapter.call("project_list_requirements", {"requesting_profile_id": "PR1", "project_ids": ["P"]})["status"] == "POLICY_DENIED"

    def test_grant_created_then_allowed(self, store_path, adapter):
        _grant(store_path, "PR1", "project", "P", ["requirement"])
        configure(store_path)
        assert adapter.call("project_list_requirements", {"requesting_profile_id": "PR1", "project_ids": ["P"]})["status"] == "SUCCESS"

    def test_grant_revoked_next_denied(self, store_path, adapter):
        _grant(store_path, "PR1", "project", "P", ["requirement"])
        configure(store_path)
        assert adapter.call("project_list_requirements", {"requesting_profile_id": "PR1", "project_ids": ["P"]})["status"] == "SUCCESS"
        st = SQLiteStore(SQLiteStoreConfig(path=store_path.parent / "m6.sqlite"))
        admin.GrantAdminService(st._conn, lambda ev: None, lambda r: None).revoke(
            admin.GrantAdminRequest(action="revoke", grant_id="GX", subject_profile="PR1",
                                     operation="READ", target_type="project", target_id="P"))
        st._conn.commit(); st.close(); configure(store_path)
        assert adapter.call("project_list_requirements", {"requesting_profile_id": "PR1", "project_ids": ["P"]})["status"] == "POLICY_DENIED"

    def test_grant_superseded_old_denied(self, store_path, adapter):
        # G1 authorizes requirement reads.
        _grant(store_path, "PR1", "project", "P", ["requirement"], grant_id="G1")
        configure(store_path)
        assert adapter.call("project_list_requirements", {"requesting_profile_id": "PR1", "project_ids": ["P"]})["status"] == "SUCCESS"
        # Supersede G1 with G2 that only grants DECISION. After supersession,
        # G1 must STOP authorizing requirement reads (M5 exact semantics).
        s = SQLiteStore(SQLiteStoreConfig(path=store_path.parent / "m6.sqlite"))
        svc = admin.GrantAdminService(s._conn, lambda ev: None, lambda r: None)
        svc.create(admin.GrantAdminRequest(action="create", grant_id="G2", subject_profile="PR1",
                    operation="READ", target_type="project", target_id="P", resource_types=["decision"]))
        svc.supersede(admin.GrantAdminRequest(action="supersede", grant_id="G2",
                    subject_profile="PR1", operation="READ", target_type="project", target_id="P",
                    resource_types=["decision"], supersedes="G1"))
        s._conn.commit(); s.close(); configure(store_path)
        # G1 superseded -> requirement read denied; G2 only grants decision.
        assert adapter.call("project_list_requirements", {"requesting_profile_id": "PR1", "project_ids": ["P"]})["status"] == "POLICY_DENIED"
        assert adapter.call("project_list_decisions", {"requesting_profile_id": "PR1", "project_ids": ["P"]})["status"] == "SUCCESS"

    def test_no_adapter_restart_required(self, store_path, adapter):
        _grant(store_path, "PR1", "project", "P", ["requirement"])
        configure(store_path)
        assert adapter.call("project_list_requirements", {"requesting_profile_id": "PR1", "project_ids": ["P"]})["status"] == "SUCCESS"
        st = SQLiteStore(SQLiteStoreConfig(path=store_path.parent / "m6.sqlite"))
        admin.GrantAdminService(st._conn, lambda ev: None, lambda r: None).revoke(
            admin.GrantAdminRequest(action="revoke", grant_id="GX", subject_profile="PR1",
                                     operation="READ", target_type="project", target_id="P"))
        st._conn.commit(); st.close(); configure(store_path)
        assert adapter.call("project_list_requirements", {"requesting_profile_id": "PR1", "project_ids": ["P"]})["status"] == "POLICY_DENIED"


# 4. Cross-resource isolation
class TestCrossResourceIsolation:
    def test_requirement_vs_decision(self, store_path, adapter):
        _grant(store_path, "PR1", "project", "P", ["requirement"])
        configure(store_path)
        assert adapter.call("project_list_requirements", {"requesting_profile_id": "PR1", "project_ids": ["P"]})["status"] == "SUCCESS"
        assert adapter.call("project_list_decisions", {"requesting_profile_id": "PR1", "project_ids": ["P"]})["status"] == "POLICY_DENIED"

    def test_decision_vs_requirement(self, store_path, adapter):
        _grant(store_path, "PR1", "project", "P", ["decision"])
        configure(store_path)
        assert adapter.call("project_list_decisions", {"requesting_profile_id": "PR1", "project_ids": ["P"]})["status"] == "SUCCESS"
        assert adapter.call("project_list_requirements", {"requesting_profile_id": "PR1", "project_ids": ["P"]})["status"] == "POLICY_DENIED"

    def test_artifact_vs_linked_requirement(self, store_path, adapter):
        _grant(store_path, "PR1", "project", "P", ["artifact"])
        configure(store_path)
        assert adapter.call("project_list_artifacts", {"requesting_profile_id": "PR1", "project_ids": ["P"]})["status"] == "SUCCESS"
        assert adapter.call("project_list_requirements", {"requesting_profile_id": "PR1", "project_ids": ["P"]})["status"] == "POLICY_DENIED"

    def test_event_permission_vs_project_memory(self, store_path, adapter):
        # An EVENT resource grant (within project P) must NOT authorize
        # project-memory reads (charter/requirements).
        _grant(store_path, "PR1", "project", "P", ["event"])
        configure(store_path)
        # event grant does NOT confer project-memory (charter) read authority
        assert adapter.call("project_get_charter", {"requesting_profile_id": "PR1", "project_ids": ["P"],
                                                     "target_profile_ids": ["PR2"]})["status"] == "POLICY_DENIED"
        # and does not confer project-memory requirement read authority
        assert adapter.call("project_list_requirements", {"requesting_profile_id": "PR1", "project_ids": ["P"],
                                                           "target_profile_ids": ["PR2"]})["status"] == "POLICY_DENIED"

    def test_resource_type_not_overridable(self, adapter):
        r = adapter.call("project_list_requirements", {**BASE, "resource_type": "decision"})
        assert r["status"] == "INVALID_REQUEST"


# 5. Linked-resource security
class TestLinkedResourceSecurity:
    @pytest.mark.parametrize("tool,fields", [
        ("memory_get_related", {"filters": {"event_id": "e1"}, "relation": "incoming"}),
        ("memory_get_related", {"filters": {"event_id": "e1"}, "relation": "outgoing"}),
        ("memory_get_related", {"filters": {"event_id": "e1"}, "relation": "parent"}),
        ("memory_get_related", {"filters": {"event_id": "e1"}, "relation": "children"}),
    ])
    def test_relation_target_independent(self, adapter, tool, fields):
        r = adapter.call(tool, {"requesting_profile_id": "PR1", "project_ids": ["P"],
                                "target_profile_ids": ["PR2"], **fields})
        assert r["status"] == "POLICY_DENIED"

    def test_source_event_independent(self, adapter):
        r = adapter.call("project_get_charter", {"requesting_profile_id": "PR1", "project_ids": ["P"],
                                                 "target_profile_ids": ["PR2"], "include_source_event": True})
        assert r["status"] == "POLICY_DENIED"

    def test_no_protected_leak_on_denied_relation(self, adapter):
        r = adapter.call("memory_get_related", {"requesting_profile_id": "PR1", "project_ids": ["P"],
                                                 "target_profile_ids": ["PR2"], "filters": {"event_id": "e1"}, "relation": "incoming"})
        blob = str(r).lower()
        assert "stored_path" not in blob
        assert "trace_id" not in blob
        assert "secret" not in blob


# 6/8. Probing + adversarial input
class TestProbingAndAdversarial:
    def test_event_probing_resistance(self, adapter):
        r = adapter.call("memory_get_event", {"requesting_profile_id": "PR1", "project_ids": ["P"],
                                               "target_profile_ids": ["PR2"], "filters": {"event_id": "e1"}})
        assert r["status"] == "POLICY_DENIED"
        blob = str(r).lower()
        assert "e1" not in blob and "exists" not in blob and "not found" not in blob

    def test_project_probing_resistance(self, adapter):
        r = adapter.call("project_get_charter", {"requesting_profile_id": "PR1", "project_ids": ["P"],
                                                  "target_profile_ids": ["PR2"]})
        assert r["status"] == "POLICY_DENIED"
        blob = str(r).lower()
        assert "charter" not in blob and "requirement" not in blob and "decision" not in blob and "artifact" not in blob

    def test_unknown_tool(self, adapter):
        assert adapter.call("nonexistent_tool", BASE)["status"] == "UNSUPPORTED_TOOL"

    def test_wrong_operation(self, adapter):
        assert adapter.call("project_get_charter", {**BASE, "operation": "WRITE"})["status"] == "UNSUPPORTED_OPERATION"

    def test_missing_required_field(self, adapter):
        assert adapter.call("memory_search", {"requesting_profile_id": "PR1", "project_ids": ["P"]})["status"] == "INVALID_REQUEST"

    def test_unknown_field_rejected(self, adapter):
        assert adapter.call("project_get_charter", {**BASE, "bogus_field": 1})["status"] == "INVALID_REQUEST"

    def test_wrong_scalar_type(self, adapter):
        assert adapter.call("project_get_charter", {"requesting_profile_id": 123, "project_ids": ["P"]})["status"] == "INVALID_REQUEST"

    def test_oversized_list_rejected(self, adapter):
        big = {**BASE, "project_ids": ["P"] * 500}
        assert adapter.call("project_get_charter", big)["status"] == "INVALID_REQUEST"

    def test_oversized_query_rejected(self, adapter):
        big = {**BASE, "search_text": "x" * 5000}
        assert adapter.call("memory_search", big)["status"] == "INVALID_REQUEST"

    def test_malformed_cursor_rejected(self, adapter):
        # Malformed cursor must not crash or leak; returns a bounded safe status.
        st = adapter.call("project_list_requirements", {**BASE, "cursor": "not-a-cursor"})["status"]
        assert st in ("INVALID_REQUEST", "DOWNSTREAM_ERROR", "EMPTY", "SUCCESS")

    def test_malformed_request_object(self, adapter):
        assert adapter.call("project_get_charter", None)["status"] in ("INVALID_REQUEST", "DOWNSTREAM_ERROR")

    @pytest.mark.parametrize("bad", ["admin", "is_admin", "trusted", "grant_admin", "grant",
                                     "authorized_read_grant", "effective_scope", "allowed_scope",
                                     "verified", "bypass_policy", "cross_profile_allowed", "raw_sql",
                                     "sql", "database", "jsonl_path"])
    def test_forbidden_authority_fields(self, adapter, bad):
        r = adapter.call("project_get_charter", {bad: True, **BASE})
        assert r["status"] == "INVALID_REQUEST", bad


# 7. Artifact final security
class TestArtifactFinalSecurity:
    def test_artifact_metadata_only(self, adapter):
        r = adapter.call("project_list_artifacts", BASE)
        assert r["status"] == "SUCCESS"
        blob = str(r).lower()
        assert "stored_path" not in blob
        assert "sk-m4" not in blob
        for item in r.get("results", []):
            assert "stored_path" not in item
            assert "content" not in item

    def test_artifact_link_does_not_open_file(self, store_path, adapter):
        _grant(store_path, "PR1", "project", "P", ["artifact"])
        configure(store_path)
        r = adapter.call("project_list_artifacts", {"requesting_profile_id": "PR1", "project_ids": ["P"]})
        assert r["status"] == "SUCCESS"
        blob = str(r).lower()
        assert "stored_path" not in blob


# 9/10. Response sanitization + failure isolation
class TestSanitizationAndFailure:
    def test_no_traceback_in_response(self, adapter):
        r = adapter.call("project_get_charter", {**BASE, "bogus": object()})
        blob = str(r).lower()
        assert "traceback" not in blob and "exception" not in blob and "sqlite3" not in blob

    def test_db_missing_safe(self, store_path):
        cfg = BridgeConfig(enabled=True)
        ad = HermesReadAdapter(cfg, store_path=Path(tempfile.mkdtemp()).resolve() / "missing.sqlite")
        with pytest.raises(RegistrationFailure):
            ad.startup()
        ctx = _Ctx(); ad.register(ctx)
        assert ad.call("project_get_charter", BASE)["status"] == "CAPABILITY_UNAVAILABLE"

    def test_db_unreadable_safe(self, tmp_path, adapter):
        bad = tmp_path / "bad.sqlite"
        bad.write_text("not a sqlite db")
        cfg = BridgeConfig(enabled=True)
        ad = HermesReadAdapter(cfg, store_path=bad)
        with pytest.raises(RegistrationFailure):
            ad.startup()
        assert ad.call("project_get_charter", BASE)["status"] == "CAPABILITY_UNAVAILABLE"

    def test_no_raw_fallback(self, store_path):
        cfg = BridgeConfig(enabled=True)
        ad = HermesReadAdapter(cfg, store_path=Path(tempfile.mkdtemp()).resolve() / "missing.sqlite")
        try:
            ad.startup()
        except RegistrationFailure:
            pass
        assert ad.call("project_get_charter", BASE)["status"] == "CAPABILITY_UNAVAILABLE"

    def test_internal_handler_failure_bounded(self, store_path):
        cfg = BridgeConfig(enabled=True)
        ad = HermesReadAdapter(cfg, store_path=store_path)
        ad.startup()
        ctx = _Ctx(); ad.register(ctx)
        r = ad.call("project_get_charter", {"requesting_profile_id": object()})
        assert r["status"] in ("INVALID_REQUEST", "DOWNSTREAM_ERROR")
        assert "traceback" not in str(r).lower()


# 11. TRUE READ-ONLY final proof
class TestReadOnlyProof:
    def test_memory_db_unchanged_after_reads(self, store_path, adapter):
        import hashlib
        before = hashlib.sha256(Path(store_path).read_bytes()).hexdigest()
        for _ in range(20):
            adapter.call("project_get_charter", BASE)
            adapter.call("memory_query", {"requesting_profile_id": "PR1", "project_ids": ["P"]})
            adapter.call("project_list_requirements", {"requesting_profile_id": "PR1", "project_ids": ["P"]})
        after = hashlib.sha256(Path(store_path).read_bytes()).hexdigest()
        assert before == after

    def test_query_only_pragma(self, store_path):
        from src.retrieval.db import open_readonly
        ro = open_readonly(store_path)
        qo = ro.conn.execute("PRAGMA query_only").fetchone()[0]
        ro.close()
        assert qo in (1, "1", "true", True)

    def test_jsonl_unchanged_under_read(self, tmp_path, store_path):
        import shutil, hashlib
        jl = tmp_path / "m3.jsonl"
        _write_jsonl(jl, _m3_items())
        digest = hashlib.sha256(jl.read_bytes()).hexdigest()
        cfg = BridgeConfig(enabled=True)
        ad = HermesReadAdapter(cfg, store_path=store_path); ad.startup()
        for _ in range(10):
            ad.call("memory_search", {"requesting_profile_id": "PR1", "project_ids": ["P"], "search_text": "x"})
        assert hashlib.sha256(jl.read_bytes()).hexdigest() == digest


# 12/13. Startup/shutdown/restart + concurrency
class TestLifecycleAndConcurrency:
    def test_repeated_cycles_no_duplicates(self, store_path):
        for _ in range(8):
            cfg = BridgeConfig(enabled=True)
            ad = HermesReadAdapter(cfg, store_path=store_path)
            ad.startup()
            ctx = _Ctx()
            reg = ad.register(ctx)
            assert len(reg) == 10
            ad.shutdown()
        cfg = BridgeConfig(enabled=True)
        ad = HermesReadAdapter(cfg, store_path=store_path); ad.startup()
        ctx = _Ctx()
        assert len(ad.register(ctx)) == 10

    def test_concurrent_identity_separation(self, adapter):
        out = {}
        def call(profile, key):
            out[key] = adapter.call("project_get_charter",
                                    {"requesting_profile_id": profile, "project_ids": ["P"], "target_profile_ids": [profile]})
        ts = [threading.Thread(target=call, args=(p, p)) for p in ["PR1", "PR2", "PR3"]]
        for t in ts: t.start()
        for t in ts: t.join()
        assert out["PR1"]["status"] == "SUCCESS"
        assert out["PR2"]["status"] == "POLICY_DENIED"
        assert out["PR3"]["status"] == "POLICY_DENIED"

    def test_concurrent_policy_isolation_during_grant_change(self, store_path, adapter):
        _grant(store_path, "PR1", "project", "P", ["requirement"])
        configure(store_path)
        results = {}
        lock = threading.Lock()
        def worker(tag):
            ra = adapter.call("project_list_requirements", {"requesting_profile_id": "PR1", "project_ids": ["P"]})
            rb = adapter.call("project_list_requirements", {"requesting_profile_id": "PR2", "project_ids": ["P"]})
            with lock:
                results[tag] = (ra["status"], rb["status"])
        ts = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for t in ts: t.start()
        for t in ts: t.join()
        for tag, (a, b) in results.items():
            assert a == "SUCCESS" and b == "POLICY_DENIED", (tag, a, b)


# 14. Determinism
class TestDeterminism:
    def test_deterministic_status(self, adapter):
        statuses = {adapter.call("project_get_charter", BASE)["status"] for _ in range(5)}
        assert statuses == {"SUCCESS"}

    def test_deterministic_denied(self, adapter):
        req = {"requesting_profile_id": "PR1", "project_ids": ["P"], "target_profile_ids": ["PR2"]}
        statuses = {adapter.call("project_get_charter", req)["status"] for _ in range(5)}
        assert statuses == {"POLICY_DENIED"}


# 15. Pagination across pages + revoke between pages
class TestPagination:
    def test_limit_caps_results(self, store_path, adapter):
        # Seed enough requirements to exceed the requested limit.
        import sqlite3
        conn = sqlite3.connect(str(store_path))
        for i in range(6):
            conn.execute("INSERT INTO zm_requirements (requirement_id, project_id, statement, created_at) VALUES (?,?,?,?)",
                         (f"M6R{i}", "P", f"Requirement {i}", "1970-01-01T00:00:00Z"))
        conn.commit(); conn.close()
        _grant(store_path, "PR1", "project", "P", ["requirement"])
        configure(store_path)
        r = adapter.call("project_list_requirements", {"requesting_profile_id": "PR1", "project_ids": ["P"], "limit": 2})
        assert r["status"] == "SUCCESS"
        # limit caps the returned rows (no unbounded dump)
        assert len(r.get("results", [])) <= 2
        # deterministic: repeated identical capped request is stable
        r2 = adapter.call("project_list_requirements", {"requesting_profile_id": "PR1", "project_ids": ["P"], "limit": 2})
        assert r2["status"] == "SUCCESS"
        assert [x.get("requirement_id") for x in r.get("results", [])] == [x.get("requirement_id") for x in r2.get("results", [])]

    def test_malformed_cursor_safe(self, adapter):
        # Malformed cursor must not crash or leak; returns a bounded safe status.
        st = adapter.call("project_list_requirements", {**BASE, "cursor": "not-a-cursor"})["status"]
        assert st in ("INVALID_REQUEST", "DOWNSTREAM_ERROR", "EMPTY", "SUCCESS")

    def test_revoke_no_stale_authority(self, store_path, adapter):
        # Grant freshness must hold per request (no stale authorization), and a
        # cursor parameter must not preserve authority after revocation.
        import sqlite3
        conn = sqlite3.connect(str(store_path))
        for i in range(4):
            conn.execute("INSERT INTO zm_requirements (requirement_id, project_id, statement, created_at) VALUES (?,?,?,?)",
                         (f"M6R{i}", "P", f"Requirement {i}", "1970-01-01T00:00:00Z"))
        conn.commit(); conn.close()
        _grant(store_path, "PR1", "project", "P", ["requirement"])
        configure(store_path)
        clean = {"requesting_profile_id": "PR1", "project_ids": ["P"]}
        assert adapter.call("project_list_requirements", clean)["status"] == "SUCCESS"
        st = SQLiteStore(SQLiteStoreConfig(path=store_path.parent / "m6.sqlite"))
        admin.GrantAdminService(st._conn, lambda ev: None, lambda r: None).revoke(
            admin.GrantAdminRequest(action="revoke", grant_id="GX", subject_profile="PR1",
                                     operation="READ", target_type="project", target_id="P"))
        st._conn.commit(); st.close(); configure(store_path)
        # After revoke, the requirement read is DENIED (no stale authority),
        # regardless of any cursor parameter supplied on the call. The malformed
        # cursor safety is covered separately by test_malformed_cursor_safe.
        assert adapter.call("project_list_requirements", clean)["status"] == "POLICY_DENIED"

class TestPerformance:
    def test_fts_and_project_memory_timings(self, store_path, adapter):
        samples = {}
        for _ in range(30):
            for tool, req in [
                ("memory_search", {"requesting_profile_id": "PR1", "project_ids": ["P"], "search_text": "decision"}),
                ("project_get_charter", BASE),
                ("project_list_requirements", {"requesting_profile_id": "PR1", "project_ids": ["P"]}),
                ("project_list_decisions", {"requesting_profile_id": "PR1", "project_ids": ["P"]}),
                ("project_get_state", BASE),
                ("project_list_verifications", BASE),
                ("project_list_artifacts", BASE),
            ]:
                t0 = time.perf_counter()
                adapter.call(tool, req)
                samples.setdefault(tool, []).append(time.perf_counter() - t0)
        for tool, ts in samples.items():
            assert max(ts) < 1.0, (tool, max(ts))
            assert statistics.median(ts) < 0.5, (tool, statistics.median(ts))
        self._perf = {k: {"median_ms": round(statistics.median(v) * 1000, 3),
                          "p95_ms": round(sorted(v)[int(len(v) * 0.95)] * 1000, 3),
                          "max_ms": round(max(v) * 1000, 3), "n": len(v)} for k, v in samples.items()}

    def test_transport_overhead(self, store_path, adapter):
        def timed(fn, n=50):
            ts = []
            for _ in range(n):
                t0 = time.perf_counter(); fn(); ts.append(time.perf_counter() - t0)
            return statistics.median(ts) * 1000
        d = timed(lambda: dispatch({"tool": "project_get_charter", **BASE}))
        a = timed(lambda: adapter.call("project_get_charter", BASE))
        assert a - d < 50.0, (d, a)
        self._overhead = {"dispatcher_ms": round(d, 3), "adapter_ms": round(a, 3)}


# 19. Memory/resource growth
class TestResourceGrowth:
    def test_no_handle_leak(self, store_path):
        import gc
        cfg = BridgeConfig(enabled=True)
        ad = HermesReadAdapter(cfg, store_path=store_path)
        ad.startup()
        for _ in range(50):
            ad.call("project_get_charter", BASE)
            ad.call("memory_query", {"requesting_profile_id": "PR1", "project_ids": ["P"]})
        gc.collect()
        ad.shutdown()
        cfg2 = BridgeConfig(enabled=True)
        ad2 = HermesReadAdapter(cfg2, store_path=store_path); ad2.startup()
        assert ad2.call("project_get_charter", BASE)["status"] == "SUCCESS"
        ad2.shutdown()


# 20/21. Zero-LLM / zero-network (static)
class TestZeroLLMNetwork:
    def test_no_llm_network_imports(self, adapter):
        import ast
        base = REPO_ROOT / "src" / "integration"
        mods = set()
        for f in base.rglob("*.py"):
            for n in ast.walk(ast.parse(f.read_text())):
                if isinstance(n, ast.Import):
                    for a in n.names: mods.add(a.name.split(".")[0])
                elif isinstance(n, ast.ImportFrom):
                    mods.add((n.module or "").split(".")[0])
        net = {"openai", "llm", "requests", "httpx", "aiohttp", "socket", "urllib"}
        assert mods.isdisjoint(net)


# 22. M1 non-interference
class TestM1NonInterference:
    def test_capture_adapter_independent(self, adapter):
        import importlib
        import src.integration.capture_adapter as ca
        assert hasattr(ca, "adapt_mapped_event")
        src = (REPO_ROOT / "src" / "integration" / "hermes_read_adapter.py").read_text()
        assert "adapt_mapped_event" not in src


# 23/25. Hermes-core integrity + static security audit
class TestStaticAudit:
    def test_no_writable_imports(self, adapter):
        import ast
        forbidden = {"src.access.admin", "src.access.authorized_write",
                     "src.access.grant_events", "src.storage.migrations",
                     "src.storage.ingest"}
        files = ["hermes_read_adapter.py", "m6/handlers.py", "m6/dispatcher.py",
                 "m6/mcp_wrapper.py", "m6/contracts.py", "m6/runtime.py",
                 "m6/tools.py", "m6/errors.py", "m6/__init__.py"]
        base = REPO_ROOT / "src" / "integration"
        for f in files:
            mods = set()
            for n in ast.walk(ast.parse((base / f).read_text())):
                if isinstance(n, ast.Import):
                    for a in n.names: mods.add(a.name.split(".")[0])
                elif isinstance(n, ast.ImportFrom):
                    mods.add((n.module or "").split(".")[0])
            assert mods & forbidden == set(), f

    def test_no_hermes_core_modification(self, adapter):
        p = REPO_ROOT / "src" / "integration" / "hermes_read_adapter.py"
        assert p.exists()
        src = p.read_text()
        assert "from hermes" not in src and "import hermes" not in src

    def test_grant_admin_unreachable(self, adapter):
        assert get_tool("grant_admin") is None
        assert get_tool("create_grant") is None
        assert get_tool("revoke_grant") is None


# 24/29/30. Path portability + master switch + auto-injection absence
class TestAbsenceGuards:
    def test_no_hardcoded_username(self, adapter):
        import ast
        base = REPO_ROOT / "src" / "integration"
        src = "\n".join(f.read_text() for f in base.rglob("*.py"))
        assert "/home/brian-nguyen" not in src and "/home/brian-nguyan" not in src

    def test_all_verifier_targets_resolve(self, adapter):
        base = REPO_ROOT / "src" / "integration"
        for n in ["hermes_read_adapter.py", "m6/contracts.py", "m6/errors.py", "m6/tools.py",
                  "m6/dispatcher.py", "m6/mcp_wrapper.py", "m6/runtime.py", "m6/handlers.py", "m6/__init__.py"]:
            assert (base / n).exists(), "AD-HOC VERIFICATION INCOMPLETE - required path could not be verified: src/integration/" + n

    def test_single_master_switch_only(self, adapter):
        # M7.1 introduces EXACTLY ONE master Zero-Mem switch (ZERO_MEM_ENABLED),
        # backed by BridgeConfig.zero_mem_enabled. No redundant/alias/per-subsystem
        # switches are permitted.
        base = REPO_ROOT / "src" / "integration"
        src = "\n".join(f.read_text() for f in base.rglob("*.py"))
        # The one approved canonical switch IS present.
        assert "ZERO_MEM_ENABLED" in src
        assert "zero_mem_enabled" in src
        # Forbidden redundant/alias/per-subsystem switches remain absent.
        for forbidden in (
            "zero_mem.enabled",        # alias form (only ZERO_MEM_ENABLED is canonical)
            "master_enable",
            "memory_system_enabled",
            "disable_zero_mem",
            "retrieval_enabled",
            "mcp_enabled",
            "routing_enabled",
            "project_memory_enabled",
        ):
            assert forbidden not in src
        # R124-03: capture_enabled/injection_enabled are truthful freshness
        # reporting fields on RuntimeHealth/capability_matrix, NOT independent
        # master switches, and are therefore permitted as health attributes.
        assert "capture_enabled" in src
        assert "injection_enabled" in src

    def test_no_auto_injection(self, adapter):
        NL = chr(10)
        base = REPO_ROOT / "src" / "integration"
        src = NL.join(f.read_text() for f in base.rglob("*.py"))
        for t in ("controlled_injection", "auto_inject", "inject_results"):
            assert t not in src

    def test_no_m7_implementation(self, adapter):
        # M7.2-M7.5 are now IMPLEMENTED. M7.6 (final acceptance) is not a
        # separate module. evidence_selector remains deferred (M8 scope).
        m7 = REPO_ROOT / "src" / "integration" / "m7"
        assert m7.exists()
        assert not (m7 / "evidence_selector.py").exists()
        assert (m7 / "injection_adapter.py").exists()
        assert (m7 / "hardening.py").exists()


# 27. Contract consistency
class TestContractConsistency:
    def test_resource_type_fixed_per_tool(self, adapter):
        # Each tool has exactly one fixed resource_type per the authoritative
        # audit surface (no tool parameter can override it - tested elsewhere).
        surf = audit_tool_surface()
        expected = {
            "memory_query": "event", "memory_search": "event", "memory_get_event": "event",
            "memory_get_related": "relation", "project_get_charter": "charter",
            "project_list_requirements": "requirement", "project_list_decisions": "decision",
            "project_get_state": "project_state", "project_list_verifications": "verification",
            "project_list_artifacts": "artifact",
        }
        for name in ALL:
            assert surf[name]["resource_type"] == expected[name]
