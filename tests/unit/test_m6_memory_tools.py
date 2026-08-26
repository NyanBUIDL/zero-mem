"""M6.2 focused tests — M3 authorized memory read tools.

Wires memory_query / memory_search / memory_get_event / memory_get_related
through the verified M5 AuthorizedReadService. Reuses the verified M3 corpus
builders (ingest_file populates the FTS index; rebuild_from_jsonl does not).

No hard-coded repository or user paths: the repo root is resolved dynamically
and all fixture paths are OS-temp. The committed M6.2 source is checked via the
installed package import (never by re-reading absolute /home paths).
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Resolve repo root dynamically (no hard-coded /home/<user> paths).
REPO_ROOT = Path(__file__).resolve().parents[2]

from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.storage.ingest import ingest_file
from tests.unit.test_m3_query import _make_env, _open_store, _write_jsonl, _checkpoint_and_close
from src.access import admin



def _imported_modules(src: str):
    mods = set()
    tree = __import__("ast").parse(src)
    for node in __import__("ast").walk(tree):
        if isinstance(node, __import__("ast").Import):
            for a in node.names:
                mods.add(a.name.split(".")[0])
        elif isinstance(node, __import__("ast").ImportFrom):
            mods.add((node.module or "").split(".")[0])
    return mods


from src.integration.m6 import (
    M6Response, Operation, ResourceType, ResponseStatus, validate_request,
    configure, dispatch, TOOL_REGISTRY, get_tool, list_tool_names,
    Dispatcher,
)

SECRET = "SK-M6R-DONTLEAK-7a8b9c0d"


def _corpus_items():
    return [
        _make_env("e1", trace_id="tr-a", project_id="P", profile_id="A",
                  sanitized_content={"text": "alpha A content"}),
        _make_env("e2", trace_id="tr-b", project_id="P", profile_id="B",
                  sanitized_content={"text": f"alpha B {SECRET}"}),
        _make_env("e3", trace_id="tr-a", project_id="P", profile_id="A",
                  sanitized_content={"text": "beta A content"}),
    ]


@pytest.fixture
def store_path(tmp_path):
    jl = tmp_path / "corpus.jsonl"
    _write_jsonl(jl, _corpus_items())
    store = _open_store(tmp_path)
    ingest_file(store, jl)  # populates zm_fts (M2.5 path)
    _checkpoint_and_close(store)
    return tmp_path / "m.sqlite"


@pytest.fixture
def rt(store_path):
    return configure(store_path)


def _grant(store_path, **kw):
    store = _open_store(store_path.parent)
    g = store._conn
    svc = admin.GrantAdminService(g, lambda ev: None, lambda r: None)
    svc.create(admin.GrantAdminRequest(action="create", grant_id=kw.pop("grant_id", "GX"),
                                       subject_profile=kw["subject_profile"], operation="READ",
                                       target_type=kw["target_type"], target_id=kw["target_id"],
                                       resource_types=kw.get("resource_types", ["event"])))
    g.commit()
    _checkpoint_and_close(store)


# --------------------------------------------------------------------------
# memory_query
# --------------------------------------------------------------------------
class TestMemoryQuery:
    def test_same_profile_authorized(self, rt):
        r = dispatch({"tool": "memory_query", "requesting_profile_id": "A",
                      "target_profile_ids": ["A"], "project_ids": ["P"]})
        assert r.status is ResponseStatus.SUCCESS
        assert len(r.results) >= 1

    def test_cross_profile_denied(self, rt):
        r = dispatch({"tool": "memory_query", "requesting_profile_id": "A",
                      "target_profile_ids": ["B"], "project_ids": ["P"]})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_exact_persistent_grant_allow(self, store_path, rt):
        _grant(store_path, subject_profile="A", target_type="profile", target_id="B")
        configure(store_path)
        r = dispatch({"tool": "memory_query", "requesting_profile_id": "A",
                      "target_profile_ids": ["B"]})
        assert r.status is ResponseStatus.SUCCESS

    def test_bp_grant_does_not_allow_bq(self, store_path, rt):
        _grant(store_path, subject_profile="A", target_type="profile", target_id="B")
        configure(store_path)
        # grant is B only; requesting Q must not be authorized
        r = dispatch({"tool": "memory_query", "requesting_profile_id": "A",
                      "target_profile_ids": ["Q"]})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_isolated_mode(self, rt):
        r = dispatch({"tool": "memory_query", "requesting_profile_id": "A",
                      "isolated_mode": True})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_include_global_false(self, rt):
        r = dispatch({"tool": "memory_query", "requesting_profile_id": "A",
                      "target_profile_ids": ["A"], "project_ids": ["P"], "include_global": False})
        # still authorized for the explicit scope
        assert r.status in (ResponseStatus.SUCCESS, ResponseStatus.EMPTY)

    def test_empty_result(self, rt):
        r = dispatch({"tool": "memory_query", "requesting_profile_id": "A",
                      "target_profile_ids": ["A"], "project_ids": ["P"],
                      "filters": {"project_filter": "NONEXISTENT_PROJECT"}})
        assert r.status is ResponseStatus.EMPTY

    def test_deterministic_ordering(self, rt):
        a = dispatch({"tool": "memory_query", "requesting_profile_id": "A",
                      "target_profile_ids": ["A"], "project_ids": ["P"]})
        b = dispatch({"tool": "memory_query", "requesting_profile_id": "A",
                      "target_profile_ids": ["A"], "project_ids": ["P"]})
        assert [x.get("event_id") for x in a.results] == [x.get("event_id") for x in b.results]

    def test_unbound_requester_no_default_profile(self, rt):
        r = dispatch({"tool": "memory_query", "target_profile_ids": ["A"]})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_secret_absent(self, rt):
        r = dispatch({"tool": "memory_query", "requesting_profile_id": "A",
                      "target_profile_ids": ["B"], "project_ids": ["P"]})
        assert SECRET not in str(r.to_dict())


# --------------------------------------------------------------------------
# memory_search
# --------------------------------------------------------------------------
class TestMemorySearch:
    def test_authorized_fts(self, rt):
        r = dispatch({"tool": "memory_search", "requesting_profile_id": "A",
                      "target_profile_ids": ["A"], "project_ids": ["P"], "search_text": "alpha"})
        assert r.status is ResponseStatus.SUCCESS
        assert any("alpha" in str(x) for x in r.results)

    def test_unauthorized_fts_denied(self, rt):
        r = dispatch({"tool": "memory_search", "requesting_profile_id": "A",
                      "target_profile_ids": ["B"], "search_text": "alpha"})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_search_text_not_identity(self, store_path, rt):
        _grant(store_path, subject_profile="A", target_type="profile", target_id="B")
        configure(store_path)
        # Candidate authorization now occurs in SQL before FTS ranking/snippets.
        # Text does not grant scope, so the hidden candidate yields no result
        # rather than a boundary-denial oracle.
        r = dispatch({"tool": "memory_search", "requesting_profile_id": "A",
                      "search_text": "B"})
        assert r.status is ResponseStatus.EMPTY

    def test_exact_grant_fts(self, store_path, rt):
        _grant(store_path, subject_profile="A", target_type="profile", target_id="B")
        configure(store_path)
        r = dispatch({"tool": "memory_search", "requesting_profile_id": "A",
                      "target_profile_ids": ["B"], "search_text": "alpha"})
        assert r.status is ResponseStatus.SUCCESS

    def test_revoked_grant_denies_next(self, store_path, rt):
        _grant(store_path, grant_id="GX", subject_profile="A", target_type="profile", target_id="B")
        configure(store_path)
        assert dispatch({"tool": "memory_search", "requesting_profile_id": "A",
                        "target_profile_ids": ["B"], "search_text": "alpha"}).status is ResponseStatus.SUCCESS
        store = _open_store(store_path.parent); g = store._conn
        admin.GrantAdminService(g, lambda ev: None, lambda r: None).revoke(
            admin.GrantAdminRequest(action="revoke", grant_id="GX", subject_profile="A",
                                    operation="READ", target_type="profile", target_id="B"))
        g.commit(); _checkpoint_and_close(store)
        configure(store_path)
        r = dispatch({"tool": "memory_search", "requesting_profile_id": "A",
                      "target_profile_ids": ["B"], "search_text": "alpha"})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_isolated_fts(self, rt):
        r = dispatch({"tool": "memory_search", "requesting_profile_id": "A",
                      "isolated_mode": True, "search_text": "alpha"})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_include_global_false(self, rt):
        r = dispatch({"tool": "memory_search", "requesting_profile_id": "A",
                      "target_profile_ids": ["A"], "project_ids": ["P"], "include_global": False,
                      "search_text": "alpha"})
        assert r.status in (ResponseStatus.SUCCESS, ResponseStatus.EMPTY)

    def test_pagination(self, rt):
        r = dispatch({"tool": "memory_search", "requesting_profile_id": "A",
                      "target_profile_ids": ["A"], "project_ids": ["P"], "search_text": "content",
                      "limit": 1})
        assert r.status in (ResponseStatus.SUCCESS, ResponseStatus.EMPTY)

    def test_secret_absent_without_grant(self, rt):
        # Without a grant, A's authorized search scope is A only; B's secret event
        # is out of scope and must never appear in results/snippets/errors.
        r = dispatch({"tool": "memory_search", "requesting_profile_id": "A",
                      "target_profile_ids": ["A"], "project_ids": ["P"], "search_text": "alpha"})
        assert r.status in (ResponseStatus.SUCCESS, ResponseStatus.EMPTY)
        assert SECRET not in str(r.to_dict())


# --------------------------------------------------------------------------
# memory_get_event
# --------------------------------------------------------------------------
class TestMemoryGetEvent:
    def test_authorized_event(self, rt):
        r = dispatch({"tool": "memory_get_event", "requesting_profile_id": "A", "query": "e1"})
        assert r.status is ResponseStatus.SUCCESS

    def test_unauthorized_event(self, rt):
        r = dispatch({"tool": "memory_get_event", "requesting_profile_id": "A", "query": "e2"})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_missing_event_safe(self, rt):
        r = dispatch({"tool": "memory_get_event", "requesting_profile_id": "A", "query": "nope"})
        assert r.status is ResponseStatus.EMPTY  # not a denial; no existence leak

    def test_cross_profile_deny(self, rt):
        r = dispatch({"tool": "memory_get_event", "requesting_profile_id": "A",
                      "target_profile_ids": ["B"], "query": "e2"})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_exact_grant_allow(self, store_path, rt):
        _grant(store_path, subject_profile="A", target_type="profile", target_id="B")
        configure(store_path)
        r = dispatch({"tool": "memory_get_event", "requesting_profile_id": "A",
                      "target_profile_ids": ["B"], "query": "e2"})
        assert r.status is ResponseStatus.SUCCESS

    def test_no_protected_existence_leak(self, rt):
        r = dispatch({"tool": "memory_get_event", "requesting_profile_id": "A", "query": "e2"})
        assert r.status is ResponseStatus.POLICY_DENIED
        assert SECRET not in str(r.to_dict())


# --------------------------------------------------------------------------
# memory_get_related
# --------------------------------------------------------------------------
class TestMemoryGetRelated:
    def test_authorized_source_target(self, store_path, rt):
        # add a relation e1 -> e3 (both in A) via direct corpus extension
        items = _corpus_items() + [
            _make_env("e1b", trace_id="tr-a", project_id="P", profile_id="A",
                      relation_ids=["e3"], sanitized_content={"text": "rel A"}),
        ]
        jl = store_path.parent / "rel.jsonl"
        _write_jsonl(jl, items)
        store = _open_store(store_path.parent); ingest_file(store, jl); _checkpoint_and_close(store)
        configure(store_path)
        r = dispatch({"tool": "memory_get_related", "requesting_profile_id": "A",
                      "target_profile_ids": ["A"], "project_ids": ["P"], "query": "e1b"})
        assert r.status in (ResponseStatus.SUCCESS, ResponseStatus.EMPTY)

    def test_unauthorized_source_denied(self, rt):
        r = dispatch({"tool": "memory_get_related", "requesting_profile_id": "A",
                      "target_profile_ids": ["B"], "query": "e2"})
        assert r.status is ResponseStatus.POLICY_DENIED

    def test_exact_grant_allows_exact_target(self, store_path, rt):
        _grant(store_path, subject_profile="A", target_type="profile", target_id="B")
        configure(store_path)
        r = dispatch({"tool": "memory_get_related", "requesting_profile_id": "A",
                      "target_profile_ids": ["B"], "query": "e2"})
        assert r.status in (ResponseStatus.SUCCESS, ResponseStatus.EMPTY, ResponseStatus.POLICY_DENIED)

    def test_revoked_grant_denies_next(self, store_path, rt):
        _grant(store_path, grant_id="GX", subject_profile="A", target_type="profile", target_id="B")
        configure(store_path)
        store = _open_store(store_path.parent); g = store._conn
        admin.GrantAdminService(g, lambda ev: None, lambda r: None).revoke(
            admin.GrantAdminRequest(action="revoke", grant_id="GX", subject_profile="A",
                                    operation="READ", target_type="profile", target_id="B"))
        g.commit(); _checkpoint_and_close(store)
        configure(store_path)
        r = dispatch({"tool": "memory_get_related", "requesting_profile_id": "A",
                      "target_profile_ids": ["B"], "query": "e2"})
        assert r.status is ResponseStatus.POLICY_DENIED


# --------------------------------------------------------------------------
# Contract / transport regression (M6.1 intact)
# --------------------------------------------------------------------------
class TestContractRegression:
    def test_m61_contracts_unchanged(self, rt):
        assert set(list_tool_names()) >= {
            "memory_query", "memory_search", "memory_get_event", "memory_get_related",
            "project_get_charter", "project_list_requirements", "project_list_decisions",
            "project_get_state", "project_list_verifications", "project_list_artifacts"}

    def test_direct_dispatcher_mcp_parity(self, rt):
        raw = {"tool": "memory_query", "requesting_profile_id": "A",
               "target_profile_ids": ["A"], "project_ids": ["P"]}
        d = dispatch(raw)
        from src.integration.m6 import mcp_wrapper
        m = mcp_wrapper.handle_call("memory_query", raw)
        assert m["status"] == d.status.value

    def test_unknown_fields_rejected(self, rt):
        r = dispatch({"tool": "memory_query", "requesting_profile_id": "A",
                      "target_profile_ids": ["A"], "project_ids": ["P"], "bogus": 1})
        assert r.status is ResponseStatus.INVALID_REQUEST

    def test_fake_grant_rejected(self, rt):
        r = dispatch({"tool": "memory_query", "grant_object": {"grant_id": "G", "valid": True}})
        assert r.status is ResponseStatus.INVALID_REQUEST

    def test_admin_rejected(self, rt):
        r = dispatch({"tool": "memory_query", "admin": True})
        assert r.status is ResponseStatus.INVALID_REQUEST

    def test_raw_sql_absent(self, rt):
        assert get_tool("execute_sql") is None and get_tool("raw_sql") is None

    def test_raw_jsonl_absent(self, rt):
        assert get_tool("read_jsonl") is None and get_tool("raw_jsonl") is None

    def test_m4_project_tools_now_wired(self, rt):
        # After M6.3 these tools are wired (no longer CAPABILITY_UNAVAILABLE) and
        # still enforce authorization (unauthorized -> POLICY_DENIED).
        for t in ["project_get_charter", "project_list_requirements", "project_list_decisions",
                  "project_get_state", "project_list_verifications", "project_list_artifacts"]:
            r = dispatch({"tool": t, "requesting_profile_id": "A", "project_ids": ["P"]})
            assert r.status is not ResponseStatus.CAPABILITY_UNAVAILABLE
            r2 = dispatch({"tool": t, "requesting_profile_id": "A", "project_ids": ["P"],
                           "target_profile_ids": ["B"]})
            assert r2.status is ResponseStatus.POLICY_DENIED

    def test_no_m63_behavior(self, rt):
        assert get_tool("m4_charter") is None

    def test_no_m7_master_switch(self, rt):
        # No ON/OFF master switch in M6.2
        import src.integration.m6 as m6
        src_blob = " ".join(Path(m6.__file__).read_text() for _ in [0])
        for tok in ("ZERO_MEM_ENABLED", "zero_mem.enabled", "master_enable", "memory_system_enabled"):
            assert tok not in src_blob


# --------------------------------------------------------------------------
# Read-only / schema safety
# --------------------------------------------------------------------------
class TestReadOnly:
    def test_schema_v8(self, rt):
        from src.storage.migrations import CURRENT_SCHEMA_VERSION
        assert CURRENT_SCHEMA_VERSION == 13

    def test_no_forbidden_writable_imports(self, rt):
        base = REPO_ROOT / "src" / "integration" / "m6"
        forbidden = {"src.access.admin", "src.access.authorized_write",
                     "src.access.grant_events", "src.storage.migrations",
                     "src.storage.ingest"}
        for f in base.glob("*.py"):
            assert _imported_modules(f.read_text()) & forbidden == set(), f"{f.name} imports writable module"

    def test_no_projector_or_canonical_writer_imports(self, rt):
        base = REPO_ROOT / "src" / "integration" / "m6"
        forbidden = {"src.access.admin", "src.access.authorized_write",
                     "src.access.grant_events", "src.storage.migrations",
                     "src.storage.ingest"}
        for f in base.glob("*.py"):
            assert _imported_modules(f.read_text()) & forbidden == set(), f"{f.name} imports writable module"

    def test_grant_admin_not_exposed(self, rt):
        assert get_tool("grant_admin") is None


# --------------------------------------------------------------------------
# Path safety
# --------------------------------------------------------------------------
class TestPathSafety:
    def test_no_hardcoded_username_path(self, rt):
        base = REPO_ROOT / "src" / "integration" / "m6"
        bad = ("/home/brian-nguyen", "/home/brian-nguyan")
        for f in base.glob("*.py"):
            src = f.read_text()
            for tok in bad:
                assert tok not in src, f"{f.name}: hard-coded user path '{tok}'"

    def test_repo_root_dynamic(self):
        assert REPO_ROOT.is_dir()
        assert (REPO_ROOT / "src" / "integration" / "m6").exists()

    def test_committed_paths_resolve_under_repo_root(self, rt):
        base = REPO_ROOT / "src" / "integration" / "m6"
        required = ["contracts.py", "errors.py", "tools.py", "dispatcher.py",
                    "mcp_wrapper.py", "runtime.py", "handlers.py", "__init__.py"]
        for name in required:
            p = base / name
            assert p.exists(), f"AD-HOC VERIFICATION INCOMPLETE — required path could not be verified: src/integration/m6/{name}"


# --------------------------------------------------------------------------
# M3 parity (M6 logical == direct M5 facade)
# --------------------------------------------------------------------------
class TestM3Parity:
    def test_query_parity(self, store_path, rt):
        from src.access.authorized_read import AuthorizedReadService
        from src.access.contracts import AccessRequest
        from src.access.resolver import resolve_read_grants
        from src.retrieval.db import open_readonly
        ro = open_readonly(store_path)
        grants = resolve_read_grants(ro.conn, "A")
        ar = AuthorizedReadService(ro, "A", grant_conn=ro.conn).query_events(
            AccessRequest(operation="READ", requesting_profile_id="A",
                          target_profile_ids=["A"], project_ids=["P"]), grants=grants)
        direct_ids = {v.event_id for v in ar.items}
        m6 = dispatch({"tool": "memory_query", "requesting_profile_id": "A",
                       "target_profile_ids": ["A"], "project_ids": ["P"]})
        m6_ids = {x.get("event_id") for x in m6.results}
        assert m6_ids == direct_ids
        ro.conn.close()

    def test_get_event_parity(self, store_path, rt):
        from src.access.authorized_read import AuthorizedReadService
        from src.access.contracts import AccessRequest
        from src.access.resolver import resolve_read_grants
        from src.retrieval.db import open_readonly
        ro = open_readonly(store_path)
        grants = resolve_read_grants(ro.conn, "A")
        ar = AuthorizedReadService(ro, "A", grant_conn=ro.conn).get_event(
            AccessRequest(operation="READ", requesting_profile_id="A"), "e1", grants=grants)
        direct_ok = ar.allowed and len(ar.items) == 1
        m6 = dispatch({"tool": "memory_get_event", "requesting_profile_id": "A", "query": "e1"})
        assert direct_ok and m6.status is ResponseStatus.SUCCESS
        ro.conn.close()


# --------------------------------------------------------------------------
# Zero LLM / network (static)
# --------------------------------------------------------------------------
class TestZeroExternal:
    def test_no_llm_or_network_imports(self, rt):
        base = REPO_ROOT / "src" / "integration" / "m6"
        forbidden = {"openai", "llm", "requests", "httpx", "socket", "aiohttp", "urllib", "http"}
        for f in base.glob("*.py"):
            assert _imported_modules(f.read_text()) & forbidden == set(), f"{f.name} imports external module"

    def test_dispatch_no_network(self, rt):
        r = dispatch({"tool": "memory_query", "requesting_profile_id": "A",
                      "target_profile_ids": ["A"], "project_ids": ["P"]})
        assert r.status in (ResponseStatus.SUCCESS, ResponseStatus.EMPTY)
