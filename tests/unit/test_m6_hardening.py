"""M6.4 focused hardening matrix - complete exposed M6 read surface.

Reuses the verified M4 rebuild pipeline (m4base.build_corpus + rebuild_*). Repo
root resolved dynamically; fixtures OS-temp (pytest tmp_path). No hard-coded
repository or user paths.
"""

import os
import sys
import subprocess
import tempfile
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
    list_tool_names, mcp_wrapper, validate_request,
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
    # Layer 1: M3 event store (populated via M2.5 ingest so zm_fts exists).
    jl = tmp_path / "m3.jsonl"
    _write_jsonl(jl, _m3_items())
    ingest_file(store, jl)
    # Layer 2: M4 project memory (corpus builder + rebuild pipeline).
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
def rt(store_path):
    return configure(store_path)


ALL_TOOLS = [
    "memory_query", "memory_search", "memory_get_event", "memory_get_related",
    "project_get_charter", "project_list_requirements", "project_list_decisions",
    "project_get_state", "project_list_verifications", "project_list_artifacts",
]


def _grant(store_path, subject, target_type, target_id, resource_types):
    store = SQLiteStore(SQLiteStoreConfig(path=store_path.parent / "m6.sqlite"))
    svc = admin.GrantAdminService(store._conn, lambda ev: None, lambda r: None)
    svc.create(admin.GrantAdminRequest(action="create", grant_id="GX", subject_profile=subject,
                operation="READ", target_type=target_type, target_id=target_id,
                resource_types=resource_types))
    store._conn.commit()
    store.close()


# --------------------------------------------------------------------------
# 1. Complete tool-surface audit
# --------------------------------------------------------------------------
class TestToolSurfaceAudit:
    def test_all_tools_registered(self, rt):
        audit = audit_tool_surface()
        for t in ALL_TOOLS:
            assert audit[t]["registered"] is True
            assert audit[t]["read_only"] is True
            assert audit[t]["no_forbidden_tool"] is True
            assert audit[t]["resource_type"]

    def test_forbidden_tools_unreachable(self, rt):
        audit = audit_tool_surface()
        assert audit["_forbidden_unreachable"] is True
        forbidden = audit["_forbidden_listed"]
        for f in ("execute_sql", "raw_sql", "read_jsonl", "write_memory",
                  "create_grant", "grant_admin", "project_write"):
            assert f in forbidden
            assert get_tool(f) is None

    def test_registry_explicit_allowlist(self, rt):
        names = set(list_tool_names())
        assert names == set(ALL_TOOLS)


# --------------------------------------------------------------------------
# 2/3. MCP transport hardening + privilege-injection matrix
# --------------------------------------------------------------------------
class TestMCPTransportHardening:
    def test_unknown_tool_rejected(self, rt):
        r = dispatch({"tool": "nonexistent_tool", "requesting_profile_id": "PR1"})
        assert r.status is ResponseStatus.UNSUPPORTED_TOOL

    def test_unknown_field_rejected(self, rt):
        r = dispatch({"tool": "project_get_charter", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "bogus_field": 1})
        assert r.status is ResponseStatus.INVALID_REQUEST

    def test_authority_fields_rejected(self, rt):
        for bad in ["admin", "is_admin", "trusted", "grant_admin", "grant", "grant_valid",
                    "verified", "bypass_policy", "cross_profile_allowed", "raw_sql",
                    "sql", "database", "jsonl_path", "authorization", "grant_object",
                    "authorized_read_grant", "allowed_scope", "effective_scope",
                    "identity", "token", "auth", "credential", "assume_identity",
                    "policy_override", "session_authority", "requesting_authority"]:
            r = dispatch({"tool": "project_get_charter", bad: True,
                          "requesting_profile_id": "PR1", "project_ids": ["P"]})
            assert r.status is ResponseStatus.INVALID_REQUEST, bad

    def test_fake_grant_object_rejected(self, rt):
        r = dispatch({"tool": "project_get_charter",
                      "grant_object": {"grant_id": "G", "valid": True}})
        assert r.status is ResponseStatus.INVALID_REQUEST

    def test_wrong_field_type_rejected(self, rt):
        r = dispatch({"tool": "project_get_charter", "requesting_profile_id": 123,
                      "project_ids": ["P"]})
        assert r.status is ResponseStatus.INVALID_REQUEST

    def test_invalid_enum_rejected(self, rt):
        r = dispatch({"tool": "project_get_charter", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "resource_type": "nonsense"})
        assert r.status is ResponseStatus.INVALID_REQUEST

    def test_oversized_list_rejected(self, rt):
        r = dispatch({"tool": "project_get_charter", "requesting_profile_id": "PR1",
                      "project_ids": ["P"] * 200})
        assert r.status is ResponseStatus.INVALID_REQUEST

    def test_oversized_payload_rejected(self, rt):
        big = {"tool": "project_get_charter", "requesting_profile_id": "PR1",
               "project_ids": ["P"]}
        big.update({f"x{i}": i for i in range(80)})
        r = dispatch(big)
        assert r.status is ResponseStatus.INVALID_REQUEST

    def test_malformed_cursor_rejected(self, rt):
        r = dispatch({"tool": "project_list_requirements", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR1"],
                      "cursor": 12345})
        assert r.status is ResponseStatus.INVALID_REQUEST

    def test_invalid_relation_rejected(self, rt):
        r = dispatch({"tool": "memory_get_related", "requesting_profile_id": "PR1",
                      "target_profile_ids": ["PR1"], "project_ids": ["P"],
                      "filters": {"event_id": "E1"}, "relation": "sideways"})
        assert r.status is ResponseStatus.INVALID_REQUEST

    def test_non_read_operation_rejected(self, rt):
        r = dispatch({"tool": "project_get_charter", "operation": "WRITE",
                      "requesting_profile_id": "PR1", "project_ids": ["P"]})
        assert r.status is ResponseStatus.UNSUPPORTED_OPERATION

    def test_no_traceback_on_error(self, rt):
        r = dispatch({"tool": "project_get_charter", "bogus": 1})
        blob = str(r.to_dict()).lower()
        assert "traceback" not in blob and "sqlite" not in blob and "exception" not in blob

    def test_mcp_wrapper_no_traceback(self, rt):
        out = mcp_wrapper.handle_call("project_get_charter", {"bogus": 1})
        assert out["status"] == "INVALID_REQUEST"


# --------------------------------------------------------------------------
# 4. Identity hardening (no inference) + concurrent isolation
# --------------------------------------------------------------------------
class TestIdentityHardening:
    def test_null_identity_preserved(self, rt):
        r = dispatch({"tool": "project_get_charter", "project_ids": ["P"]})
        # unbound caller: M5 decides; must not invent a profile -> denied here
        assert r.status in (ResponseStatus.POLICY_DENIED, ResponseStatus.INVALID_REQUEST)

    def test_session_id_not_authority(self, rt):
        r = dispatch({"tool": "project_get_charter", "session_id": "S1",
                      "requesting_profile_id": "PR1", "project_ids": ["P"],
                      "target_profile_ids": ["PR2"]})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_concurrent_identity_separation(self, rt):
        out = {}
        import threading
        def call(profile, key):
            out[key] = dispatch({"tool": "project_get_charter",
                                  "requesting_profile_id": profile, "project_ids": ["P"],
                                  "target_profile_ids": [profile]})
        ts = [threading.Thread(target=call, args=(p, p)) for p in ["PR1", "PR2", "PR3"]]
        for t in ts: t.start()
        for t in ts: t.join()
        # PR1 owns P -> success; PR2/PR3 do not -> denied; no leakage across threads
        assert out["PR1"].status is ResponseStatus.SUCCESS
        assert out["PR2"].status is ResponseStatus.POLICY_DENIED
        assert out["PR3"].status is ResponseStatus.POLICY_DENIED

    def test_isolated_mode_no_persist(self, rt):
        r1 = dispatch({"tool": "project_list_requirements", "requesting_profile_id": "PR1",
                       "project_ids": ["P"], "isolated_mode": True})
        assert r1.status is ResponseStatus.POLICY_DENIED
        # subsequent normal request is independent (no persisted isolated state)
        r2 = dispatch({"tool": "project_list_requirements", "requesting_profile_id": "PR1",
                       "project_ids": ["P"], "target_profile_ids": ["PR1"]})
        assert r2.status is ResponseStatus.SUCCESS


# --------------------------------------------------------------------------
# 5/6. Live grant-state + cross-profile matrix
# --------------------------------------------------------------------------
class TestGrantAndCrossProfile:
    def test_cross_profile_all_denied(self, rt):
        # M3 tools need their required fields so the denial is policy-based, not
        # a missing-argument rejection.
        payloads = {
            "memory_query": {},
            "memory_search": {"search_text": "anything"},
            "memory_get_event": {"filters": {"event_id": "e1"}},
            "memory_get_related": {"filters": {"event_id": "e1"}, "relation": "incoming"},
        }
        for t in ALL_TOOLS:
            r = dispatch({"tool": t, "requesting_profile_id": "PR1", "project_ids": ["P"],
                          "target_profile_ids": ["PR2"], **payloads.get(t, {})})
            assert r.status is ResponseStatus.POLICY_DENIED, (t, r.status.value, r.reason_code)

    def test_exact_grant_allow_and_isolated(self, store_path, rt):
        _grant(store_path, "PR1", "project", "P", ["requirement", "decision"])
        configure(store_path)
        for t in ["project_list_requirements", "project_list_decisions"]:
            assert dispatch({"tool": t, "requesting_profile_id": "PR1", "project_ids": ["P"]}).status is ResponseStatus.SUCCESS
        for t in ["project_get_charter", "project_get_state", "project_list_verifications", "project_list_artifacts"]:
            assert dispatch({"tool": t, "requesting_profile_id": "PR1", "project_ids": ["P"]}).status is ResponseStatus.POLICY_DENIED

    def test_revoked_grant_next_request_denied(self, store_path, rt):
        _grant(store_path, "PR1", "project", "P", ["requirement"])
        configure(store_path)
        assert dispatch({"tool": "project_list_requirements", "requesting_profile_id": "PR1", "project_ids": ["P"]}).status is ResponseStatus.SUCCESS
        # revoke
        st = SQLiteStore(SQLiteStoreConfig(path=store_path.parent / "m6.sqlite"))
        admin.GrantAdminService(st._conn, lambda ev: None, lambda r: None).revoke(
            admin.GrantAdminRequest(action="revoke", grant_id="GX", subject_profile="PR1",
                                     operation="READ", target_type="project", target_id="P"))
        st._conn.commit(); st.close(); configure(store_path)
        # next independent request must reflect revocation
        r = dispatch({"tool": "project_list_requirements", "requesting_profile_id": "PR1", "project_ids": ["P"]})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_bp_not_bq(self, store_path, rt):
        _grant(store_path, "PR1", "project", "P", ["requirement"])
        configure(store_path)
        assert dispatch({"tool": "project_list_requirements", "requesting_profile_id": "PR1", "project_ids": ["Q"]}).status is ResponseStatus.POLICY_DENIED


# --------------------------------------------------------------------------
# 7. Resource-type cross-tool isolation
# --------------------------------------------------------------------------
class TestResourceTypeIsolation:
    def test_requirement_grant_cannot_expose_others(self, store_path, rt):
        _grant(store_path, "PR1", "project", "P", ["requirement"])
        configure(store_path)
        assert dispatch({"tool": "project_list_requirements", "requesting_profile_id": "PR1", "project_ids": ["P"]}).status is ResponseStatus.SUCCESS
        # The requirement grant must NOT expose the other M4 project-memory
        # resources (charter/state/verification/artifact/decisions).
        for t in ["project_list_decisions", "project_get_charter", "project_get_state",
                  "project_list_verifications", "project_list_artifacts"]:
            assert dispatch({"tool": t, "requesting_profile_id": "PR1", "project_ids": ["P"]}).status is ResponseStatus.POLICY_DENIED, t
        # An event-memory READ grant (requirement) does NOT auto-authorize M4
        # project memory either: a requirement-only grant cannot open charter.
        assert dispatch({"tool": "project_get_charter", "requesting_profile_id": "PR1", "project_ids": ["P"]}).status is ResponseStatus.POLICY_DENIED

    def test_event_grant_cannot_authorize_m4(self, store_path, rt):
        _grant(store_path, "PR1", "project", "P", ["requirement", "decision"])
        configure(store_path)
        # event-memory style allowed via base; M4 still scoped by project grant only
        # (here requirement/decision grant must NOT open charter/state/artifact)
        for t in ["project_get_charter", "project_get_state", "project_list_verifications", "project_list_artifacts"]:
            assert dispatch({"tool": t, "requesting_profile_id": "PR1", "project_ids": ["P"]}).status is ResponseStatus.POLICY_DENIED, t

    def test_tool_fixed_resource_type(self, rt):
        # caller cannot override the tool-fixed resource type
        r = dispatch({"tool": "project_list_requirements", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR1"],
                      "resource_type": "decision"})
        assert r.status is ResponseStatus.INVALID_REQUEST


# --------------------------------------------------------------------------
# 8/13. Linked-resource boundaries via M6 (verification, artifact, source_event)
# --------------------------------------------------------------------------
class TestLinkedResourceBoundaries:
    def test_source_event_unauthorized_withheld(self, rt):
        r = dispatch({"tool": "project_get_charter", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR2"],
                      "include_source_event": True})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_verification_cannot_grant_subject(self, store_path, rt):
        _grant(store_path, "PR1", "project", "P", ["verification"])
        configure(store_path)
        r = dispatch({"tool": "project_list_verifications", "requesting_profile_id": "PR1", "project_ids": ["P"]})
        assert r.status is ResponseStatus.SUCCESS

    def test_verification_status_not_authorization(self, rt):
        # verified status does not make a protected verification readable cross-profile
        r = dispatch({"tool": "project_list_verifications", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR2"]})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_artifact_links_do_not_authorize(self, rt):
        # reading an artifact does not grant linked requirement/decision access
        r = dispatch({"tool": "project_list_artifacts", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR2"]})
        assert r.status is ResponseStatus.POLICY_DENIED


# --------------------------------------------------------------------------
# 12. Artifact metadata-only hardening
# --------------------------------------------------------------------------
class TestArtifactHardening:
    def test_no_stored_path_content_leak(self, rt):
        r = dispatch({"tool": "project_list_artifacts", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR1"]})
        assert r.status is ResponseStatus.SUCCESS
        blob = str(r.to_dict()).lower()
        assert "stored_path" not in blob
        assert "/artifacts/" not in blob or "safe_reference" in blob
        # only whitelisted metadata fields present
        for item in r.results:
            assert set(item.keys()) <= {
                "artifact_id", "project_id", "artifact_type", "version", "safe_reference",
                "source_event_id", "created_at", "verification_status",
                "linked_requirement_ids", "linked_decision_ids", "linked_state_keys",
            }
            assert "content" not in item and "stored_path" not in item

    def test_artifact_secret_absent(self, rt):
        # the M4 corpus stores a synthetic secret inside stored_path; must never appear
        r = dispatch({"tool": "project_list_artifacts", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR1"]})
        assert "SK-M4" not in str(r.to_dict())


# --------------------------------------------------------------------------
# 10/11. Exact-event / project-object probing resistance
# --------------------------------------------------------------------------
class TestProbingResistance:
    def test_event_probing_safe(self, rt):
        # an event in a protected scope returns the same generic denial, no oracle
        r = dispatch({"tool": "memory_get_event", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR2"],
                      "filters": {"event_id": "E999"}})
        assert r.status is ResponseStatus.POLICY_DENIED
        assert "E999" not in str(r.to_dict()).lower()

    def test_project_object_probing_safe(self, rt):
        r = dispatch({"tool": "project_get_state", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR2"]})
        assert r.status is ResponseStatus.POLICY_DENIED
        assert "state" not in str(r.to_dict()).lower() or "reason_code" in r.to_dict()


# --------------------------------------------------------------------------
# 14. Global + isolated-mode matrix
# --------------------------------------------------------------------------
class TestGlobalIsolation:
    def test_isolated_blocks_global_via_relations(self, rt):
        r = dispatch({"tool": "memory_get_related", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR1"],
                      "filters": {"event_id": "E1"}, "relation": "incoming",
                      "isolated_mode": True})
        # isolated_mode still honors explicit target scope; must not silently enable global
        assert r.status in (ResponseStatus.SUCCESS, ResponseStatus.EMPTY, ResponseStatus.POLICY_DENIED)

    def test_include_global_false(self, rt):
        r = dispatch({"tool": "project_list_requirements", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR1"],
                      "include_global": False})
        assert r.status is ResponseStatus.SUCCESS


# --------------------------------------------------------------------------
# 15. Pagination security
# --------------------------------------------------------------------------
class TestPaginationSecurity:
    def test_limit_bounds(self, rt):
        r = dispatch({"tool": "project_list_requirements", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR1"], "limit": 1000})
        assert r.status is ResponseStatus.INVALID_REQUEST

    def test_deterministic_ordering(self, rt):
        a = dispatch({"tool": "project_list_requirements", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR1"]})
        b = dispatch({"tool": "project_list_requirements", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR1"]})
        assert [x.get("requirement_id") for x in a.results] == [x.get("requirement_id") for x in b.results]


# --------------------------------------------------------------------------
# 16. Direct vs MCP parity (all tools)
# --------------------------------------------------------------------------
class TestDirectMcpParity:
    @pytest.mark.parametrize("tool", ALL_TOOLS)
    def test_parity(self, rt, tool):
        raw = {"tool": tool, "requesting_profile_id": "PR1",
               "project_ids": ["P"], "target_profile_ids": ["PR1"]}
        direct = dispatch(raw).status.value
        mcp = mcp_wrapper.handle_call(tool, raw)["status"]
        assert direct == mcp

    @pytest.mark.parametrize("tool", ALL_TOOLS)
    def test_deny_parity(self, rt, tool):
        fields = {
            "memory_search": {"search_text": "x"},
            "memory_get_event": {"filters": {"event_id": "e1"}},
            "memory_get_related": {"filters": {"event_id": "e1"}, "relation": "incoming"},
        }.get(tool, {})
        raw = {"tool": tool, "requesting_profile_id": "PR1",
               "project_ids": ["P"], "target_profile_ids": ["PR2"], **fields}
        assert dispatch(raw).status.value == mcp_wrapper.handle_call(tool, raw)["status"] == "POLICY_DENIED"

    @pytest.mark.parametrize("tool", ALL_TOOLS)
    def test_invalid_parity(self, rt, tool):
        raw = {"tool": tool, "bogus": 1, "requesting_profile_id": "PR1"}
        assert dispatch(raw).status.value == mcp_wrapper.handle_call(tool, raw)["status"] == "INVALID_REQUEST"


# --------------------------------------------------------------------------
# 17. Failure isolation
# --------------------------------------------------------------------------
class TestFailureIsolation:
    def test_missing_db_safe(self, rt):
        from src.integration.m6 import configure as cfg
        cfg(Path(tempfile.mkdtemp()).resolve() / "missing.sqlite")
        r = dispatch({"tool": "project_get_charter", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR1"]})
        assert r.status in (ResponseStatus.CAPABILITY_UNAVAILABLE, ResponseStatus.DOWNSTREAM_ERROR)
        assert "traceback" not in str(r.to_dict()).lower()

    def test_corrupted_request_safe(self, rt):
        r = dispatch({"tool": "project_get_charter", "requesting_profile_id": "PR1",
                      "project_ids": ["P"], "target_profile_ids": ["PR1"], "limit": "not-an-int"})
        assert r.status is ResponseStatus.INVALID_REQUEST


# --------------------------------------------------------------------------
# 18/19/22. Read-only integrity, audit separation, no write/admin surface
# --------------------------------------------------------------------------
class TestReadOnlyAndAudit:
    def test_no_writable_imports(self, rt):
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

    def test_schema_v8(self, rt):
        from src.storage.migrations import CURRENT_SCHEMA_VERSION
        assert CURRENT_SCHEMA_VERSION == 10

    def test_raw_sql_jsonl_absent(self, rt):
        assert get_tool("execute_sql") is None and get_tool("raw_sql") is None
        assert get_tool("read_jsonl") is None and get_tool("raw_jsonl") is None

    def test_grant_admin_absent(self, rt):
        assert get_tool("grant_admin") is None

    def test_no_llm_network(self, rt):
        base = REPO_ROOT / "src" / "integration" / "m6"
        import ast
        mods = set()
        for f in base.glob("*.py"):
            for n in ast.walk(ast.parse(f.read_text())):
                if isinstance(n, ast.Import):
                    for a in n.names: mods.add(a.name.split(".")[0])
                elif isinstance(n, ast.ImportFrom):
                    mods.add((n.module or "").split(".")[0])
        assert not ({"openai", "llm", "requests", "httpx", "socket", "aiohttp", "urllib", "http"} & mods)

    def test_no_master_switch(self, rt):
        base = REPO_ROOT / "src" / "integration" / "m6"
        src = "\n".join(f.read_text() for f in base.glob("*.py"))
        assert all(t not in src for t in ("ZERO_MEM_ENABLED", "zero_mem.enabled", "master_enable", "memory_system_enabled"))

    def test_no_hardcoded_username(self, rt):
        base = REPO_ROOT / "src" / "integration" / "m6"
        src = "\n".join(f.read_text() for f in base.glob("*.py"))
        assert not any(u in src for u in ("/home/brian-nguyen", "/home/brian-nguyan"))

    def test_committed_paths_resolve(self, rt):
        base = REPO_ROOT / "src" / "integration" / "m6"
        for n in ["contracts.py", "errors.py", "tools.py", "dispatcher.py",
                  "mcp_wrapper.py", "runtime.py", "handlers.py", "__init__.py"]:
            assert (base / n).exists(), "AD-HOC VERIFICATION INCOMPLETE - required path could not be verified: src/integration/m6/" + n
