"""T6b end to end - four agents (claude-code, codex, hermes, openclaw), each its OWN real stdio MCP server process,
all on ONE ``ZERO_MEM_DATA_ROOT``. Every server is started from exactly what ``zero-mem mcp-config`` prints for that
agent. The only client is our stdio JSON-RPC test client (no real Claude Code / Codex / Hermes / OpenClaw here).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading

import pytest

from tests.unit import adapters_fixtures as fx
from tests.unit.t6b_helpers import (AGENTS, SECRET_ENV, SECRET_TOKEN, McpProc, apply_env, grep_tree, launch,
                                    registration, registry_lines)
from zero_mem.memory_layout import Layout
from zero_mem.provisioning import Provisioner


class Fleet:
    """One data root, four registered agents, servers started on demand from the printed registrations."""

    def __init__(self, tmp_path, monkeypatch) -> None:
        apply_env(monkeypatch, tmp_path)
        self.tmp = tmp_path
        self.root = tmp_path / "data"
        self.layout = Layout.resolve(self.root)
        self.layout.ensure()
        self.prov = Provisioner(self.layout, operator="tester")
        for agent in AGENTS:
            self.prov.add_agent(agent)
        self.docs = tmp_path / "docs"
        self.docs.mkdir()
        self.procs: dict[str, McpProc] = {}

    def start(self, agent: str, *, write: bool = True, roots=None) -> McpProc:
        flags = ["--enable-write"] if write else []
        for root in (roots if roots is not None else ([self.docs] if write else [])):
            flags += ["--allow-root", str(root)]
        proc = launch(registration(agent, *flags), cwd=self.tmp)
        self.procs[agent] = proc
        return proc

    def start_all(self, **kw) -> dict[str, McpProc]:
        for agent in AGENTS:
            self.start(agent, **kw)
        return self.procs

    def close(self) -> dict[str, str]:
        return {a: p.close() for a, p in self.procs.items()}


@pytest.fixture
def fleet(tmp_path, monkeypatch):
    f = Fleet(tmp_path, monkeypatch)
    yield f
    stderrs = f.close()
    for agent, err in stderrs.items():
        assert "Traceback" not in err, (agent, err)
        assert SECRET_TOKEN not in err and "hunter2" not in err


def add(proc, text, memory_type="fact", scope="private", **extra):
    return proc.env("memory_add", {"text": text, "memory_type": memory_type, "scope": scope, **extra})


def recall(proc, query, **extra):
    return proc.env("memory_recall", {"query": query, **extra})


def texts(envelope):
    return [h["text"] for h in envelope.get("hits", [])]


# ----------------------------------------------------------------------------------------------- (a) shared persona
def test_a_claude_code_adds_a_shared_persona_and_codex_recalls_it_from_its_own_server(fleet):
    servers = fleet.start_all()
    fleet.prov.grant_write("claude-code", space="ks-shared", basis="owner approved in chat")
    out = add(servers["claude-code"], "Nyan prefers terse answers and no emojis.", "persona", "shared", name="style")
    assert out["status"] == "SUCCESS" and out["result"] == "created" and out["ref"] == "mem://persona/style"
    for reader in ("codex", "hermes", "openclaw", "claude-code"):
        got = recall(servers[reader], "terse answers", memory_types=["persona"])
        assert got["status"] == "SUCCESS", (reader, got)
        assert got["hits"][0]["ref"] == "mem://persona/style" and got["hits"][0]["scope"] == "shared"
        assert "terse answers" in got["hits"][0]["text"]
    # the M6 read tool of ANOTHER agent's server sees the same shared unit through the same authorization
    legacy = servers["codex"].call("corpus_search", {"search_text": "terse", "knowledge_space_ids": ["ks-shared"]})
    assert legacy["isError"] is False and legacy["structuredContent"]["results"]
    # an update by name is a new version: the old words are no longer recalled
    upd = add(servers["claude-code"], "Nyan prefers detailed answers.", "persona", "shared", name="style")
    assert upd["result"] == "updated"
    assert recall(servers["codex"], "terse")["status"] == "EMPTY"
    assert "detailed answers" in texts(recall(servers["codex"], "detailed"))[0]


# ----------------------------------------------------------------------------------------------- (b) private + spoof
def test_b_private_notes_are_not_visible_to_other_agents_and_a_spoofed_identity_is_rejected(fleet):
    servers = fleet.start_all()
    add(servers["claude-code"], "claude-code private note about the vault of narwhals")
    assert recall(servers["claude-code"], "narwhals")["status"] == "SUCCESS"
    for other in ("codex", "hermes", "openclaw"):
        assert recall(servers[other], "narwhals")["status"] == "EMPTY"
    codex = servers["codex"]
    # spoofing the identity on every new tool: rejected, structured, isError
    for tool, args in (("memory_recall", {"query": "narwhals"}), ("memory_context", {}),
                       ("memory_add", {"text": "evil", "memory_type": "fact", "scope": "private"}),
                       ("memory_forget", {"source_id": "mem://fact/abcdef"})):
        result = codex.call(tool, {**args, "requesting_profile_id": "claude-code"})
        assert result["isError"] is True
        assert result["structuredContent"]["status"] == "DENIED"
        assert result["structuredContent"]["reason_code"] == "DENY_IDENTITY_PINNED"
        assert "narwhals" not in json.dumps(result)
    # ... and on the M6 read surface of the same server
    legacy = codex.call("corpus_search", {"search_text": "narwhals", "requesting_profile_id": "claude-code"})
    assert legacy["isError"] is True and legacy["structuredContent"]["status"] == "POLICY_DENIED"
    other = codex.call("corpus_search", {"search_text": "narwhals", "target_profile_ids": ["claude-code"]})
    assert other["isError"] is True
    assert "evil" not in " ".join(h["text"] for h in recall(servers["claude-code"], "evil").get("hits", []))
    assert [l["profile_id"] for l in registry_lines(fleet.root)] == ["claude-code"]


# ----------------------------------------------------------------------------------------------- (c) no grant
def test_c_a_shared_write_without_an_operator_grant_is_denied_and_stores_nothing(fleet):
    servers = fleet.start_all()
    for agent in AGENTS:
        out = servers[agent].call("memory_add", {"text": f"{agent} wants to share", "memory_type": "persona",
                                                 "scope": "shared"})
        env = out["structuredContent"]
        assert out["isError"] is True and env["status"] == "DENIED" and env["reason_code"] == "DENY_CROSS_PROFILE_WRITE"
        assert f"grant-write {agent} --space ks-shared" in env["operator_hint"]
    assert registry_lines(fleet.root) == []
    assert recall(servers["codex"], "wants to share")["status"] == "EMPTY"
    # the denial is audited on the canonical stream (decision metadata only, never content)
    stream = fleet.layout.memory_stream.read_text(encoding="utf-8")
    assert stream.count('"policy_decision"') >= 4 and "wants to share" not in stream


def test_c2_grant_and_revoke_take_effect_without_restarting_a_server(fleet):
    cc = fleet.start("claude-code")
    assert add(cc, "first shared try", "fact", "shared")["status"] == "DENIED"
    fleet.prov.grant_write("claude-code", space="ks-shared")
    assert add(cc, "second shared try about elk", "fact", "shared")["status"] == "SUCCESS"
    fleet.prov.revoke("claude-code", space="ks-shared", operation="WRITE")
    assert add(cc, "third shared try", "fact", "shared")["status"] == "DENIED"
    assert recall(cc, "elk")["status"] == "SUCCESS"  # reading it was never affected


# ----------------------------------------------------------------------------------------------- (d) secrets
def test_d_secret_text_is_rejected_and_never_reaches_blobs_db_or_streams(fleet):
    servers = fleet.start_all()
    fleet.prov.grant_write("codex", space="ks-shared")
    for agent, scope in (("claude-code", "private"), ("codex", "shared")):
        for secret in (SECRET_TOKEN, SECRET_ENV):
            result = servers[agent].call("memory_add", {"text": f"deploy with {secret} now",
                                                        "memory_type": "fact", "scope": scope})
            env = result["structuredContent"]
            assert result["isError"] is True and env["status"] == "REJECTED_SECRET" and env["rule_ids"], env
            assert secret not in json.dumps(result)
    (fleet.docs / "leak.md").write_text(f"# deploy\n\n{SECRET_TOKEN}\n", encoding="utf-8")
    ing = servers["claude-code"].call("memory_ingest", {"path": str(fleet.docs / "leak.md"), "memory_type": "file",
                                                        "scope": "private"})
    assert ing["structuredContent"]["status"] == "REJECTED_SECRET" and ing["isError"] is True
    assert registry_lines(fleet.root) == []
    for needle in (SECRET_TOKEN, "hunter2hunter2", SECRET_TOKEN[3:]):
        assert grep_tree(fleet.root, needle) == [], needle
    for agent in AGENTS:
        assert recall(servers[agent], "deploy")["status"] == "EMPTY"
    # a docx that carries the secret INSIDE its (compressed) XML is caught after extraction
    secret_docx = fx.make_docx([("p", f"notes {SECRET_ENV}")])
    (fleet.docs / "leak.docx").write_bytes(secret_docx)
    out = servers["claude-code"].env("memory_ingest", {"path": str(fleet.docs / "leak.docx"), "memory_type": "file",
                                                       "scope": "private"})
    assert out["status"] == "REJECTED_SECRET"
    assert registry_lines(fleet.root) == [] and grep_tree(fleet.root, "hunter2hunter2") == []


# ----------------------------------------------------------------------------------------------- (e) ingest
def _write_tree(docs):
    (docs / "notes.md").write_text("# Meeting\n\nThe zebra migration happens on Friday.\n", encoding="utf-8")
    (docs / "plan.docx").write_bytes(fx.make_docx([("h", 1, "Release plan"),
                                                   ("p", "Ship the okapi feature in March.")]))
    (docs / "table.xlsx").write_bytes(fx.make_xlsx([("Sheet1", [["animal", "count"], ["quokka", 7]])]))


def test_e_a_folder_of_docx_xlsx_and_md_is_ingested_under_the_allowlist_and_recalled_by_other_agents(fleet):
    _write_tree(fleet.docs)
    servers = fleet.start_all()
    fleet.prov.grant_write("claude-code", space="ks-shared")
    out = servers["claude-code"].env("memory_ingest", {"path": str(fleet.docs), "memory_type": "file",
                                                       "scope": "shared"})
    assert out["status"] == "SUCCESS" and out["counts"]["created"] == 3 and out["counts"]["rejected"] == 0
    for query, needle in (("zebra migration", "zebra"), ("okapi feature", "okapi"), ("quokka", "quokka")):
        for reader in ("codex", "openclaw"):
            got = recall(servers[reader], query)
            assert got["status"] == "SUCCESS" and needle in got["hits"][0]["text"].lower(), (reader, query, got)
            assert got["hits"][0]["type"] == "file" and got["hits"][0]["scope"] == "shared"
    again = servers["claude-code"].env("memory_ingest", {"path": str(fleet.docs), "memory_type": "file",
                                                         "scope": "shared"})
    assert again["counts"]["unchanged"] == 3 and again["counts"]["created"] == 0


def test_e2_paths_outside_the_allowlist_and_symlinks_are_refused(fleet):
    _write_tree(fleet.docs)
    outside = fleet.tmp / "outside"
    outside.mkdir()
    (outside / "vault.txt").write_text("the vault code is orchid", encoding="utf-8")
    (fleet.docs / "sneaky.txt").symlink_to(outside / "vault.txt")
    (fleet.docs / "sneaky-dir").symlink_to(outside, target_is_directory=True)
    cc = fleet.start("claude-code")
    for target in (outside, outside / "vault.txt", "/etc/passwd", "/", str(fleet.docs) + "/../outside"):
        result = cc.call("memory_ingest", {"path": str(target), "memory_type": "file", "scope": "private"})
        assert result["isError"] is True and result["structuredContent"]["status"] == "DENIED", target
        assert result["structuredContent"]["reason_code"] == "DENY_PATH_OUTSIDE_ALLOWLIST"
        assert str(fleet.tmp) not in json.dumps(result)
    for target in (fleet.docs / "sneaky.txt", fleet.docs / "sneaky-dir", fleet.docs / "sneaky-dir" / "vault.txt"):
        result = cc.call("memory_ingest", {"path": str(target), "memory_type": "file", "scope": "private"})
        assert result["isError"] is True and result["structuredContent"]["reason_code"] == "DENY_SYMLINK", target
    assert registry_lines(fleet.root) == []
    ok = cc.env("memory_ingest", {"path": str(fleet.docs), "memory_type": "file", "scope": "private"})
    assert ok["status"] == "SUCCESS" and ok["counts"]["created"] == 3  # symlinks inside a walked folder are skipped
    assert recall(cc, "orchid")["status"] == "EMPTY" and grep_tree(fleet.root, "orchid") == []


def test_e3_a_server_without_allow_roots_cannot_ingest_at_all(fleet):
    _write_tree(fleet.docs)
    cc = fleet.start("claude-code", roots=[])
    out = cc.call("memory_ingest", {"path": str(fleet.docs), "memory_type": "file", "scope": "private"})
    assert out["isError"] is True and out["structuredContent"]["reason_code"] == "DENY_NO_ALLOWED_ROOTS"


# ----------------------------------------------------------------------------------------------- (f) forget
def test_f_forget_removes_a_shared_memory_from_the_recall_of_every_agent(fleet):
    servers = fleet.start_all()
    fleet.prov.grant_write("claude-code", space="ks-shared")
    added = add(servers["claude-code"], "The staging password policy lives in the wiki about okapis.", "fact", "shared")
    for agent in AGENTS:
        assert recall(servers[agent], "okapis")["status"] == "SUCCESS", agent
    # a reader without the write approval cannot forget it
    denied = servers["codex"].call("memory_forget", {"source_id": added["source_id"]})
    assert denied["isError"] is True and denied["structuredContent"]["status"] == "DENIED"
    assert recall(servers["codex"], "okapis")["status"] == "SUCCESS"
    gone = servers["claude-code"].env("memory_forget", {"source_id": added["source_id"]})
    assert gone["status"] == "SUCCESS" and gone["result"] == "forgotten"
    for agent in AGENTS:
        assert recall(servers[agent], "okapis")["status"] == "EMPTY", agent
    again = servers["claude-code"].env("memory_forget", {"source_id": added["ref"]})
    assert again["status"] == "SUCCESS" and again["result"] == "already_forgotten"
    assert servers["codex"].call("memory_forget", {"source_id": "0" * 16})["structuredContent"]["status"] == "NOT_FOUND"
    # the raw record is kept (append-only canonical corpus), only recall/context hide it
    assert [l["lifecycle_status"] for l in registry_lines(fleet.root)] == ["observed", "deleted"]


# ----------------------------------------------------------------------------------------------- (g) concurrency
N_PER_AGENT = int(os.environ.get("T6B_CONCURRENT_N", "20"))  # raise it to stress (the closure used 40)
_KEY = {"claude-code": "cca", "codex": "cdx", "hermes": "hrm", "openclaw": "ocl"}


def _hammer(proc, agent, barrier, results):
    """One agent's server process: N private + N shared adds, each followed by a read of the private item (reads
    run while the three other servers are writing)."""
    key = _KEY[agent]
    try:
        barrier.wait(60)
        for i in range(N_PER_AGENT):
            for scope in ("private", "shared"):
                out = proc.call("memory_add", {"text": f"{key}{scope}{i:03d}marker concurrent note number {i}",
                                               "memory_type": "fact", "scope": scope})
                results.append((agent, scope, i, out["structuredContent"]["status"], out["structuredContent"].get("result")))
            seen = proc.call("memory_recall", {"query": f"{key}private{i:03d}marker"})["structuredContent"]["status"]
            results.append((agent, "read", i, seen, "created"))
    except BaseException as exc:  # noqa: BLE001 - surfaced by the assertions below
        results.append((agent, "crash", -1, repr(exc), None))


@pytest.mark.parametrize("round_", range(2))
def test_g_four_server_processes_write_concurrently_with_no_loss_and_a_correct_registry(fleet, round_):
    servers = fleet.start_all()
    for agent in AGENTS:
        fleet.prov.grant_write(agent, space="ks-shared")
    barrier = threading.Barrier(len(AGENTS))
    results: list = []
    threads = [threading.Thread(target=_hammer, args=(servers[a], a, barrier, results)) for a in AGENTS]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=600)
        assert not t.is_alive()
    assert len(results) == len(AGENTS) * N_PER_AGENT * 3, [r for r in results if r[1] == "crash"] or len(results)
    assert all(r[3] == "SUCCESS" and r[4] == "created" for r in results), [r for r in results if r[3] != "SUCCESS"]
    lines = registry_lines(fleet.root)
    assert len(lines) == len(AGENTS) * N_PER_AGENT * 2
    assert len({(l["external_ref"], l["profile_id"], l["knowledge_space_id"]) for l in lines}) == len(lines)
    conn = sqlite3.connect(fleet.layout.derived_db)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM zm_corpus_sources").fetchone()[0] == len(lines)
        assert conn.execute("SELECT COUNT(*) FROM zm_corpus_units").fetchone()[0] == len(lines)
        assert conn.execute("SELECT COUNT(*) FROM zm_corpus_fts").fetchone()[0] == len(lines)
    finally:
        conn.close()
    # every shared item is recallable by an agent that did NOT write it; every private item by its writer only
    for agent in AGENTS:
        reader = servers[AGENTS[(AGENTS.index(agent) + 1) % len(AGENTS)]]
        for i in range(N_PER_AGENT):
            got = recall(reader, f"{_KEY[agent]}shared{i:03d}marker")
            assert got["status"] == "SUCCESS" and got["hits"][0]["scope"] == "shared", (agent, i, got)
            mine = recall(servers[agent], f"{_KEY[agent]}private{i:03d}marker")
            assert mine["status"] == "SUCCESS" and mine["hits"][0]["scope"] == "private", (agent, i, mine)
            leak = recall(reader, f"{_KEY[agent]}private{i:03d}marker")
            assert leak["status"] == "EMPTY", (agent, i, leak)


# ----------------------------------------------------------------------------------------------- (h) context
def test_h_the_context_bundle_has_persona_and_workflow_and_respects_max_chars(fleet):
    servers = fleet.start_all()
    fleet.prov.grant_write("claude-code", space="ks-shared")
    fleet.prov.grant_write("claude-code", project="zero-mem")
    fleet.prov.grant_read("codex", project="zero-mem")
    cc, codex = servers["claude-code"], servers["codex"]
    add(cc, "The user prefers terse answers and no emojis.", "persona", "shared", name="style")
    add(cc, "Always run pytest before every commit.", "workflow", "shared", name="commit")
    add(cc, "---\nname: deploy\ndescription: Deploy the service to staging\n---\nRun the script.", "skill", "shared",
        name="deploy")
    add(cc, "Fixed the flaky lock test", "devlog", "project", project_id="zero-mem")
    add(cc, "claude private fact that codex must not see in its bundle: salamander", "fact", "private")
    bundle = codex.env("memory_context", {"max_chars": 2000, "project_id": "zero-mem"})
    assert bundle["status"] == "SUCCESS" and bundle["chars"] <= 2000 == bundle["max_chars"]
    text = bundle["text"]
    assert "terse answers" in text and "pytest before every commit" in text
    assert "deploy" in text and "flaky lock test" in text and "salamander" not in text
    assert {"Persona", "Workflow", "Skills", "Recent devlog"} <= set(bundle["sections"])
    raw = codex.call("memory_context", {"max_chars": 2000, "project_id": "zero-mem"})
    assert raw["content"][0]["text"] == text
    for limit in (200, 300, 700, 1200, 4000):
        small = codex.env("memory_context", {"max_chars": limit})
        assert small["chars"] <= limit and "terse answers" in small["text"], limit
    assert codex.env("memory_context", {"max_chars": 4001})["status"] == "INVALID"
    assert servers["hermes"].env("memory_context")["text"].startswith("## Persona")


# ----------------------------------------------------------------------------------------------- robustness
def test_servers_keep_serving_after_bad_calls_and_never_leak_paths(fleet):
    cc = fleet.start("claude-code")
    junk = [("memory_add", {}), ("memory_add", {"text": 5}), ("memory_recall", {"query": None}),
            ("memory_ingest", {"path": "/", "memory_type": "file", "scope": "private"}),
            ("memory_forget", {"source_id": "../../etc/passwd"}), ("memory_context", {"max_chars": "lots"}),
            ("memory_add", {"text": "x", "memory_type": "fact", "scope": "private", "extra": {"a": 1}})]
    for tool, args in junk:
        result = cc.call(tool, args)
        assert result["isError"] is True
        assert str(fleet.tmp) not in json.dumps(result) and "Traceback" not in json.dumps(result)
    assert add(cc, "still alive about lapwings")["status"] == "SUCCESS"
    assert recall(cc, "lapwings")["status"] == "SUCCESS"
    err = cc.close()
    assert "Traceback" not in err
