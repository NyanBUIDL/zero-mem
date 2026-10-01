"""T6b - the MCP memory tool set (``src.integration.m6w``), driven in process against a real data root.

recall / context (read) and add / ingest / forget (write) all delegate to ``zero_mem.memory.Memory`` as the PINNED
profile. These tests pin the tool contract: closed schemas, structured statuses, ``isError``, bounded outputs, no
identity/scope authority from the caller, path allowlist, and that nothing leaks paths, SQL or secrets.
"""
from __future__ import annotations

import json
import os
import re

import pytest

from src.integration.m6w import ToolSetConfig, ToolSetConfigError, build_tool_set
from tests.unit import adapters_fixtures as fx
from tests.unit.t5_memory_helpers import Env
from tests.unit.t6b_helpers import SECRET_ENV, SECRET_TOKEN, STATUS_ERRORS

READ_TOOLS = ["memory_recall", "memory_context"]
WRITE_TOOLS = ["memory_add", "memory_ingest", "memory_forget"]


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.close()


@pytest.fixture
def allowed(tmp_path):
    d = tmp_path / "allowed"
    d.mkdir()
    return d


def toolset(env, profile="claude-code", *, write=True, roots=(), config=None, register=True):
    if register:
        env.prov.add_agent(profile)
    return build_tool_set(profile_id=profile, layout=env.layout, enable_write=write,
                          allow_roots=[str(r) for r in roots], config=config)


def run(ts, tool, **arguments):
    result = ts.call(tool, arguments)
    assert set(result) == {"content", "structuredContent", "isError"}
    envelope = result["structuredContent"]
    assert result["isError"] is (envelope["status"] in STATUS_ERRORS), envelope
    assert isinstance(result["content"], list) and result["content"][0]["type"] == "text"
    return envelope


def text_of(ts, tool, **arguments):
    return ts.call(tool, arguments)["content"][0]["text"]


# ----------------------------------------------------------------------------------------------- tool list
def test_read_tools_are_always_present_and_write_tools_only_when_enabled(env):
    assert list(toolset(env, write=False).names) == READ_TOOLS
    assert list(toolset(env, write=True, register=False).names) == READ_TOOLS + WRITE_TOOLS


def test_a_write_tool_is_not_callable_when_write_is_disabled(env):
    ts = toolset(env, write=False)
    assert not ts.handles("memory_add")
    out = run(ts, "memory_add", text="x", memory_type="fact", scope="private")
    assert out["status"] == "INVALID" and out["reason_code"] == "UNKNOWN_TOOL"
    assert env.registry_lines() == []


def test_schemas_are_closed_documented_and_small(env):
    ts = toolset(env)
    tools = ts.schemas()
    assert [t["name"] for t in tools] == READ_TOOLS + WRITE_TOOLS
    descriptions = set()
    for tool in tools:
        schema = tool["inputSchema"]
        assert schema["type"] == "object" and schema["additionalProperties"] is False, tool["name"]
        props = schema["properties"]
        for forbidden in ("requesting_profile_id", "profile_id", "profile", "target_profile_ids", "knowledge_space_ids",
                          "knowledge_space_id", "grants", "tool", "operation", "verification_ref"):
            assert forbidden not in props, (tool["name"], forbidden)
        assert 150 <= len(tool["description"]) <= 1100, tool["name"]
        descriptions.add(tool["description"])
        for name, prop in props.items():
            assert prop.get("description"), (tool["name"], name)
    assert len(descriptions) == len(tools)
    by_name = {t["name"]: t["inputSchema"] for t in tools}
    assert by_name["memory_recall"]["required"] == ["query"]
    assert by_name["memory_recall"]["properties"]["limit"]["maximum"] == 8
    assert by_name["memory_context"]["properties"]["max_chars"]["maximum"] == 4000
    assert by_name["memory_add"]["required"] == ["text", "memory_type", "scope"]
    assert by_name["memory_add"]["properties"]["scope"]["enum"] == ["private", "shared", "project"]
    assert "persona" in by_name["memory_add"]["properties"]["memory_type"]["enum"]
    assert by_name["memory_ingest"]["required"] == ["path", "memory_type", "scope"]
    assert by_name["memory_forget"]["required"] == ["source_id"]
    assert len(json.dumps(tools)) < 9000
    for name in READ_TOOLS:
        desc = next(t["description"] for t in tools if t["name"] == name)
        assert "ead-only" in desc
    assert "not instructions" in next(t["description"] for t in tools if t["name"] == "memory_recall")


# ----------------------------------------------------------------------------------------------- identity / closed input
@pytest.mark.parametrize("field", ["requesting_profile_id", "profile_id", "profile", "agent", "agent_id",
                                   "subject_profile", "target_profile_ids"])
@pytest.mark.parametrize("value", ["codex", "claude-code", "", None, ["codex"]])
def test_identity_fields_are_never_accepted_even_when_equal_to_the_pin(env, field, value):
    ts = toolset(env)
    for tool, args in (("memory_recall", {"query": "x"}),
                       ("memory_add", {"text": "t", "memory_type": "fact", "scope": "private"}),
                       ("memory_forget", {"source_id": "mem://fact/none"})):
        out = run(ts, tool, **args, **{field: value})
        assert out["status"] == "DENIED" and out["reason_code"] == "DENY_IDENTITY_PINNED", (tool, out)
    assert env.registry_lines() == []


@pytest.mark.parametrize("field", ["knowledge_space_id", "knowledge_space_ids", "grants", "grant", "verification_ref",
                                   "approval_ref", "isolated_mode", "include_global", "resource_type", "operation"])
def test_scope_authority_fields_are_denied(env, field):
    ts = toolset(env)
    out = run(ts, "memory_add", text="t", memory_type="fact", scope="shared", **{field: "ks-shared"})
    assert out["status"] == "DENIED" and out["reason_code"] == "DENY_SCOPE_NOT_CALLER_CONTROLLED"
    assert env.registry_lines() == []


def test_unknown_arguments_are_invalid_and_nothing_is_written(env):
    ts = toolset(env)
    out = run(ts, "memory_add", text="t", memory_type="fact", scope="private", colour="red")
    assert out["status"] == "INVALID" and out["reason_code"] == "UNKNOWN_ARGUMENT"
    assert "colour" in out["message"]
    assert env.registry_lines() == []


def test_every_write_is_attributed_to_the_pinned_profile(env):
    ts = toolset(env, "codex")
    assert ts.profile_id == "codex"
    out = run(ts, "memory_add", text="codex note about narwhals", memory_type="fact", scope="private")
    assert out["status"] == "SUCCESS"
    assert [l["profile_id"] for l in env.registry_lines()] == ["codex"]


def test_a_non_object_or_garbage_call_never_raises(env):
    ts = toolset(env)
    for bad in (None, [], "x", 5):
        result = ts.call("memory_recall", bad)
        assert result["isError"] is True and result["structuredContent"]["status"] == "INVALID"
    assert ts.call("nope", {})["structuredContent"]["reason_code"] == "UNKNOWN_TOOL"


@pytest.mark.parametrize("bad", ["", " ", "has space", "../x", "a" * 65, "-lead", None, 5])
def test_the_pinned_profile_must_be_a_valid_id(env, bad):
    with pytest.raises(ToolSetConfigError):
        build_tool_set(profile_id=bad, layout=env.layout)


# ----------------------------------------------------------------------------------------------- memory_add
def test_add_creates_updates_and_dedups_with_structured_status(env):
    ts = toolset(env)
    first = run(ts, "memory_add", text="Alice prefers PostgreSQL for storage.", memory_type="fact", scope="private")
    assert first["status"] == "SUCCESS" and first["result"] == "created"
    assert first["scope"] == "private" and first["memory_type"] == "fact"
    assert first["ref"].startswith("mem://fact/") and re.fullmatch(r"[0-9a-f]{16}", first["source_id"])
    again = run(ts, "memory_add", text="Alice prefers PostgreSQL for storage.", memory_type="fact", scope="private")
    assert again["status"] == "SUCCESS" and again["result"] == "unchanged"
    named = run(ts, "memory_add", text="Terse answers.", memory_type="persona", name="style", scope="private")
    updated = run(ts, "memory_add", text="Terse answers, no emojis.", memory_type="persona", name="style",
                  scope="private")
    assert named["result"] == "created" and updated["result"] == "updated" and updated["ref"] == "mem://persona/style"
    assert "mem://persona/style" in text_of(ts, "memory_add", text="Terse answers, no emojis.", memory_type="persona",
                                            name="style", scope="private")


def test_add_to_the_shared_space_without_operator_approval_is_denied_and_stores_nothing(env):
    ts = toolset(env)
    out = run(ts, "memory_add", text="shared persona text", memory_type="persona", scope="shared")
    assert out["status"] == "DENIED" and out["reason_code"] == "DENY_CROSS_PROFILE_WRITE"
    assert "grant-write claude-code --space ks-shared" in out["operator_hint"]
    assert "ks-shared" in text_of(ts, "memory_add", text="shared persona text", memory_type="persona", scope="shared")
    assert env.registry_lines() == [] and env.units() == []


def test_add_to_the_shared_space_after_operator_approval_succeeds(env):
    ts = toolset(env)
    env.prov.grant_write("claude-code", space="ks-shared", basis="test approval")
    out = run(ts, "memory_add", text="shared persona text", memory_type="persona", name="style", scope="shared")
    assert out["status"] == "SUCCESS" and out["scope"] == "shared"
    other = toolset(env, "codex")
    hit = run(other, "memory_recall", query="persona text")["hits"][0]
    assert hit["scope"] == "shared" and hit["ref"] == "mem://persona/style"


def test_devlog_needs_project_scope_and_a_project_grant(env):
    ts = toolset(env)
    bad = run(ts, "memory_add", text="did x", memory_type="devlog", scope="private")
    assert bad["status"] == "INVALID" and bad["reason_code"] == "devlog_requires_project_scope"
    missing = run(ts, "memory_add", text="did x", memory_type="devlog", scope="project")
    assert missing["status"] == "INVALID" and missing["reason_code"] == "project_id_required"
    denied = run(ts, "memory_add", text="did x", memory_type="devlog", scope="project", project_id="zero-mem")
    assert denied["status"] == "DENIED" and "--project zero-mem" in denied["operator_hint"]
    env.prov.grant_write("claude-code", project="zero-mem")
    ok = run(ts, "memory_add", text="fixed the flaky lock test", memory_type="devlog", scope="project",
             project_id="zero-mem")
    assert ok["status"] == "SUCCESS" and ok["scope"] == "project"


def test_secrets_are_rejected_with_a_fixed_rule_id_and_never_stored_or_echoed(env):
    ts = toolset(env)
    for secret in (SECRET_TOKEN, SECRET_ENV):
        result = ts.call("memory_add", {"text": f"my key is {secret} ok", "memory_type": "fact", "scope": "private"})
        out = result["structuredContent"]
        assert out["status"] == "REJECTED_SECRET" and result["isError"] is True
        assert out["rule_ids"] and all(re.fullmatch(r"[A-Za-z0-9_.-]+", r) for r in out["rule_ids"])
        assert secret not in json.dumps(result) and "hunter2" not in json.dumps(result)
        assert "Nothing was stored" in result["content"][0]["text"]
    assert env.registry_lines() == [] and env.units() == []
    assert env.files_containing("hunter2hunter2") == [] and env.files_containing(SECRET_TOKEN) == []


@pytest.mark.parametrize("args,reason", [
    ({"text": "", "memory_type": "fact", "scope": "private"}, "SCHEMA_VIOLATION"),
    ({"text": "x", "memory_type": "diary", "scope": "private"}, "SCHEMA_VIOLATION"),
    ({"text": "x", "memory_type": "fact", "scope": "everyone"}, "SCHEMA_VIOLATION"),
    ({"text": "x", "memory_type": "fact"}, "SCHEMA_VIOLATION"),
    ({"text": 5, "memory_type": "fact", "scope": "private"}, "SCHEMA_VIOLATION"),
    ({"text": "x", "memory_type": "fact", "scope": "private", "name": "has space"}, "SCHEMA_VIOLATION"),
    ({"text": "x", "memory_type": "fact", "scope": "private", "name": "a/../b"}, "invalid_name"),
    ({"text": "x" * 100_001, "memory_type": "fact", "scope": "private"}, "SCHEMA_VIOLATION"),
    ({"text": "x", "memory_type": "fact", "scope": "private", "project_id": "p"}, "project_id_not_allowed"),
    ({"text": "x", "memory_type": "fact", "scope": "project", "project_id": "bad id"}, "SCHEMA_VIOLATION"),
])
def test_add_rejects_malformed_arguments_with_invalid(env, args, reason):
    out = run(toolset(env), "memory_add", **args)
    assert out["status"] == "INVALID" and out["reason_code"] == reason, out
    assert env.registry_lines() == []


# ----------------------------------------------------------------------------------------------- memory_recall
def test_recall_returns_compact_hits_with_a_short_forgettable_id(env):
    ts = toolset(env)
    run(ts, "memory_add", text="Gazelles run very fast across the savanna.", memory_type="fact", scope="private")
    out = run(ts, "memory_recall", query="how fast do gazelles run")
    assert out["status"] == "SUCCESS" and out["count"] == 1
    hit = out["hits"][0]
    assert set(hit) == {"text", "ref", "type", "scope", "score", "source_id"}
    assert "Gazelles run very fast" in hit["text"] and hit["scope"] == "private" and hit["type"] == "fact"
    assert re.fullmatch(r"[0-9a-f]{16}", hit["source_id"])
    rendered = text_of(ts, "memory_recall", query="gazelles")
    assert "Gazelles run very fast" in rendered and hit["source_id"] in rendered
    assert "profile_id" not in json.dumps(out) and "unit_id" not in json.dumps(out)


def test_recall_with_no_match_is_empty_and_not_an_error(env):
    out = run(toolset(env), "memory_recall", query="nonexistentword")
    assert out["status"] == "EMPTY" and out["count"] == 0 and out["hits"] == []


def test_recall_filters_by_memory_type_and_bounds_the_limit(env):
    ts = toolset(env)
    for i in range(10):
        run(ts, "memory_add", text=f"quokka fact number {i}", memory_type="fact", scope="private")
    run(ts, "memory_add", text="quokka workflow steps", memory_type="workflow", name="quokka", scope="private")
    assert run(ts, "memory_recall", query="quokka")["count"] == 5  # default
    assert run(ts, "memory_recall", query="quokka", limit=8)["count"] == 8
    only = run(ts, "memory_recall", query="quokka", memory_types=["workflow"])
    assert [h["type"] for h in only["hits"]] == ["workflow"]
    both = run(ts, "memory_recall", query="quokka", memory_types=["workflow", "fact"], limit=8)
    assert {h["type"] for h in both["hits"]} == {"workflow", "fact"}
    for bad in (0, 9, 100, -1, "3", 2.5, True):
        out = run(ts, "memory_recall", query="quokka", limit=bad)
        assert out["status"] == "INVALID", bad
    assert run(ts, "memory_recall", query="quokka", memory_types=["nope"])["status"] == "INVALID"
    assert run(ts, "memory_recall", query="   ")["status"] == "INVALID"
    assert run(ts, "memory_recall", query="q" * 1001)["status"] == "INVALID"
    assert run(ts, "memory_recall", query="quokka", memory_types=[])["status"] == "INVALID"


def test_recall_output_is_token_bounded(env):
    ts = toolset(env)
    for i in range(8):
        run(ts, "memory_add", text=("lengthy " * 400) + f" marker{i} wallaby", memory_type="fact", scope="private")
    result = ts.call("memory_recall", {"query": "wallaby", "limit": 8})
    out = result["structuredContent"]
    assert out["status"] == "SUCCESS" and out["count"] >= 1
    assert all(len(h["text"]) <= 600 for h in out["hits"])
    assert len(result["content"][0]["text"]) <= 6000
    assert sum(len(h["text"]) for h in out["hits"]) <= 5000
    assert len(json.dumps(out)) <= 9000


def test_private_notes_of_another_agent_are_never_returned(env):
    cc, codex = toolset(env, "claude-code"), toolset(env, "codex")
    run(cc, "memory_add", text="claude private note about narwhals", memory_type="fact", scope="private")
    assert run(codex, "memory_recall", query="narwhals")["status"] == "EMPTY"
    assert run(cc, "memory_recall", query="narwhals")["status"] == "SUCCESS"


def test_recall_of_a_project_devlog_needs_a_read_grant(env):
    cc, codex = toolset(env, "claude-code"), toolset(env, "codex")
    env.prov.grant_write("claude-code", project="zero-mem")
    run(cc, "memory_add", text="wrote the lock fix for ravens", memory_type="devlog", scope="project",
        project_id="zero-mem")
    assert run(codex, "memory_recall", query="ravens", project_id="zero-mem")["status"] == "EMPTY"
    env.prov.grant_read("codex", project="zero-mem")
    out = run(codex, "memory_recall", query="ravens", project_id="zero-mem")
    assert out["status"] == "SUCCESS" and out["hits"][0]["scope"] == "project"


# ----------------------------------------------------------------------------------------------- memory_context
def test_context_is_a_bounded_bundle_of_persona_workflow_skill_and_devlog(env):
    ts = toolset(env)
    env.prov.grant_write("claude-code", space="ks-shared")
    env.prov.grant_write("claude-code", project="zero-mem")
    run(ts, "memory_add", text="The user prefers terse answers.", memory_type="persona", name="style", scope="shared")
    run(ts, "memory_add", text="Always run pytest before every commit.", memory_type="workflow", name="commit",
        scope="shared")
    run(ts, "memory_add", text="---\nname: deploy\ndescription: Deploy the service to staging\n---\nSteps follow.",
        memory_type="skill", name="deploy", scope="shared")
    run(ts, "memory_add", text="Fixed the flaky lock test", memory_type="devlog", scope="project", project_id="zero-mem")
    result = ts.call("memory_context", {"max_chars": 2000, "project_id": "zero-mem"})
    out, text = result["structuredContent"], result["content"][0]["text"]
    assert out["status"] == "SUCCESS" and out["max_chars"] == 2000 and len(text) <= 2000 and text == out["text"]
    assert "terse answers" in text and "pytest before every commit" in text
    assert "deploy" in text and "Deploy the service to staging" in text and "flaky lock test" in text
    small = run(ts, "memory_context", max_chars=200)
    assert small["status"] == "SUCCESS" and small["chars"] <= 200 and small["truncated"] is True


def test_context_defaults_are_bounded_and_an_empty_memory_is_not_an_error(env):
    ts = toolset(env)
    out = run(ts, "memory_context")
    assert out["status"] == "EMPTY" and out["max_chars"] == 3000
    for bad in (0, 99, 199, 4001, 10**6, "300", 3.5, True, None):
        assert run(ts, "memory_context", max_chars=bad)["status"] == "INVALID", bad
    assert run(ts, "memory_context", project_id="bad id")["status"] == "INVALID"


# ----------------------------------------------------------------------------------------------- memory_forget
def test_forget_removes_the_memory_from_recall_for_every_agent(env):
    cc, codex = toolset(env, "claude-code"), toolset(env, "codex")
    env.prov.grant_write("claude-code", space="ks-shared")
    added = run(cc, "memory_add", text="shared fact about okapis", memory_type="fact", scope="shared")
    assert run(codex, "memory_recall", query="okapis")["status"] == "SUCCESS"
    gone = run(cc, "memory_forget", source_id=added["source_id"])
    assert gone["status"] == "SUCCESS" and gone["result"] == "forgotten" and gone["ref"] == added["ref"]
    assert run(codex, "memory_recall", query="okapis")["status"] == "EMPTY"
    assert run(cc, "memory_recall", query="okapis")["status"] == "EMPTY"
    again = run(cc, "memory_forget", source_id=added["ref"])
    assert again["status"] == "SUCCESS" and again["result"] == "already_forgotten"


def test_forget_of_a_shared_memory_needs_the_write_approval(env):
    cc, codex = toolset(env, "claude-code"), toolset(env, "codex")
    env.prov.grant_write("claude-code", space="ks-shared")
    added = run(cc, "memory_add", text="shared fact about tapirs", memory_type="fact", scope="shared")
    out = run(codex, "memory_forget", source_id=added["source_id"])
    assert out["status"] == "DENIED" and "grant-write codex --space ks-shared" in out["operator_hint"]
    assert run(codex, "memory_recall", query="tapirs")["status"] == "SUCCESS"


def test_forget_cannot_reach_another_agents_private_memory_and_leaks_no_ids(env):
    cc, codex = toolset(env, "claude-code"), toolset(env, "codex")
    mine = run(cc, "memory_add", text="same words in two private stores", memory_type="fact", scope="private")
    theirs = run(codex, "memory_add", text="same words in two private stores", memory_type="fact", scope="private")
    assert mine["ref"] == theirs["ref"] and mine["source_id"] != theirs["source_id"]
    other = run(codex, "memory_forget", source_id="f" * 16)
    assert other["status"] == "NOT_FOUND"
    # the shared ref names two sources (one per profile): the answer must not reveal codex's id
    ambiguous = cc.call("memory_forget", {"source_id": mine["ref"]})
    assert theirs["source_id"] not in json.dumps(ambiguous)
    assert ambiguous["structuredContent"]["status"] == "INVALID"
    assert ambiguous["structuredContent"]["reason_code"] == "AMBIGUOUS_REFERENCE"
    assert run(cc, "memory_forget", source_id=mine["source_id"])["status"] == "SUCCESS"
    assert run(codex, "memory_recall", query="private stores")["status"] == "SUCCESS"
    assert run(cc, "memory_recall", query="private stores")["status"] == "EMPTY"


@pytest.mark.parametrize("bad", ["", "abc", "x" * 601, 5, None])
def test_forget_validates_its_argument(env, bad):
    args = {} if bad is None else {"source_id": bad}
    assert run(toolset(env), "memory_forget", **args)["status"] == "INVALID"


# ----------------------------------------------------------------------------------------------- memory_ingest
def _tree(allowed):
    (allowed / "notes.md").write_text("# Notes\n\nThe zebra migration happens on Friday.\n", encoding="utf-8")
    (allowed / "plan.docx").write_bytes(fx.make_docx([("h", 1, "Release plan"), ("p", "Ship the okapi feature in March.")]))
    (allowed / "table.xlsx").write_bytes(fx.make_xlsx([("Sheet1", [["animal", "count"], ["quokka", 7]])]))
    return allowed


def test_ingest_a_folder_of_docx_xlsx_and_md_makes_it_recallable(env, allowed):
    _tree(allowed)
    ts = toolset(env, roots=[allowed])
    out = run(ts, "memory_ingest", path=str(allowed), memory_type="file", scope="private")
    assert out["status"] == "SUCCESS" and out["counts"]["created"] == 3 and out["counts"]["rejected"] == 0
    for query, needle in (("zebra migration", "zebra"), ("okapi feature", "okapi"), ("quokka", "quokka")):
        hit = run(ts, "memory_recall", query=query)["hits"][0]
        assert needle in hit["text"].lower() and hit["type"] == "file"
    again = run(ts, "memory_ingest", path=str(allowed), memory_type="file", scope="private")
    assert again["status"] == "SUCCESS" and again["counts"]["unchanged"] == 3 and again["counts"]["created"] == 0
    # one named file is its own source (file://notes.md), distinct from the same file met inside the folder
    single = run(ts, "memory_ingest", path=str(allowed / "notes.md"), memory_type="file", scope="private")
    assert single["status"] == "SUCCESS" and single["counts"]["created"] == 1
    single = run(ts, "memory_ingest", path=str(allowed / "notes.md"), memory_type="file", scope="private")
    assert single["status"] == "SUCCESS" and single["counts"]["unchanged"] == 1


def test_ingest_into_the_shared_space_needs_approval(env, allowed):
    _tree(allowed)
    ts = toolset(env, roots=[allowed])
    out = run(ts, "memory_ingest", path=str(allowed), memory_type="file", scope="shared")
    assert out["status"] == "DENIED" and out["reason_code"] == "DENY_CROSS_PROFILE_WRITE"
    assert env.registry_lines() == []


def test_ingest_refuses_paths_outside_the_allowlist_without_revealing_anything(env, allowed, tmp_path):
    _tree(allowed)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text("the vault code is orchid", encoding="utf-8")
    ts = toolset(env, roots=[allowed])
    for target in (outside, outside / "private.txt", tmp_path / "does-not-exist", "/etc/passwd", "/",
                   str(allowed) + "/../outside", str(allowed.parent), str(allowed) + "x"):
        result = ts.call("memory_ingest", {"path": str(target), "memory_type": "file", "scope": "private"})
        out = result["structuredContent"]
        assert out["status"] == "DENIED" and out["reason_code"] == "DENY_PATH_OUTSIDE_ALLOWLIST", (target, out)
        body = json.dumps(result)
        assert str(tmp_path) not in body and str(allowed) not in body and "etc/passwd" not in body
    assert env.registry_lines() == []


def test_ingest_refuses_symlinks_even_inside_the_allowlist(env, allowed, tmp_path):
    _tree(allowed)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text("the vault code is orchid", encoding="utf-8")
    (allowed / "link.txt").symlink_to(outside / "private.txt")
    (allowed / "dirlink").symlink_to(outside, target_is_directory=True)
    ts = toolset(env, roots=[allowed])
    for target in (allowed / "link.txt", allowed / "dirlink", allowed / "dirlink" / "private.txt"):
        out = run(ts, "memory_ingest", path=str(target), memory_type="file", scope="private")
        assert out["status"] == "DENIED" and out["reason_code"] == "DENY_SYMLINK", (target, out)
    # a symlink met while walking an allowed folder is skipped, never followed
    out = run(ts, "memory_ingest", path=str(allowed), memory_type="file", scope="private")
    assert out["status"] == "SUCCESS" and out["counts"]["created"] == 3
    assert run(ts, "memory_recall", query="orchid")["status"] == "EMPTY"
    assert env.files_containing("orchid") == []


def test_a_symlinked_allow_root_is_followed_but_a_symlink_below_it_is_not(env, allowed, tmp_path):
    _tree(allowed)
    link = tmp_path / "via-link"
    link.symlink_to(allowed, target_is_directory=True)
    ts = toolset(env, roots=[link])
    ok = run(ts, "memory_ingest", path=str(link), memory_type="file", scope="private")
    assert ok["status"] == "SUCCESS" and ok["counts"]["created"] == 3


def test_ingest_requires_an_absolute_existing_path_under_a_root(env, allowed):
    ts = toolset(env, roots=[allowed])
    for relative in ("notes.md", "./notes.md", "~/notes.md", "..", ""):
        assert run(ts, "memory_ingest", path=relative, memory_type="file", scope="private")["status"] == "INVALID", relative
    out = run(ts, "memory_ingest", path=str(allowed / "missing.md"), memory_type="file", scope="private")
    assert out["status"] == "INVALID" and out["reason_code"] == "PATH_NOT_FOUND"
    assert str(allowed) not in json.dumps(out)
    assert run(ts, "memory_ingest", path=str(allowed) + "\x00", memory_type="file", scope="private")["status"] == "INVALID"


def test_ingest_without_any_allowed_root_is_disabled(env, allowed):
    _tree(allowed)
    ts = toolset(env, roots=[])
    out = run(ts, "memory_ingest", path=str(allowed), memory_type="file", scope="private")
    assert out["status"] == "DENIED" and out["reason_code"] == "DENY_NO_ALLOWED_ROOTS"
    assert env.registry_lines() == []


def test_the_memory_store_itself_cannot_be_ingested(env, tmp_path):
    ts = toolset(env, roots=[tmp_path])  # an operator mistake: the root contains the data root
    for target in (env.root, env.layout.corpus_root, env.layout.memory_stream, env.layout.derived_db, tmp_path):
        out = run(ts, "memory_ingest", path=str(target), memory_type="file", scope="private")
        assert out["status"] == "DENIED" and out["reason_code"] == "DENY_PATH_RESERVED", (target, out)
    assert env.registry_lines() == []


def test_ingest_rejects_secret_files_and_reports_partial_without_storing_them(env, allowed):
    _tree(allowed)
    (allowed / "leak.md").write_text(f"deploy notes\n{SECRET_ENV}\n", encoding="utf-8")
    ts = toolset(env, roots=[allowed])
    result = ts.call("memory_ingest", {"path": str(allowed), "memory_type": "file", "scope": "private"})
    out = result["structuredContent"]
    assert out["status"] == "PARTIAL" and result["isError"] is True
    assert out["counts"]["created"] == 3 and out["counts"]["rejected"] == 1
    assert out["rejected"] == [{"name": "leak.md", "status": "REJECTED_SECRET", "reason": "secret_detected"}]
    assert "hunter2" not in json.dumps(result) and env.files_containing("hunter2hunter2") == []
    only = run(ts, "memory_ingest", path=str(allowed / "leak.md"), memory_type="file", scope="private")
    assert only["status"] == "REJECTED_SECRET"


def test_ingest_rejects_unsupported_files(env, allowed):
    (allowed / "blob.bin").write_bytes(bytes(range(256)) * 8)
    (allowed / "empty.txt").write_bytes(b"")
    ts = toolset(env, roots=[allowed])
    out = run(ts, "memory_ingest", path=str(allowed / "blob.bin"), memory_type="file", scope="private")
    assert out["status"] in ("REJECTED_CONTENT", "SUCCESS") and out["counts"]["created"] == 0
    folder = run(ts, "memory_ingest", path=str(allowed), memory_type="file", scope="private")
    assert folder["counts"]["created"] == 0 and folder["skipped"]


def test_ingest_size_caps_bound_the_work_and_the_report(env, allowed):
    for i in range(12):
        (allowed / f"n{i:02d}.md").write_text(f"# Note {i}\n\nunique heron fact {i} " + "word " * 50, encoding="utf-8")
    cfg = ToolSetConfig(max_ingest_files=5, max_ingest_bytes=10_000_000, report_items=3)
    ts = toolset(env, roots=[allowed], config=cfg)
    out = run(ts, "memory_ingest", path=str(allowed), memory_type="file", scope="private")
    assert out["counts"]["created"] == 5
    assert out["status"] == "PARTIAL" and any(s["reason"] == "max_files_reached" for s in out["skipped"])
    assert len(out["skipped"]) <= 3 and len(out["created"]) <= 3
    tiny = toolset(env, roots=[allowed], config=ToolSetConfig(max_ingest_files=100, max_ingest_bytes=300), register=False)
    out = run(tiny, "memory_ingest", path=str(allowed), memory_type="file", scope="private")
    assert out["status"] == "PARTIAL" and any(s["reason"] == "max_total_bytes_reached" for s in out["skipped"])


def test_ingest_report_is_bounded_for_a_big_folder(env, allowed):
    for i in range(60):
        (allowed / f"f{i:03d}.txt").write_text(f"ibis document {i} " + "x" * 40, encoding="utf-8")
    ts = toolset(env, roots=[allowed])
    result = ts.call("memory_ingest", {"path": str(allowed), "memory_type": "file", "scope": "private"})
    out = result["structuredContent"]
    assert out["counts"]["created"] == 60 and len(out["created"]) <= 10
    assert len(result["content"][0]["text"]) <= 2500 and len(json.dumps(out)) <= 6000


# ----------------------------------------------------------------------------------------------- never raise, never leak
def test_an_unexpected_failure_is_a_fixed_error_that_leaks_nothing(env, monkeypatch):
    from zero_mem import memory as memory_module

    ts = toolset(env)
    boom = "sqlite3.OperationalError: no such table zm_x at /srv/private/zero-mem.sqlite3 SELECT * FROM secret_table"

    def explode(*_a, **_k):
        raise RuntimeError(boom)

    for name in ("add", "ingest", "recall", "context", "forget"):
        monkeypatch.setattr(memory_module.Memory, name, explode)
    cases = [("memory_add", {"text": "t", "memory_type": "fact", "scope": "private"}),
             ("memory_ingest", {"path": str(env.root.parent), "memory_type": "file", "scope": "private"}),
             ("memory_recall", {"query": "t"}), ("memory_context", {}), ("memory_forget", {"source_id": "mem://fact/abc"})]
    ts_write = toolset(env, roots=[env.root.parent], register=False)
    for tool, args in cases:
        result = ts_write.call(tool, args)
        body = json.dumps(result)
        assert result["isError"] is True and result["structuredContent"]["status"] in ("ERROR", "DENIED"), tool
        for leak in ("sqlite3", "/srv/private", "SELECT", "secret_table", "Traceback", "RuntimeError"):
            assert leak not in body, (tool, leak)


def test_library_error_reasons_are_normalized(env, monkeypatch):
    from zero_mem import memory as memory_module
    from zero_mem.memory_results import WriteResult

    ts = toolset(env)
    monkeypatch.setattr(memory_module.Memory, "add",
                        lambda self, *a, **k: WriteResult(status="error", reason="internal_error:OperationalError"))
    out = run(ts, "memory_add", text="t", memory_type="fact", scope="private")
    assert out["status"] == "ERROR" and out["reason_code"] == "INTERNAL_ERROR"
    assert "Operational" not in json.dumps(out)


def test_tool_results_are_json_serializable_and_never_contain_the_data_root(env):
    ts = toolset(env)
    run(ts, "memory_add", text="a note about pelicans", memory_type="fact", scope="private")
    for tool, args in (("memory_recall", {"query": "pelicans"}), ("memory_context", {}),
                       ("memory_add", {"text": "a note about pelicans", "memory_type": "fact", "scope": "private"})):
        blob = json.dumps(ts.call(tool, args))
        assert str(env.root) not in blob and os.sep + "corpus" not in blob and ".sqlite" not in blob
