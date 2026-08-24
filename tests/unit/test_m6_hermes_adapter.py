"""M6.5 focused tests - Hermes READ-tool adapter / registration + failure isolation.

Reuses the verified M4+M3 corpus builder. Repo root resolved dynamically;
fixtures OS-temp (pytest tmp_path). No hard-coded repository or user paths.
"""

import os
import sys
import subprocess
import tempfile
import threading
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


def _grant(store_path, subject, target_type, target_id, resource_types):
    store = SQLiteStore(SQLiteStoreConfig(path=store_path.parent / "m6.sqlite"))
    svc = admin.GrantAdminService(store._conn, lambda ev: None, lambda r: None)
    svc.create(admin.GrantAdminRequest(action="create", grant_id="GX", subject_profile=subject,
                operation="READ", target_type=target_type, target_id=target_id,
                resource_types=resource_types))
    store._conn.commit()
    store.close()


ALL = list(ALL_READ_TOOLS)
BASE = {"requesting_profile_id": "PR1", "project_ids": ["P"], "target_profile_ids": ["PR1"]}


class TestRegistration:
    def test_all_ten_registered(self, adapter):
        ctx = _Ctx()
        reg = adapter.register(ctx)
        assert set(reg) == set(ALL)
        assert len(reg) == 11

    def test_no_extra_or_missing(self, adapter):
        ctx = _Ctx()
        reg = adapter.register(ctx)
        assert set(reg) == set(list_tool_names())
        for f in ("execute_sql", "raw_sql", "read_jsonl", "write_memory",
                  "project_set_state", "create_grant", "grant_admin"):
            assert f not in reg

    def test_idempotent(self, adapter):
        ctx = _Ctx()
        r1 = adapter.register(ctx)
        r2 = adapter.register(ctx)
        assert r1 == r2

    def test_unknown_tool_rejected(self, adapter):
        r = adapter.call("nonexistent_tool", {"requesting_profile_id": "PR1", "project_ids": ["P"]})
        assert r["status"] == "UNSUPPORTED_TOOL"

    def test_write_admin_tools_absent(self, adapter):
        for f in FORBIDDEN_TOOL_NAMES:
            assert get_tool(f) is None

    def test_disabled_adapter_no_registration(self, store_path):
        cfg = BridgeConfig(enabled=False)
        ad = HermesReadAdapter(cfg, store_path=store_path)
        ctx = _Ctx()
        assert ad.register(ctx) == ()
        assert ad.call("project_get_charter", BASE)["status"] == "CAPABILITY_UNAVAILABLE"


class TestSchemaParity:
    def test_schemas_match_m6_contract(self, adapter):
        schemas = {s["name"]: s for s in adapter.list_tools()}
        for name in ALL:
            assert name in schemas
            assert schemas[name]["inputSchema"]["properties"]["tool"]["const"] == name
            assert schemas[name]["inputSchema"]["properties"]["operation"]["const"] == "READ"

    def test_read_only_schemas(self, adapter):
        schemas = {s["name"]: s for s in adapter.list_tools()}
        for name in ALL:
            assert schemas[name]["inputSchema"]["additionalProperties"] is False

    def test_authority_fields_rejected(self, adapter):
        ctx = _Ctx(); adapter.register(ctx)
        for bad in ["admin", "is_admin", "trusted", "grant_admin", "grant", "authorized_read_grant",
                    "effective_scope", "bypass_policy", "verified", "cross_profile_allowed", "raw_sql", "authorized_read_grant"]:
            r = adapter.call("project_get_charter", {bad: True, "requesting_profile_id": "PR1", "project_ids": ["P"]})
            assert r["status"] == "INVALID_REQUEST", bad

    def test_fake_grant_object_rejected(self, adapter):
        r = adapter.call("project_get_charter", {"grant_object": {"grant_id": "G", "valid": True}})
        assert r["status"] == "INVALID_REQUEST"

    def test_top_level_fake_grant_rejected(self, adapter):
        # M6 contract hardening rejects forbidden authority fields at the TOP level
        # (by design; nested scanning is out of scope). authorized_read_grant is one.
        r = adapter.call("project_get_charter", {"requesting_profile_id": "PR1", "project_ids": ["P"],
                                                 "authorized_read_grant": {"grant_id": "G"}})
        assert r["status"] == "INVALID_REQUEST"

    def test_write_operation_rejected(self, adapter):
        r = adapter.call("project_get_charter", {"operation": "WRITE", "requesting_profile_id": "PR1", "project_ids": ["P"]})
        assert r["status"] == "UNSUPPORTED_OPERATION"


class TestIdentity:
    def test_explicit_identity_preserved(self, adapter):
        assert adapter.call("project_get_charter", BASE)["status"] == "SUCCESS"

    def test_null_identity_preserved(self, adapter):
        r = adapter.call("project_get_charter", {"project_ids": ["P"]})
        assert r["status"] in (ResponseStatus.POLICY_DENIED.value, ResponseStatus.INVALID_REQUEST.value)

    def test_identity_not_retained(self, adapter):
        r1 = adapter.call("project_get_charter", BASE)
        assert r1["status"] == "SUCCESS"
        r2 = adapter.call("project_get_charter", {"project_ids": ["P"]})
        assert r2["status"] in (ResponseStatus.POLICY_DENIED.value, ResponseStatus.INVALID_REQUEST.value)

    def test_concurrent_identity_separation(self, adapter):
        out = {}
        def call(profile, key):
            out[key] = adapter.call("project_get_charter",
                                    {"requesting_profile_id": profile, "project_ids": ["P"],
                                     "target_profile_ids": [profile]})
        ts = [threading.Thread(target=call, args=(p, p)) for p in ["PR1", "PR2", "PR3"]]
        for t in ts: t.start()
        for t in ts: t.join()
        assert out["PR1"]["status"] == "SUCCESS"
        assert out["PR2"]["status"] == "POLICY_DENIED"
        assert out["PR3"]["status"] == "POLICY_DENIED"


class TestAuthorization:
    def test_same_profile_allowed(self, adapter):
        assert adapter.call("project_get_charter", BASE)["status"] == "SUCCESS"

    def test_cross_profile_denied(self, adapter):
        payloads = {
            "memory_query": {},
            "memory_search": {"search_text": "anything"},
            "memory_get_event": {"filters": {"event_id": "e1"}},
            "memory_get_related": {"filters": {"event_id": "e1"}, "relation": "incoming"},
            "corpus_search": {"search_text": "anything"},
        }
        for tool in ALL:
            r = adapter.call(tool, {"requesting_profile_id": "PR1", "project_ids": ["P"],
                                    "target_profile_ids": ["PR2"], **payloads.get(tool, {})})
            assert r["status"] == "POLICY_DENIED", (tool, r["status"])

    def test_exact_grant_allowed(self, store_path, adapter):
        # Grant is the SOLE authorization source: omit target_profile_ids so the
        # request is NOT a same-profile base read (which would mask the grant).
        req = {"requesting_profile_id": "PR1", "project_ids": ["P"]}
        _grant(store_path, "PR1", "project", "P", ["requirement", "decision"])
        configure(store_path)
        for tool in ["project_list_requirements", "project_list_decisions"]:
            assert adapter.call(tool, req)["status"] == "SUCCESS"
        for tool in ["project_get_charter", "project_get_state", "project_list_verifications", "project_list_artifacts"]:
            assert adapter.call(tool, req)["status"] == "POLICY_DENIED"

    def test_revoked_grant_denies_next(self, store_path, adapter):
        # Grant is the SOLE auth source -> omit target_profile_ids.
        req = {"requesting_profile_id": "PR1", "project_ids": ["P"]}
        _grant(store_path, "PR1", "project", "P", ["requirement"])
        configure(store_path)
        assert adapter.call("project_list_requirements", req)["status"] == "SUCCESS"
        st = SQLiteStore(SQLiteStoreConfig(path=store_path.parent / "m6.sqlite"))
        admin.GrantAdminService(st._conn, lambda ev: None, lambda r: None).revoke(
            admin.GrantAdminRequest(action="revoke", grant_id="GX", subject_profile="PR1",
                                     operation="READ", target_type="project", target_id="P"))
        st._conn.commit(); st.close(); configure(store_path)
        assert adapter.call("project_list_requirements", req)["status"] == "POLICY_DENIED"

    def test_resource_type_isolation(self, store_path, adapter):
        # Grant is the SOLE auth source -> omit target_profile_ids.
        req = {"requesting_profile_id": "PR1", "project_ids": ["P"]}
        _grant(store_path, "PR1", "project", "P", ["requirement"])
        configure(store_path)
        assert adapter.call("project_list_requirements", req)["status"] == "SUCCESS"
        # Caller cannot override the tool-fixed resource type (top-level field).
        assert adapter.call("project_list_requirements", {**req, "resource_type": "decision"})["status"] == "INVALID_REQUEST"
        for tool in ["project_list_decisions", "project_get_charter", "project_get_state",
                     "project_list_verifications", "project_list_artifacts"]:
            assert adapter.call(tool, req)["status"] == "POLICY_DENIED", tool

    def test_linked_target_independent(self, adapter):
        # Cross-profile project read must remain denied even when a linked
        # resource (source_event) is requested; the target auth is independent.
        r = adapter.call("project_get_charter", {"requesting_profile_id": "PR1", "project_ids": ["P"],
                                                 "target_profile_ids": ["PR2"], "include_source_event": True})
        assert r["status"] == "POLICY_DENIED"


class TestDirectAdapterParity:
    @pytest.mark.parametrize("tool", ALL)
    def test_parity(self, adapter, tool):
        raw = dict(BASE)
        direct = dispatch({"tool": tool, **raw}).status.value
        adapter_r = adapter.call(tool, raw)["status"]
        assert direct == adapter_r

    @pytest.mark.parametrize("tool", ALL)
    def test_deny_parity(self, adapter, tool):
        fields = {
            "memory_search": {"search_text": "x"},
            "memory_get_event": {"filters": {"event_id": "e1"}},
            "memory_get_related": {"filters": {"event_id": "e1"}, "relation": "incoming"},
            "corpus_search": {"search_text": "x"},
        }.get(tool, {})
        raw = {"requesting_profile_id": "PR1", "project_ids": ["P"], "target_profile_ids": ["PR2"], **fields}
        assert dispatch({"tool": tool, **raw}).status.value == adapter.call(tool, raw)["status"] == "POLICY_DENIED"


class TestFailureIsolation:
    def test_missing_db_startup_safe(self, store_path):
        cfg = BridgeConfig(enabled=True)
        ad = HermesReadAdapter(cfg, store_path=Path(tempfile.mkdtemp()).resolve() / "missing.sqlite")
        with pytest.raises(RegistrationFailure):
            ad.startup()
        ctx = _Ctx()
        assert ad.register(ctx) == ()
        assert ad.call("project_get_charter", BASE)["status"] == "CAPABILITY_UNAVAILABLE"

    def test_unreadable_db_startup_safe(self, tmp_path):
        bad = tmp_path / "bad.sqlite"
        bad.write_text("not a sqlite file at all")
        cfg = BridgeConfig(enabled=True)
        ad = HermesReadAdapter(cfg, store_path=bad)
        with pytest.raises(RegistrationFailure):
            ad.startup()
        assert ad.call("project_get_charter", BASE)["status"] == "CAPABILITY_UNAVAILABLE"

    def test_internal_exception_bounded(self, store_path):
        cfg = BridgeConfig(enabled=True)
        ad = HermesReadAdapter(cfg, store_path=store_path)
        ad.startup()
        ctx = _Ctx(); ad.register(ctx)
        r = ad.call("project_get_charter", None)
        assert r["status"] in ("INVALID_REQUEST", "DOWNSTREAM_ERROR")
        assert "traceback" not in str(r).lower()


class TestLifecycle:
    def test_startup_no_mutation(self, store_path):
        import hashlib
        before = hashlib.sha256(Path(store_path).read_bytes()).hexdigest()
        cfg = BridgeConfig(enabled=True)
        ad = HermesReadAdapter(cfg, store_path=store_path)
        ad.startup()
        after = hashlib.sha256(Path(store_path).read_bytes()).hexdigest()
        assert before == after

    def test_shutdown_no_mutation(self, store_path):
        import hashlib
        cfg = BridgeConfig(enabled=True)
        ad = HermesReadAdapter(cfg, store_path=store_path)
        ad.startup()
        before = hashlib.sha256(Path(store_path).read_bytes()).hexdigest()
        ad.shutdown()
        after = hashlib.sha256(Path(store_path).read_bytes()).hexdigest()
        assert before == after

    def test_restart_safe(self, store_path):
        cfg = BridgeConfig(enabled=True)
        ad = HermesReadAdapter(cfg, store_path=store_path)
        ad.startup(); ad.register(_Ctx())
        ad.restart()
        ctx = _Ctx()
        assert set(ad.register(ctx)) == set(ALL)

    def test_no_orphan_state(self, store_path):
        cfg = BridgeConfig(enabled=True)
        ad = HermesReadAdapter(cfg, store_path=store_path)
        ad.startup(); ad.register(_Ctx())
        ad.shutdown()
        assert ad.call("project_get_charter", BASE)["status"] == "CAPABILITY_UNAVAILABLE"


class TestSecuritySurface:
    def test_no_writable_imports(self, adapter):
        import ast
        base = REPO_ROOT / "src" / "integration"
        forbidden = {"src.access.admin", "src.access.authorized_write",
                     "src.access.grant_events", "src.storage.migrations",
                     "src.storage.ingest"}
        for f in (base / "hermes_read_adapter.py", base / "m6" / "handlers.py", base / "m6" / "dispatcher.py",
                  base / "m6" / "mcp_wrapper.py", base / "m6" / "contracts.py", base / "m6" / "runtime.py",
                  base / "m6" / "tools.py", base / "m6" / "errors.py", base / "m6" / "__init__.py"):
            mods = set()
            for n in ast.walk(ast.parse(f.read_text())):
                if isinstance(n, ast.Import):
                    for a in n.names: mods.add(a.name.split(".")[0])
                elif isinstance(n, ast.ImportFrom):
                    mods.add((n.module or "").split(".")[0])
            assert mods & forbidden == set(), f.name

    def test_schema_v8(self, adapter):
        from src.storage.migrations import CURRENT_SCHEMA_VERSION
        assert CURRENT_SCHEMA_VERSION == 12

    def test_raw_sql_jsonl_absent(self, adapter):
        assert get_tool("execute_sql") is None and get_tool("raw_sql") is None
        assert get_tool("read_jsonl") is None and get_tool("raw_jsonl") is None

    def test_grant_admin_absent(self, adapter):
        assert get_tool("grant_admin") is None

    def test_no_llm_network(self, adapter):
        import ast
        base = REPO_ROOT / "src" / "integration"
        mods = set()
        for f in base.glob("**/*.py"):
            for n in ast.walk(ast.parse(f.read_text())):
                if isinstance(n, ast.Import):
                    for a in n.names: mods.add(a.name.split(".")[0])
                elif isinstance(n, ast.ImportFrom):
                    mods.add((n.module or "").split(".")[0])
        assert not ({"openai", "llm", "requests", "httpx", "socket", "aiohttp", "urllib", "http"} & mods)

    def test_single_master_switch_only(self, adapter):
        # M7.1 introduces EXACTLY ONE master switch (ZERO_MEM_ENABLED /
        # BridgeConfig.zero_mem_enabled). No redundant/alias/per-subsystem switches.
        import ast
        base = REPO_ROOT / "src" / "integration"
        src = "\n".join(f.read_text() for f in base.rglob("*.py"))
        assert "ZERO_MEM_ENABLED" in src
        assert "zero_mem_enabled" in src
        assert all(t not in src for t in ("zero_mem.enabled", "master_enable", "master_enabled",
                                          "memory_system_enabled", "disable_zero_mem"))

    def test_no_hardcoded_username(self, adapter):
        import ast
        base = REPO_ROOT / "src" / "integration"
        src = "\n".join(f.read_text() for f in base.rglob("*.py"))
        assert not any(u in src for u in ("/home/brian-nguyen", "/home/brian-nguyan"))

    def test_committed_paths_resolve(self, adapter):
        base = REPO_ROOT / "src" / "integration"
        for n in ["hermes_read_adapter.py", "m6/contracts.py", "m6/errors.py", "m6/tools.py",
                  "m6/dispatcher.py", "m6/mcp_wrapper.py", "m6/runtime.py", "m6/handlers.py", "m6/__init__.py"]:
            assert (base / n).exists(), "AD-HOC VERIFICATION INCOMPLETE - required path could not be verified: src/integration/" + n

    def test_artifact_metadata_only(self, adapter):
        r = adapter.call("project_list_artifacts", BASE)
        assert r["status"] == "SUCCESS"
        blob = str(r).lower()
        assert "stored_path" not in blob and "sk-m4" not in blob
        for item in r.get("results", []):
            assert "stored_path" not in item and "content" not in item

    def test_m1_capture_unchanged(self, adapter):
        import importlib
        import src.integration.capture_adapter as ca
        assert hasattr(ca, "adapt_mapped_event")
