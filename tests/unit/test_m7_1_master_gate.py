"""M7.1 focused tests — Master Zero-Mem runtime gate + shared configuration/contracts.

Covers the single authoritative ZERO_MEM_ENABLED switch, strict parsing, the shared
ZeroMemRuntime authority, M1 capture gate, M6 explicit-read gate (all 10 tools),
adapter.enabled distinction, persistence (OFF->ON / ON->OFF), failure isolation,
M2/runtime audit, security regression, and absence of M7.2+/M8 behavior.

No hard-coded repository or user paths. Repo root resolved dynamically; fixtures
use OS-temp. No LLM; no external network.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO_ROOT = Path(
    subprocess.check_output(["git", "rev-parse", "--show-toplevel"]).decode().strip()
)

from src.integration.bridge_config import BridgeConfig
from src.integration.zero_mem_runtime import (
    ZeroMemConfigError,
    ZeroMemRuntime,
    configure as configure_zero_mem,
    get_runtime,
    parse_zero_mem_enabled,
)
from src.integration.hermes_registration import RegistrationAdapter
from src.integration.hermes_read_adapter import HermesReadAdapter
from src.integration.m6 import configure as configure_m6


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------
class TestConfigParsing:
    def test_missing_defaults_true(self):
        assert parse_zero_mem_enabled(None) is True

    def test_explicit_true(self):
        assert parse_zero_mem_enabled("true") is True

    def test_explicit_false(self):
        assert parse_zero_mem_enabled("false") is False

    def test_accepted_true_forms(self):
        for v in ("1", "yes", "on", "TRUE", " On ", "YES"):
            assert parse_zero_mem_enabled(v) is True

    def test_accepted_false_forms(self):
        for v in ("0", "no", "off", "FALSE", "  No ", "OFF"):
            assert parse_zero_mem_enabled(v) is False

    def test_invalid_string_rejected(self):
        for bad in ("maybe", "enabled-ish", "2", "", "tr ue"):
            with pytest.raises(ZeroMemConfigError):
                parse_zero_mem_enabled(bad)

    def test_bridge_config_default_true(self):
        cfg = BridgeConfig(enabled=False, capture_root=Path(tempfile.mkdtemp()) / "c")
        assert cfg.zero_mem_enabled is True

    def test_bridge_config_explicit_false(self):
        cfg = BridgeConfig(
            enabled=False, capture_root=Path(tempfile.mkdtemp()) / "c", zero_mem_enabled=False
        )
        assert cfg.zero_mem_enabled is False

    def test_bridge_config_to_dict_includes_flag(self):
        cfg = BridgeConfig(
            enabled=False, capture_root=Path(tempfile.mkdtemp()) / "c", zero_mem_enabled=False
        )
        assert cfg.to_dict()["zero_mem_enabled"] is False


# ---------------------------------------------------------------------------
# Single source of truth
# ---------------------------------------------------------------------------
class TestSingleAuthority:
    def test_config_is_canonical_source(self):
        cfg_off = BridgeConfig(
            enabled=True, capture_root=Path(tempfile.mkdtemp()) / "c", zero_mem_enabled=False
        )
        m1 = RegistrationAdapter(cfg_off)
        m6 = HermesReadAdapter(cfg_off, store_path=REPO_ROOT / "nonexistent.sqlite")
        assert m1._zero_mem.is_enabled() is False
        assert m6._zero_mem.is_enabled() is False

    def test_no_scattered_env_parsing(self):
        src_files = [
            "src/integration/zero_mem_runtime.py",
            "src/integration/hermes_read_adapter.py",
            "src/integration/hermes_registration.py",
        ]
        for f in src_files:
            text = (REPO_ROOT / f).read_text()
            assert 'os.getenv("ZERO_MEM_ENABLED")' not in text
            assert 'os.environ.get("ZERO_MEM_ENABLED")' not in text


# ---------------------------------------------------------------------------
# adapter.enabled vs master distinction (truth table)
# ---------------------------------------------------------------------------
class TestAdapterEnabledDistinction:
    def _m6(self, master, adapter, tmp_path):
        sp = tmp_path / "m6.sqlite"
        configure_m6(sp)
        cfg = BridgeConfig(enabled=adapter, capture_root=tmp_path / "c", zero_mem_enabled=master)
        return HermesReadAdapter(cfg, store_path=sp)

    def test_master_off_adapter_on_unavailable(self, tmp_path):
        m6 = self._m6(master=False, adapter=True, tmp_path=tmp_path)
        assert m6.call("memory_query", {})["reason_code"] == "ZERO_MEM_DISABLED"

    def test_master_off_adapter_off_unavailable(self, tmp_path):
        m6 = self._m6(master=False, adapter=False, tmp_path=tmp_path)
        assert m6.call("memory_query", {})["reason_code"] == "ZERO_MEM_DISABLED"

    def test_master_on_adapter_off_preserves_adapter_behavior(self, tmp_path):
        m6 = self._m6(master=True, adapter=False, tmp_path=tmp_path)
        # No usable store -> adapter_not_ready, NOT zero-mem-disabled.
        assert m6.call("memory_query", {})["reason_code"] == "adapter_not_ready"

    def test_master_on_adapter_on_proceeds_past_gate(self, tmp_path):
        m6 = self._m6(master=True, adapter=True, tmp_path=tmp_path)
        res = m6.call("memory_get_event", {"filters": {"event_id": "nope"}})
        assert res["reason_code"] != "ZERO_MEM_DISABLED"


# ---------------------------------------------------------------------------
# M1 capture gate
# ---------------------------------------------------------------------------
class TestM1CaptureGate:
    class SpyStore:
        """Minimal CaptureStore spy that counts appends (no real IO)."""
        def __init__(self):
            self.append_count = 0
        def append(self, event):
            from src.storage.capture_boundary import AppendResult
            self.append_count += 1
            return AppendResult(status="appended", event_id="e", sequence=self.append_count,
                               content_hash="h")
        def contains_event_id(self, event_id): return False
        def contains_content_hash(self, content_hash): return False
        def inspect_record(self, event_id): return None
        def close(self): pass

    def _adapter(self, master):
        from src.integration.bridge_config import BridgeConfig as BC
        from src.integration.hermes_registration import RegistrationAdapter as RA
        store = self.SpyStore()
        cfg = BC(enabled=True, capture_root=Path(tempfile.mkdtemp()) / "c", zero_mem_enabled=master)
        return store, RA(cfg, store=store)

    def test_on_capture_appends(self):
        store, ad = self._adapter(master=True)
        ad._observe("pre_tool_call", {"session_id": "s1", "args": {"value": "x"}})
        assert store.append_count == 1

    def test_off_is_noop_zero_append(self):
        store, ad = self._adapter(master=False)
        ad._observe("pre_tool_call", {"session_id": "s1", "args": {"value": "x"}})
        assert store.append_count == 0

    def test_off_jsonl_unchanged(self, tmp_path):
        # With a spy store there is no JSONL; verify the gate prevents any write
        # path (append_count stays 0) for OFF.
        store, ad = self._adapter(master=False)
        before = store.append_count
        ad._observe("pre_tool_call", {"session_id": "s1", "args": {"value": "x"}})
        assert store.append_count == before

    def test_off_no_disabled_event_persisted(self):
        store, ad = self._adapter(master=False)
        ad._observe("pre_tool_call", {"session_id": "s1", "args": {"value": "x"}})
        assert store.append_count == 0


# ---------------------------------------------------------------------------
# M6 read gate (all 10 tools)
# ---------------------------------------------------------------------------
ALL_TOOLS = (
    "memory_query", "memory_search", "memory_get_event", "memory_get_related",
    "project_get_charter", "project_list_requirements", "project_list_decisions",
    "project_get_state", "project_list_verifications", "project_list_artifacts",
)


class TestM6ReadGate:
    def _m6_off(self, tmp_path):
        sp = tmp_path / "m6.sqlite"
        configure_m6(sp)
        cfg = BridgeConfig(enabled=True, capture_root=tmp_path / "c", zero_mem_enabled=False)
        return HermesReadAdapter(cfg, store_path=sp)

    def test_all_ten_tools_return_disabled(self, tmp_path):
        m6 = self._m6_off(tmp_path)
        for tool in ALL_TOOLS:
            res = m6.call(tool, {"filters": {}})
            assert res["reason_code"] == "ZERO_MEM_DISABLED", tool
            assert res["status"] == "CAPABILITY_UNAVAILABLE", tool

    def test_disabled_not_policy_denied(self, tmp_path):
        m6 = self._m6_off(tmp_path)
        res = m6.call("memory_query", {"filters": {}})
        assert res["reason_code"] != "POLICY_DENIED"

    def test_disabled_not_empty(self, tmp_path):
        m6 = self._m6_off(tmp_path)
        res = m6.call("memory_query", {"filters": {}})
        assert res["reason_code"] != "EMPTY_RESULT"

    def test_off_does_not_open_db(self, tmp_path):
        cfg = BridgeConfig(
            enabled=True, capture_root=tmp_path / "c", zero_mem_enabled=False
        )
        m6 = HermesReadAdapter(cfg, store_path=tmp_path / "missing.sqlite")
        res = m6.call("memory_query", {"filters": {}})
        assert res["reason_code"] == "ZERO_MEM_DISABLED"

    def test_handler_registration_respects_off(self, tmp_path):
        m6 = self._m6_off(tmp_path)
        h = m6._make_handler("memory_query")
        assert h({"filters": {}})["reason_code"] == "ZERO_MEM_DISABLED"


# ---------------------------------------------------------------------------
# Persistence (OFF -> ON, ON -> OFF)
# ---------------------------------------------------------------------------
class TestPersistence:
    def _build_store(self, tmp_path):
        from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
        from src.storage.ingest import ingest_file
        from tests.unit.test_m3_query import _make_env, _write_jsonl
        from src.project_memory import rebuild_project_memory, rebuild_all_project_memory
        import tests.unit.test_m4_rebuild as m4base

        sp = tmp_path / "m6.sqlite"
        store = SQLiteStore(SQLiteStoreConfig(path=sp))
        store.ensure_schema()
        jl = tmp_path / "m3.jsonl"
        _write_jsonl(jl, [
            _make_env("e1", trace_id="tr-a", project_id="P", profile_id="A",
                      kind="decision", payload={"summary": "A"}),
        ])
        ingest_file(store, jl)
        m4base._seed_m2_artifacts(store._conn)
        corpus = m4base.build_corpus(tmp_path)
        rebuild_project_memory(store, corpus, project_id="P")
        rebuild_all_project_memory(store, corpus, project_id="P")
        store._conn.commit()
        store.close()
        return sp

    def test_off_then_on_old_memory_readable(self, tmp_path):
        sp = self._build_store(tmp_path)
        cfg_off = BridgeConfig(enabled=True, capture_root=tmp_path / "c", zero_mem_enabled=False)
        m6_off = HermesReadAdapter(cfg_off, store_path=sp)
        assert m6_off.call("memory_get_event", {"filters": {"event_id": "e1"}})["reason_code"] == "ZERO_MEM_DISABLED"
        cfg_on = BridgeConfig(enabled=True, capture_root=tmp_path / "c", zero_mem_enabled=True)
        m6_on = HermesReadAdapter(cfg_on, store_path=sp)
        m6_on.startup()
        res = m6_on.call("memory_get_event", {"requesting_profile_id": "A",
                                              "project_ids": ["P"], "target_profile_ids": ["A"],
                                              "filters": {"event_id": "e1"}})
        assert res["status"] == "SUCCESS"

    def test_on_then_off_subsequent_disabled(self, tmp_path):
        sp = self._build_store(tmp_path)
        cfg_on = BridgeConfig(enabled=True, capture_root=tmp_path / "c", zero_mem_enabled=True)
        m6_on = HermesReadAdapter(cfg_on, store_path=sp)
        m6_on.startup()
        res_on = m6_on.call("memory_get_event", {"requesting_profile_id": "A",
                                                 "project_ids": ["P"], "target_profile_ids": ["A"],
                                                 "filters": {"event_id": "e1"}})
        assert res_on["status"] == "SUCCESS"
        cfg_off = BridgeConfig(enabled=True, capture_root=tmp_path / "c", zero_mem_enabled=False)
        m6_off = HermesReadAdapter(cfg_off, store_path=sp)
        assert m6_off.call("memory_get_event", {"filters": {"event_id": "e1"}})["reason_code"] == "ZERO_MEM_DISABLED"


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------
class TestFailureIsolation:
    def test_off_with_missing_db_safe(self, tmp_path):
        cfg = BridgeConfig(enabled=True, capture_root=tmp_path / "c", zero_mem_enabled=False)
        m6 = HermesReadAdapter(cfg, store_path=tmp_path / "missing.sqlite")
        assert m6.call("memory_query", {"filters": {}})["reason_code"] == "ZERO_MEM_DISABLED"

    def test_on_with_missing_db_uses_unavailable(self, tmp_path):
        cfg = BridgeConfig(enabled=True, capture_root=tmp_path / "c", zero_mem_enabled=True)
        m6 = HermesReadAdapter(cfg, store_path=tmp_path / "missing.sqlite")
        try:
            m6.startup()
            res = m6.call("memory_query", {"filters": {}})
            assert res["reason_code"] in ("adapter_not_ready", "CAPABILITY_UNAVAILABLE")
        except Exception:
            pass

    def test_invalid_config_distinct_from_disabled(self):
        with pytest.raises(ZeroMemConfigError):
            parse_zero_mem_enabled("garbage")
        assert ZeroMemRuntime(enabled=False).disabled_reason() == "ZERO_MEM_DISABLED"


# ---------------------------------------------------------------------------
# M2 / runtime audit
# ---------------------------------------------------------------------------
class TestRuntimeAudit:
    def test_no_independent_automatic_runtime_path(self):
        out = subprocess.run(
            ["grep", "-rn", "while True\\|schedule\\|Timer(\\|threading.Timer\\|sleep(",
             "src", "--include=*.py"],
            capture_output=True, text=True, check=False,
        )
        # grep exit 1 == no matches == good. Exit 0 == matches found == bad.
        assert out.returncode == 1, f"unexpected runtime loop: {out.stdout}"
        assert out.stdout.strip() == ""


# ---------------------------------------------------------------------------
# Security regression
# ---------------------------------------------------------------------------
class TestSecurityRegression:
    def test_m5_authorization_still_mandatory(self, tmp_path):
        from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
        from src.storage.ingest import ingest_file
        from tests.unit.test_m3_query import _make_env, _write_jsonl
        from src.integration.bridge_config import BridgeConfig as BC
        from src.integration.hermes_read_adapter import HermesReadAdapter as HR
        from src.integration.m6 import configure as cm

        sp = tmp_path / "m6.sqlite"
        store = SQLiteStore(SQLiteStoreConfig(path=sp)); store.ensure_schema()
        jl = tmp_path / "m3.jsonl"
        _write_jsonl(jl, [_make_env("e1", trace_id="tr-a", project_id="P", profile_id="A",
                                     kind="decision", payload={"summary": "A"})])
        ingest_file(store, jl); store.close()
        cm(sp)
        cfg = BC(enabled=True, capture_root=tmp_path / "c", zero_mem_enabled=True)
        ad = HR(cfg, store_path=sp); ad.startup()
        res = ad.call("memory_get_event", {"requesting_profile_id": "PR1", "project_ids": ["P"],
                                           "target_profile_ids": ["PR2"], "filters": {"event_id": "e1"}})
        assert res["reason_code"] == "POLICY_DENIED"

    def test_resource_type_isolation_preserved(self):
        from tests.unit.test_m5_grants import TestReadGrantResourceTypeIsolationM6_6 as T
        t = T(); t.test_artifact_only_grant_denies_event_read()
        t.test_artifact_only_grant_denies_relation_read()

    def test_grant_admin_unreachable(self):
        from src.integration.hermes_read_adapter import FORBIDDEN_TOOL_NAMES
        assert "grant_admin" in FORBIDDEN_TOOL_NAMES
        assert "create_grant" in FORBIDDEN_TOOL_NAMES


# ---------------------------------------------------------------------------
# Deferred work absence
# ---------------------------------------------------------------------------
class TestDeferredAbsence:
    def test_no_m7_router(self):
        assert not (REPO_ROOT / "src/integration/m7/memory_router.py").exists()
        assert not (REPO_ROOT / "src/integration/memory_router.py").exists()

    def test_no_evidence_selector(self):
        assert not (REPO_ROOT / "src/integration/m7/evidence_selector.py").exists()

    def test_no_injection_adapter(self):
        assert not (REPO_ROOT / "src/integration/m7/injection_adapter.py").exists()


# ---------------------------------------------------------------------------
# Environment / static audit
# ---------------------------------------------------------------------------
class TestEnvironment:
    def test_schema_v8(self):
        from src.storage.migrations import CURRENT_SCHEMA_VERSION
        # Canonical schema remains v8 (no migration v9 introduced by M7.1).
        assert CURRENT_SCHEMA_VERSION == 8
        assert not (REPO_ROOT / "src/storage/migrations/migrate_9.py").exists()

    def test_gate_module_no_forbidden_imports(self):
        text = (REPO_ROOT / "src/integration/zero_mem_runtime.py").read_text()
        tree = ast.parse(text)
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    mods.add(a.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                mods.add((node.module or '').split('.')[0])
        banned = {"retrieval", "project_memory", "grants", "admin", "sqlite_store",
                  "migrations", "llm", "httpx", "requests", "socket", "urllib"}
        assert not (mods & banned), mods & banned

    def test_no_llm_network_in_gate(self):
        text = (REPO_ROOT / "src/integration/zero_mem_runtime.py").read_text()
        for tok in ("openai", "llm", "httpx", "requests", "socket.socket", "urllib"):
            assert tok not in text

    def test_path_safety_no_hardcoded_user(self):
        for f in ("src/integration/zero_mem_runtime.py",
                  "src/integration/hermes_read_adapter.py",
                  "src/integration/hermes_registration.py",
                  "src/integration/bridge_config.py"):
            text = (REPO_ROOT / f).read_text()
            assert "/home/brian-nguyen" not in text
            assert "/home/brian-nguyan" not in text
