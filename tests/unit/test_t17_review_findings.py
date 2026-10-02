"""T17 - PR #4 review findings: learned-type write split, approval atomicity, learner-state lock, expiry provenance."""
from __future__ import annotations

import multiprocessing

from tests.unit import _t17_workers as W


# ================================================================ finding 3: learner state lock
def test_learner_state_survives_concurrent_writers(tmp_path):
    from zero_mem import learner

    ctx = multiprocessing.get_context("spawn")
    for round_no in range(4):
        path = tmp_path / f"state-{round_no}.json"
        barrier, out = ctx.Barrier(4), ctx.Queue()
        procs = [ctx.Process(target=W.save_keys, args=(str(path), w, 25, barrier, out)) for w in range(4)]
        for p in procs:
            p.start()
        results = [out.get(timeout=120) for _ in procs]
        for p in procs:
            p.join(60)
        assert all(r[0] == "ok" for r in results), results
        keys = set(learner._load_state(path))
        assert keys == {f"w{w}#{i}" for w in range(4) for i in range(25)}, round_no


# ================================================================ shared harness (same style as T14)
import json  # noqa: E402

import pytest  # noqa: E402

from src.integration.m6w import build_tool_set  # noqa: E402
from tests.unit.test_t14_proposals import Harness  # noqa: E402
from zero_mem import cli, learning  # noqa: E402
from zero_mem.provisioning import ProvisioningError  # noqa: E402

LEARNED = ("rule", "decision", "gotcha")


@pytest.fixture
def h(tmp_path):
    harness = Harness(tmp_path)
    yield harness
    harness.env.close()


# ================================================================ finding 1: agents cannot write learned types directly
@pytest.mark.parametrize("mtype", LEARNED)
@pytest.mark.parametrize("scope", ["private", "shared"])
def test_agent_add_refuses_learned_types_and_nothing_is_recallable(h, mtype, scope):
    m = h.agent("codex", write_shared=True)
    res = m.add("Always run the zebra checklist.", mtype, name="zebra", scope=scope)
    assert res.status == "denied" and res.reason == "learned_type_requires_proposal" and not res.ok
    assert not m.recall("zebra").hits and "zebra" not in m.context().text
    assert h.sources(f"mem://{mtype}/zebra") == []


def test_agent_add_project_scope_and_ingest_refuse_learned_types(h, tmp_path):
    m = h.agent("codex", write_projects=["p1"])
    assert m.add("x y z", "rule", scope="project", project_id="p1").reason == "learned_type_requires_proposal"
    note = tmp_path / "note.md"
    note.write_text("Always feed the zebra.", encoding="utf-8")
    for mtype in LEARNED:
        report = m.ingest(note, memory_type=mtype)
        assert report.status == "denied" and report.reason == "learned_type_requires_proposal"
        report = m.ingest(b"Always feed the zebra.", "n.md", memory_type=mtype)
        assert report.status == "denied"
    assert not m.recall("zebra").hits
    assert m.add("a plain fact", "fact").ok and m.ingest(note, memory_type="fact").status in (None, "ok")


@pytest.mark.parametrize("mtype", LEARNED)
def test_mcp_memory_add_and_ingest_refuse_learned_types(h, tmp_path, mtype):
    note = tmp_path / "note.md"
    note.write_text("Always feed the zebra.", encoding="utf-8")
    ts = build_tool_set(profile_id="codex", layout=h.env.layout, enable_write=True, allow_roots=[tmp_path])
    schemas = {t["name"]: t for t in ts.schemas()}
    for tool in ("memory_add", "memory_ingest"):
        assert mtype not in schemas[tool]["inputSchema"]["properties"]["memory_type"]["enum"]
    out = ts.call("memory_add", {"text": "Always feed the zebra.", "memory_type": mtype, "scope": "private"})
    assert out["isError"] is True and out["structuredContent"]["status"] == "INVALID"
    out2 = ts.call("memory_ingest", {"path": str(note), "memory_type": mtype, "scope": "private"})
    assert out2["isError"] is True and out2["structuredContent"]["status"] == "INVALID"
    assert h.env.registry_lines() == []


def test_library_layer_below_the_schema_also_refuses(h):
    """Even without schema validation (direct toolset handler) the library refuses and points to memory_propose."""
    ts = build_tool_set(profile_id="codex", layout=h.env.layout, enable_write=True, allow_roots=[])
    out = ts._add({"text": "Always feed the zebra.", "memory_type": "rule", "scope": "private"})
    out = out["structuredContent"]
    assert out["status"] == "DENIED" and out["reason_code"] == "learned_type_requires_proposal"
    assert "memory_propose" in out["message"]
    assert h.env.registry_lines() == []


def test_owner_paths_still_write_learned_types(h, tmp_path, monkeypatch):
    m = h.agent("codex", write_shared=True)
    res = m._owner_add("Always run the zebra checklist.", "rule", name="zebra", scope="shared")
    assert res.status == "created"
    assert [x.external_ref for x in m.recall("zebra").hits] == ["mem://rule/zebra"]
    # a Reviewer approval commits through the same write path
    p = m.propose("Never feed the lemurs.", "gotcha", name="lem")
    assert h.review().approve(p.proposal_id).status == "approved"
    assert m.recall("lemurs").hits
    # the owner CLI
    from tests.unit.t6b_helpers import apply_env

    apply_env(monkeypatch, tmp_path / "cli")
    monkeypatch.setenv("ZERO_MEM_SETTINGS", str(tmp_path / "cli" / "cfg" / "settings.toml"))
    assert cli.main(["setup"]) == 0
    assert cli.main(["--profile", "claude-code", "add", "Owner rule about otters.", "--type", "decision",
                     "--name", "otters"]) == 0
    assert cli.main(["--profile", "claude-code", "search", "otters", "--json"]) == 0


# ================================================================ finding 2: approval event append failure
def _fail_approve_append(monkeypatch, times=1):
    real = learning.append_canonical_event
    state = {"left": times}

    def flaky(stream, event):
        if event.get("m4", {}).get("op") == "approve" and state["left"] > 0:
            state["left"] -= 1
            raise ProvisioningError("stream_unwritable", "simulated")
        return real(stream, event)

    monkeypatch.setattr(learning, "append_canonical_event", flaky)


def test_failed_approval_record_leaves_no_active_source_and_retry_succeeds_once(h, monkeypatch):
    m = h.agent("codex")
    p = m.propose("Never feed the zebras after midnight.", "rule", name="zebra", scope="private")
    _fail_approve_append(monkeypatch)
    res = h.review().approve(p.proposal_id)
    assert res.status == "error"
    assert m.proposal(p.proposal_id)["status"] == "pending"
    assert not m.recall("zebras").hits and "zebras" not in m.context().text  # no active source without approval
    ok = h.review().approve(p.proposal_id)  # the stream works again
    assert ok.status == "approved" and ok.write_status == "created"
    assert [x.external_ref for x in m.recall("zebras").hits] == ["mem://rule/zebra"]
    assert [e["m4"]["op"] for e in h.lp_events()].count("approve") == 1
    assert h.review().approve(p.proposal_id).status == "not_pending"  # not double-applied
    assert h.review().list("approved")[0]["version"] == ok.version


def test_failed_approval_of_a_new_version_restores_the_previous_text(h, monkeypatch):
    m = h.agent("codex")
    first = m.propose("Deploys happen on Tuesdays.", "decision", name="deploys", scope="private")
    assert h.review().approve(first.proposal_id).status == "approved"
    second = m.propose("Deploys happen on Thursdays.", "decision", name="deploys", scope="private")
    _fail_approve_append(monkeypatch)
    assert h.review().approve(second.proposal_id).status == "error"
    assert [x.text for x in m.recall("deploys", memory_types=["decision"]).hits] == ["Deploys happen on Tuesdays."]
    assert m.proposal(first.proposal_id)["status"] == "approved"
    retry = h.review().approve(second.proposal_id)
    assert retry.status == "approved"
    assert [x.text for x in m.recall("deploys", memory_types=["decision"]).hits] == ["Deploys happen on Thursdays."]


def test_retry_after_a_crash_between_write_and_record_does_not_create_a_second_version(h, monkeypatch):
    """No compensation ran (e.g. the process died): the retry finds the identical version, writes nothing new."""
    m = h.agent("codex")
    p = m.propose("Always sharpen the pencils.", "rule", name="pencils", scope="private")
    monkeypatch.setattr("zero_mem.memory.Memory._undo_approved_write", lambda *a, **k: False)
    _fail_approve_append(monkeypatch)
    res = h.review().approve(p.proposal_id)
    assert res.status == "error" and res.reason == "approval_not_recorded"
    assert m.recall("pencils").hits  # reported as an unresolved state, never silent
    ok = h.review().approve(p.proposal_id)
    assert ok.status == "approved" and ok.write_status == "unchanged"
    assert len(h.sources("mem://rule/pencils")) == 1


# ================================================================ finding 4: expiry follows the current version
def test_owner_replacement_of_an_approved_name_is_not_expired_and_reapproval_restarts_the_clock(h):
    h.set("learning.active_ttl_days", "30")
    m = h.agent("codex")
    p = m.propose("Learned rule about narwhals.", "rule", name="nar", scope="private")
    h.review().approve(p.proposal_id)
    assert m.recall("narwhals").hits
    h.day("2026-11-15T09:00:00+00:00")  # 45 days later: expires
    assert not m.recall("narwhals").hits
    owner = m._owner_add("Owner rewrote the narwhal rule.", "rule", name="nar", scope="private")
    assert owner.status == "updated"
    assert [x.text for x in m.recall("narwhals").hits] == ["Owner rewrote the narwhal rule."]
    assert "Owner rewrote" in m.context(max_chars=2000).text
    assert "active_expired" not in h.review().list("approved")[0]
    assert h.review().expire().detail["active_hidden"] == []
    # a re-approval is approved again: its own clock starts at the new approval
    p2 = m.propose("Learned rule about narwhals, v3.", "rule", name="nar", scope="private")
    h.review().approve(p2.proposal_id)
    assert m.recall("narwhals").hits
    h.day("2026-12-01T09:00:00+00:00")  # 16 days after the re-approval
    assert m.recall("narwhals").hits
    h.day("2027-01-10T09:00:00+00:00")  # 56 days after
    assert not m.recall("narwhals").hits
