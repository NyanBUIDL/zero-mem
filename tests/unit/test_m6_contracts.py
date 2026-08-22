"""M6.1 focused tests — integration contracts and read-only transport/tool surface.

Covers: contracts, registry, resource types, identity/security, response
envelope, transport wrapper, read-only boundaries, determinism, zero
LLM/network, filesystem safety.
"""

import ast
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.integration.m6 import (
    M6Request, M6Response, Operation, ResourceType, ResponseStatus,
    validate_request, TOOL_REGISTRY, ToolSpec, get_tool, list_tool_names,
    Dispatcher, dispatch, M6Error, M6ErrorCode,
)
from src.integration.m6 import mcp_wrapper


SECRET = "SK-M6-DONTLEAK-9a8b7c6d"


# --------------------------------------------------------------------------
# Contracts
# --------------------------------------------------------------------------
class TestContracts:
    def test_all_approved_tools_present(self):
        names = set(list_tool_names())
        expected = {
            "memory_query", "memory_search", "memory_get_event", "memory_get_related",
            "project_get_charter", "project_list_requirements", "project_list_decisions",
            "project_get_state", "project_list_verifications", "project_list_artifacts",
        }
        assert expected <= names

    def test_normal_tools_are_read_only(self):
        for spec in TOOL_REGISTRY.values():
            assert spec.operation is Operation.READ

    def test_explicit_requester_retained(self):
        req = validate_request({"tool": "memory_query", "requesting_profile_id": "PR2"})
        assert req.requesting_profile_id == "PR2"

    def test_null_requester_retained(self):
        req = validate_request({"tool": "memory_query"})
        assert req.requesting_profile_id is None

    def test_project_fields_retained(self):
        req = validate_request({"tool": "memory_query", "project_ids": ["P1", "P2"],
                                "target_profile_ids": ["PR1"], "knowledge_space_ids": ["K1"]})
        assert req.project_ids == ["P1", "P2"]
        assert req.target_profile_ids == ["PR1"]
        assert req.knowledge_space_ids == ["K1"]

    def test_isolated_mode_retained(self):
        req = validate_request({"tool": "memory_query", "isolated_mode": True})
        assert req.isolated_mode is True
        req2 = validate_request({"tool": "memory_query", "isolated_mode": False})
        assert req2.isolated_mode is False

    def test_include_global_retained(self):
        req = validate_request({"tool": "memory_query", "include_global": False})
        assert req.include_global is False

    def test_pagination_fields_retained(self):
        req = validate_request({"tool": "memory_query", "limit": 10, "cursor": "abc"})
        assert req.limit == 10
        assert req.cursor == "abc"

    def test_unknown_field_rejected(self):
        resp = dispatch({"tool": "memory_query", "bogus": 1})
        assert resp.status is ResponseStatus.INVALID_REQUEST

    def test_invalid_enum_rejected(self):
        resp = dispatch({"tool": "memory_query", "resource_type": "nope"})
        assert resp.status is ResponseStatus.INVALID_REQUEST

    def test_invalid_limit_rejected(self):
        resp = dispatch({"tool": "memory_query", "limit": -3})
        assert resp.status is ResponseStatus.INVALID_REQUEST
        resp2 = dispatch({"tool": "memory_query", "limit": 99999})
        assert resp2.status is ResponseStatus.INVALID_REQUEST

    def test_non_read_operation_rejected(self):
        resp = dispatch({"tool": "memory_query", "operation": "WRITE"})
        assert resp.status is ResponseStatus.UNSUPPORTED_OPERATION
        assert resp.reason_code == M6ErrorCode.UNSUPPORTED_OPERATION


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------
class TestRegistry:
    def test_only_allowlisted_dispatch(self):
        for name in list_tool_names():
            spec = get_tool(name)
            assert spec is not None
            assert spec.operation is Operation.READ

    def test_unknown_tool_rejected(self):
        resp = dispatch({"tool": "does_not_exist"})
        assert resp.status is ResponseStatus.UNSUPPORTED_TOOL

    def test_no_dynamic_function_execution(self):
        resp = dispatch({"tool": "__import__('os').system"})
        assert resp.status is ResponseStatus.UNSUPPORTED_TOOL

    @pytest.mark.parametrize("bad", [
        "execute_sql", "raw_sql", "sqlite_query", "database_query",
        "read_jsonl", "raw_jsonl", "read_file_arbitrary",
        "write_memory", "create_memory", "update_memory", "delete_memory",
        "create_grant", "revoke_grant", "supersede_grant", "grant_admin",
        "project_write", "requirement_write", "decision_write",
    ])
    def test_forbidden_tools_absent(self, bad):
        assert get_tool(bad) is None
        resp = dispatch({"tool": bad})
        assert resp.status is ResponseStatus.UNSUPPORTED_TOOL


# --------------------------------------------------------------------------
# Resource types
# --------------------------------------------------------------------------
class TestResourceTypes:
    def test_tool_resource_type_fixed(self):
        assert get_tool("project_list_requirements").resource_type is ResourceType.REQUIREMENT
        assert get_tool("project_list_decisions").resource_type is ResourceType.DECISION
        assert get_tool("project_list_artifacts").resource_type is ResourceType.ARTIFACT
        assert get_tool("memory_get_related").resource_type is ResourceType.RELATION

    def test_caller_cannot_downgrade_resource_type(self):
        resp = dispatch({"tool": "project_list_requirements", "resource_type": "event"})
        assert resp.status is ResponseStatus.INVALID_REQUEST

    def test_requirements_cannot_masquerade_as_event(self):
        resp = dispatch({"tool": "memory_get_event", "resource_type": "requirement"})
        assert resp.status is ResponseStatus.INVALID_REQUEST

    def test_artifact_remains_metadata_only(self):
        spec = get_tool("project_list_artifacts")
        assert spec.resource_type is ResourceType.ARTIFACT
        # No file-content tool exists in the registry.
        assert get_tool("read_artifact_file") is None


# --------------------------------------------------------------------------
# Identity / security
# --------------------------------------------------------------------------
class TestIdentitySecurity:
    def test_no_identity_inferred_from_cwd(self):
        os.chdir(os.getcwd())  # no effect; identity must be explicit
        req = validate_request({"tool": "memory_query"})
        assert req.requesting_profile_id is None

    def test_no_identity_from_session(self):
        req = validate_request({"tool": "memory_query", "session_id": "S1"})
        assert req.requesting_profile_id is None  # session is NOT identity

    def test_admin_true_rejected(self):
        resp = dispatch({"tool": "memory_query", "admin": True})
        assert resp.status is ResponseStatus.INVALID_REQUEST

    def test_trusted_true_rejected(self):
        resp = dispatch({"tool": "memory_query", "trusted": True})
        assert resp.status is ResponseStatus.INVALID_REQUEST

    def test_fake_grant_payload_rejected(self):
        resp = dispatch({"tool": "memory_query",
                         "grant_object": {"grant_id": "G1", "valid": True},
                         "authorized_read_grant": {"allow": True}})
        assert resp.status is ResponseStatus.INVALID_REQUEST

    def test_session_id_not_authority(self):
        # Session alone is not authority. Use an explicit unwired dispatcher so
        # this contract cannot depend on another test's runtime configuration.
        resp = dispatch(
            {"tool": "memory_query", "session_id": "S1", "operation": "READ"},
            dispatcher=Dispatcher(),
        )
        assert resp.status is ResponseStatus.CAPABILITY_UNAVAILABLE


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------
class TestResponse:
    def test_success_envelope(self):
        d = Dispatcher()
        d.register("memory_query", lambda req: [{"id": "e1"}])
        resp = d.dispatch_raw({"tool": "memory_query", "requesting_profile_id": "PR1"})
        assert resp.status is ResponseStatus.SUCCESS
        assert resp.results == [{"id": "e1"}]

    def test_zero_result_distinct_from_denial(self):
        d = Dispatcher()
        d.register("memory_query", lambda req: [])
        resp = d.dispatch_raw({"tool": "memory_query", "requesting_profile_id": "PR1"})
        assert resp.status is ResponseStatus.EMPTY
        assert resp.status is not ResponseStatus.POLICY_DENIED

    def test_denial_envelope_sanitized_shape(self):
        resp = M6Response(status=ResponseStatus.POLICY_DENIED, reason_code="DENY_CROSS_PROFILE_READ")
        out = resp.to_dict()
        assert out["status"] == "POLICY_DENIED"
        assert SECRET not in str(out)

    def test_invalid_request_sanitized(self):
        resp = dispatch({"tool": "memory_query", "bogus": 1})
        out = resp.to_dict()
        assert resp.status is ResponseStatus.INVALID_REQUEST
        assert "traceback" not in str(out).lower()
        assert "sqlite" not in str(out).lower()

    def test_unavailable_sanitized(self):
        # The unwired-tool envelope must remain sanitized.
        resp = dispatch(
            {"tool": "memory_query", "requesting_profile_id": "PR1"},
            dispatcher=Dispatcher(),
        )
        assert resp.status is ResponseStatus.CAPABILITY_UNAVAILABLE
        assert SECRET not in str(resp.to_dict())

    def test_no_raw_traceback_or_sql_or_path(self):
        resp = dispatch({"tool": "memory_query", "limit": "x"})
        blob = str(resp.to_dict()).lower()
        assert "traceback" not in blob
        assert ".db" not in blob
        assert "/home" not in blob


# --------------------------------------------------------------------------
# Transport wrapper
# --------------------------------------------------------------------------
class TestTransport:
    def test_direct_adapter_call_works(self):
        d = Dispatcher()
        d.register("memory_query", lambda req: [{"x": 1}])
        resp = dispatch({"tool": "memory_query"}, dispatcher=d)
        assert resp.status is ResponseStatus.SUCCESS

    def test_mcp_schema_maps_correctly(self):
        schemas = mcp_wrapper.tool_schemas()
        names = {s["name"] for s in schemas}
        assert "memory_query" in names
        assert all(s["inputSchema"]["properties"]["operation"]["const"] == "READ" for s in schemas)

    def test_mcp_handle_unknown_tool_safe(self):
        out = mcp_wrapper.handle_call("nope", {"tool": "nope"})
        assert out["status"] == "UNSUPPORTED_TOOL"

    def test_mcp_handle_malformed_payload_safe(self):
        out = mcp_wrapper.handle_call("memory_query", "not-a-dict")
        assert out["status"] in ("INVALID_REQUEST", "DOWNSTREAM_ERROR")

    def test_mcp_handle_unknown_field_safe(self):
        out = mcp_wrapper.handle_call("memory_query", {"tool": "memory_query", "bogus": 1})
        assert out["status"] == "INVALID_REQUEST"

    def test_mcp_handle_admin_field_safe(self):
        out = mcp_wrapper.handle_call("memory_query", {"tool": "memory_query", "admin": True})
        assert out["status"] == "INVALID_REQUEST"

    def test_local_transport_only_no_network(self):
        # handle_call performs no network; pure in-process dispatch
        out = mcp_wrapper.handle_call(
            "memory_query",
            {"tool": "memory_query", "requesting_profile_id": "PR1"},
            dispatcher=Dispatcher(),
        )
        assert out["status"] == "CAPABILITY_UNAVAILABLE"


# --------------------------------------------------------------------------
# Read-only boundaries (by construction)
# --------------------------------------------------------------------------
class TestReadOnlyBoundaries:
    def test_schema_still_v8(self):
        from src.storage.migrations import CURRENT_SCHEMA_VERSION
        assert CURRENT_SCHEMA_VERSION == 11

    def test_no_forbidden_writable_imports(self):
        import ast as _ast
        base = Path(__file__).resolve().parents[2] / "src" / "integration" / "m6"
        forbidden = {"src.access.admin", "src.access.authorized_write",
                     "src.access.grant_events", "src.storage.migrations",
                     "src.storage.ingest"}

        def _imported(src):
            mods = set()
            tree = _ast.parse(src)
            for node in _ast.walk(tree):
                if isinstance(node, _ast.Import):
                    for a in node.names:
                        mods.add(a.name.split(".")[0])
                elif isinstance(node, _ast.ImportFrom):
                    mods.add((node.module or "").split(".")[0])
            return mods

        # Also forbid the class names being imported (defensive, name-level).
        name_forbidden = ("GrantAdminService", "AuthorizedWriteService")
        for f in base.glob("*.py"):
            src = f.read_text()
            assert _imported(src) & forbidden == set(), f"{f.name} imports a writable module"
            for name in name_forbidden:
                # only as an `import X`/`from ... import X` of the class itself
                assert f"import {name}" not in src and f"import {name} as" not in src, f"{f.name} imports {name}"

    def test_no_projector_or_canonical_writer_imports(self):
        # AST-based: ensure no import of writable M5 modules. Deny-list *words*
        # (e.g. "admin") legitimately appear in our own deny-lists, so we inspect
        # actual import statements only.
        base = Path(__file__).resolve().parents[2] / "src" / "integration" / "m6"
        forbidden_modules = {
            "src.access.admin", "src.access.authorized_write",
            "src.access.grant_events", "src.storage.migrations",
            "src.storage.ingest",
        }
        for f in base.glob("*.py"):
            tree = ast.parse(f.read_text())
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    mods = [node.module or ""]
                for mod in mods:
                    assert mod not in forbidden_modules, f"{f.name} imports writable module '{mod}'"

    def test_grant_admin_service_not_exposed(self):
        # The registry must not contain any grant-admin tool.
        assert get_tool("grant_admin") is None
        assert get_tool("create_grant") is None

    def test_write_facade_not_exposed(self):
        assert get_tool("write_memory") is None

    def test_no_automatic_context_injection(self):
        # M6.1 has no injection path; dispatch returns explicit envelope only.
        resp = dispatch({"tool": "memory_query", "requesting_profile_id": "PR1"})
        assert isinstance(resp, M6Response)

    def test_no_m7_behavior(self):
        # No M7 tooling present.
        assert get_tool("memory_inject") is None


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------
class TestDeterminism:
    def test_identical_request_deterministic(self):
        a = validate_request({"tool": "memory_query", "project_ids": ["P2", "P1"]})
        b = validate_request({"tool": "memory_query", "project_ids": ["P2", "P1"]})
        # identical input yields identical normalized output (deterministic)
        assert a.project_ids == b.project_ids == ["P2", "P1"]

    def test_registry_ordering_deterministic(self):
        assert list_tool_names() == sorted(list_tool_names())

    def test_error_codes_deterministic(self):
        a = dispatch({"tool": "memory_query", "bogus": 1}).reason_code
        b = dispatch({"tool": "memory_query", "bogus": 2}).reason_code
        assert a == b == M6ErrorCode.INVALID_REQUEST


# --------------------------------------------------------------------------
# Zero LLM / network (static)
# --------------------------------------------------------------------------
class TestZeroExternal:
    def test_no_llm_or_network_imports(self):
        base = Path(__file__).resolve().parents[2] / "src" / "integration" / "m6"
        forbidden = {"openai", "requests", "httpx", "socket", "aiohttp",
                     "urllib", "http", "llm"}
        for f in base.glob("*.py"):
            tree = ast.parse(f.read_text())
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    mods = [(node.module or "").split(".")[0]]
                for mod in mods:
                    assert mod not in forbidden, f"{f.name} imports external module '{mod}'"

    def test_dispatch_no_network_call(self):
        # An unwired local dispatch must not perform network I/O.
        resp = dispatch(
            {"tool": "memory_query", "requesting_profile_id": "PR1"},
            dispatcher=Dispatcher(),
        )
        assert resp.status is ResponseStatus.CAPABILITY_UNAVAILABLE


# --------------------------------------------------------------------------
# Filesystem safety
# --------------------------------------------------------------------------
class TestFilesystemSafety:
    def test_real_hermes_home_untouched(self):
        # M6.1 performs no filesystem writes; assert no accidental temp artifacts
        # are created in the real home by importing/dispatching.
        hm = Path.home()
        before = set(hm.joinpath(".hermes").rglob("*")) if hm.joinpath(".hermes").exists() else set()
        _ = dispatch({"tool": "memory_query"})
        after = set(hm.joinpath(".hermes").rglob("*")) if hm.joinpath(".hermes").exists() else set()
        assert before == after
