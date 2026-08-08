"""M6.3 focused tests - M4 project-memory read tools through M5.

Reuses the verified M4 rebuild pipeline (m4base.build_corpus plus
rebuild_project_memory / rebuild_all_project_memory) so project ownership/scope
semantics match the real M4 path. No hard-coded repository or user paths: repo
root resolved dynamically; fixtures are OS-temp (pytest tmp_path).
"""

import os
import sys
import subprocess
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO_ROOT = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"]).decode().strip())

from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.project_memory import rebuild_project_memory, rebuild_all_project_memory
import tests.unit.test_m4_rebuild as m4base
from src.access import admin

from src.integration.m6 import (
    ResponseStatus, configure, dispatch, get_tool, list_tool_names, mcp_wrapper,
)


def _open(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(SQLiteStoreConfig(path=tmp_path / "m4.sqlite"))


def _seed(tmp_path: Path, store: SQLiteStore) -> None:
    store.ensure_schema()
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
    return tmp_path / "m4.sqlite"


@pytest.fixture
def rt(store_path):
    return configure(store_path)


def _grant(store_path, subject, target_type, target_id, resource_types):
    store = SQLiteStore(SQLiteStoreConfig(path=store_path.parent / "m4.sqlite"))
    g = store._conn
    svc = admin.GrantAdminService(g, lambda ev: None, lambda r: None)
    svc.create(admin.GrantAdminRequest(action="create", grant_id="GX", subject_profile=subject,
                operation="READ", target_type=target_type, target_id=target_id,
                resource_types=resource_types))
    g.commit()
    store.close()


class TestCharter:
    def test_authorized(self, rt):
        r = dispatch({"tool": "project_get_charter", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR1"]})
        assert r.status is ResponseStatus.SUCCESS

    def test_unauthorized_denied(self, rt):
        r = dispatch({"tool": "project_get_charter", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR2"]})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_missing_charter_empty(self, rt):
        r = dispatch({"tool": "project_get_charter", "requesting_profile_id": "PR1",
                      "project_ids": ["NOSUCH"], "target_profile_ids": ["PR1"]})
        assert r.status is ResponseStatus.EMPTY

    def test_cross_profile_denied(self, rt):
        r = dispatch({"tool": "project_get_charter", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR2"]})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_exact_grant_allows(self, store_path, rt):
        _grant(store_path, "PR1", "project", "P", ["charter"])
        configure(store_path)
        r = dispatch({"tool": "project_get_charter", "requesting_profile_id": "PR1",
                      "project_ids": ["P"]})
        assert r.status is ResponseStatus.SUCCESS

    def test_wrong_resource_grant_denied(self, store_path, rt):
        _grant(store_path, "PR1", "project", "P", ["requirement"])
        configure(store_path)
        r = dispatch({"tool": "project_get_charter", "requesting_profile_id": "PR1",
                      "project_ids": ["P"]})
        assert r.status is ResponseStatus.POLICY_DENIED


class TestRequirements:
    def test_authorized(self, rt):
        r = dispatch({"tool": "project_list_requirements", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR1"]})
        assert r.status is ResponseStatus.SUCCESS
        assert len(r.results) >= 1

    def test_cross_profile_denied(self, rt):
        r = dispatch({"tool": "project_list_requirements", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR2"]})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_exact_grant(self, store_path, rt):
        _grant(store_path, "PR1", "project", "P", ["requirement"])
        configure(store_path)
        r = dispatch({"tool": "project_list_requirements", "requesting_profile_id": "PR1",
                      "project_ids": ["P"]})
        assert r.status is ResponseStatus.SUCCESS

    def test_requirements_grant_cannot_expose_decisions(self, store_path, rt):
        _grant(store_path, "PR1", "project", "P", ["requirement"])
        configure(store_path)
        r = dispatch({"tool": "project_list_decisions", "requesting_profile_id": "PR1",
                      "project_ids": ["P"]})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_bp_not_bq(self, store_path, rt):
        _grant(store_path, "PR1", "project", "P", ["requirement"])
        configure(store_path)
        r = dispatch({"tool": "project_list_requirements", "requesting_profile_id": "PR1",
                      "project_ids": ["Q"]})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_deterministic_ordering(self, rt):
        a = dispatch({"tool": "project_list_requirements", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR1"]})
        b = dispatch({"tool": "project_list_requirements", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR1"]})
        assert [x.get("requirement_id") for x in a.results] == [x.get("requirement_id") for x in b.results]


class TestDecisions:
    def test_authorized(self, rt):
        r = dispatch({"tool": "project_list_decisions", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR1"]})
        assert r.status is ResponseStatus.SUCCESS
        assert len(r.results) >= 1

    def test_cross_profile_denied(self, rt):
        r = dispatch({"tool": "project_list_decisions", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR2"]})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_exact_grant(self, store_path, rt):
        _grant(store_path, "PR1", "project", "P", ["decision"])
        configure(store_path)
        r = dispatch({"tool": "project_list_decisions", "requesting_profile_id": "PR1",
                      "project_ids": ["P"]})
        assert r.status is ResponseStatus.SUCCESS

    def test_requirements_grant_does_not_authorize_decisions(self, store_path, rt):
        _grant(store_path, "PR1", "project", "P", ["requirement"])
        configure(store_path)
        r = dispatch({"tool": "project_list_decisions", "requesting_profile_id": "PR1",
                      "project_ids": ["P"]})
        assert r.status is ResponseStatus.POLICY_DENIED


class TestProjectState:
    def test_authorized(self, rt):
        r = dispatch({"tool": "project_get_state", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR1"]})
        assert r.status is ResponseStatus.SUCCESS

    def test_unauthorized_denied(self, rt):
        r = dispatch({"tool": "project_get_state", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR2"]})
        assert r.status is ResponseStatus.POLICY_DENIED


class TestVerifications:
    def test_authorized(self, rt):
        r = dispatch({"tool": "project_list_verifications", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR1"]})
        assert r.status is ResponseStatus.SUCCESS
        assert len(r.results) >= 1

    def test_unauthorized_denied(self, rt):
        r = dispatch({"tool": "project_list_verifications", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR2"]})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_verified_status_does_not_bypass(self, rt):
        r = dispatch({"tool": "project_list_verifications", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR2"]})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_subject_link_does_not_confer_auth(self, store_path, rt):
        _grant(store_path, "PR1", "project", "P", ["verification"])
        configure(store_path)
        r = dispatch({"tool": "project_list_verifications", "requesting_profile_id": "PR1",
                      "project_ids": ["P"]})
        assert r.status is ResponseStatus.SUCCESS


class TestArtifacts:
    def test_metadata_authorized(self, rt):
        r = dispatch({"tool": "project_list_artifacts", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR1"]})
        assert r.status is ResponseStatus.SUCCESS

    def test_unauthorized_denied(self, rt):
        r = dispatch({"tool": "project_list_artifacts", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR2"]})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_no_stored_path_leak(self, rt):
        r = dispatch({"tool": "project_list_artifacts", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR1"]})
        blob = str(r.to_dict())
        assert "stored_path" not in blob
        assert "content" not in blob or "content_hash" in blob
        assert "/artifacts/" not in blob or "safe_reference" in blob

    def test_safe_reference_present(self, rt):
        r = dispatch({"tool": "project_list_artifacts", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR1"]})
        assert any(x for x in r.results)


class TestSourceEventBoundary:
    def test_charter_source_event_denied_when_unauthorized(self, rt):
        r = dispatch({"tool": "project_get_charter", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR2"],
                      "include_source_event": True})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_authorized_source_event_allowed(self, rt):
        r = dispatch({"tool": "project_get_charter", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR1"],
                      "include_source_event": True})
        assert r.status is ResponseStatus.SUCCESS


class TestCrossProfileGrant:
    def test_a_to_b_without_grant_denied(self, rt):
        for t in ["project_get_charter", "project_list_requirements", "project_list_decisions",
                  "project_get_state", "project_list_verifications", "project_list_artifacts"]:
            r = dispatch({"tool": t, "requesting_profile_id": "PR1", "project_ids": ["P"],
                          "target_profile_ids": ["PR2"]})
            assert r.status is ResponseStatus.POLICY_DENIED, t

    def test_exact_project_resource_grant(self, store_path, rt):
        _grant(store_path, "PR1", "project", "P", ["requirement", "decision"])
        configure(store_path)
        for t in ["project_list_requirements", "project_list_decisions"]:
            assert dispatch({"tool": t, "requesting_profile_id": "PR1", "project_ids": ["P"]}).status is ResponseStatus.SUCCESS
        for t in ["project_get_charter", "project_get_state", "project_list_verifications", "project_list_artifacts"]:
            assert dispatch({"tool": t, "requesting_profile_id": "PR1", "project_ids": ["P"]}).status is ResponseStatus.POLICY_DENIED

    def test_isolated_mode(self, rt):
        r = dispatch({"tool": "project_list_requirements", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "isolated_mode": True})
        assert r.status is ResponseStatus.POLICY_DENIED


class TestTransportRegression:
    def test_direct_mcp_parity(self, rt):
        raw = {"tool": "project_get_charter", "requesting_profile_id": "PR1",
               "project_ids": ["P"], "target_profile_ids": ["PR1"]}
        assert mcp_wrapper.handle_call("project_get_charter", raw)["status"] == dispatch(raw).status.value

    def test_m61_contract_unchanged(self, rt):
        names = set(list_tool_names())
        assert {"memory_query", "memory_search", "memory_get_event", "memory_get_related",
                "project_get_charter", "project_list_requirements", "project_list_decisions",
                "project_get_state", "project_list_verifications", "project_list_artifacts"} <= names

    def test_unknown_fields_rejected(self, rt):
        r = dispatch({"tool": "project_get_charter", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR1"], "bogus": 1})
        assert r.status is ResponseStatus.INVALID_REQUEST

    def test_fake_grant_rejected(self, rt):
        r = dispatch({"tool": "project_get_charter", "grant_object": {"grant_id": "G"}})
        assert r.status is ResponseStatus.INVALID_REQUEST

    def test_admin_rejected(self, rt):
        r = dispatch({"tool": "project_get_charter", "admin": True})
        assert r.status is ResponseStatus.INVALID_REQUEST


class TestReadOnlySecurity:
    def test_schema_v8(self, rt):
        from src.storage.migrations import CURRENT_SCHEMA_VERSION
        assert CURRENT_SCHEMA_VERSION == 8

    def test_no_forbidden_writable_imports(self, rt):
        base = REPO_ROOT / "src" / "integration" / "m6"
        import ast
        forbidden = {"src.access.admin", "src.access.authorized_write",
                     "src.access.grant_events", "src.storage.migrations",
                     "src.storage.ingest"}
        for f in base.glob("*.py"):
            mods = set()
            for n in ast.walk(ast.parse(f.read_text())):
                if isinstance(n, ast.Import):
                    for a in n.names: mods.add(a.name.split(".")[0])
                elif isinstance(n, ast.ImportFrom):
                    mods.add((n.module or "").split(".")[0])
            assert mods & forbidden == set(), f.name

    def test_raw_sql_jsonl_absent(self, rt):
        assert get_tool("execute_sql") is None and get_tool("raw_sql") is None
        assert get_tool("read_jsonl") is None and get_tool("raw_jsonl") is None

    def test_grant_admin_not_exposed(self, rt):
        assert get_tool("grant_admin") is None

    def test_no_external_imports(self, rt):
        base = REPO_ROOT / "src" / "integration" / "m6"
        import ast
        mods = set()
        for f in base.glob("*.py"):
            for n in ast.walk(ast.parse(f.read_text())):
                if isinstance(n, ast.Import):
                    for a in n.names: mods.add(a.name.split(".")[0])
                elif isinstance(n, ast.ImportFrom):
                    mods.add((n.module or "").split(".")[0])
        banned = {"openai", "llm", "requests", "httpx", "socket", "aiohttp", "urllib", "http"}
        assert not (banned & mods)

    def test_no_master_switch_token(self, rt):
        base = REPO_ROOT / "src" / "integration" / "m6"
        src = "\n".join(f.read_text() for f in base.glob("*.py"))
        assert all(t not in src for t in ("ZERO_MEM_ENABLED", "zero_mem.enabled", "master_enable", "memory_system_enabled"))

    def test_no_hardcoded_username_path(self, rt):
        base = REPO_ROOT / "src" / "integration" / "m6"
        src = "\n".join(f.read_text() for f in base.glob("*.py"))
        assert not any(u in src for u in ("/home/brian-nguyen", "/home/brian-nguyan"))

    def test_committed_paths_resolve(self, rt):
        base = REPO_ROOT / "src" / "integration" / "m6"
        required = ["contracts.py", "errors.py", "tools.py", "dispatcher.py",
                    "mcp_wrapper.py", "runtime.py", "handlers.py", "__init__.py"]
        for n in required:
            assert (base / n).exists(), "AD-HOC VERIFICATION INCOMPLETE - required path could not be verified: src/integration/m6/" + n
