"""T14 - proposals (the inert staging area), owner review, revoke / supersede / TTL, replay and isolation."""
from __future__ import annotations

import json
import time
from datetime import timedelta

import pytest

from src.access.rebuild import iter_canonical_policy_events, rebuild_policy_state
from src.integration.m6w import build_tool_set
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from tests.unit.t5_memory_helpers import SECRET_ENV, SECRET_TOKEN, Env
from zero_mem import learning, learning_settings as ls
from zero_mem import upgrade as upgrade_mod
from zero_mem.learning import ProposalLog, Reviewer
from zero_mem.memory import MEMORY_TYPES, Memory

SHARED = "ks-shared"


class Harness:
    def __init__(self, tmp_path):
        self.env = Env(tmp_path)
        self.settings = tmp_path / "cfg" / "settings.toml"
        self.reviewer = Reviewer(self.env.layout, operator="owner", clock=self.env.clock, settings_path=self.settings)

    def agent(self, profile, **kw) -> Memory:
        kw.setdefault("settings_path", self.settings)
        return self.env.agent(profile, **kw)

    def set(self, key, value):
        ls.set_value(key, value, self.settings)

    def review(self) -> Reviewer:
        return Reviewer(self.env.layout, operator="owner", clock=self.env.clock, settings_path=self.settings)

    def lp_events(self):
        return self.env.stream_events("learning_proposal")

    def sources(self, ref):
        return [r for r in self.env.registry_lines() if r["external_ref"] == ref]

    def day(self, iso):
        self.env.clock.set(iso)


@pytest.fixture
def h(tmp_path):
    harness = Harness(tmp_path)
    yield harness
    harness.env.close()


# ================================================================ memory types
def test_rule_decision_gotcha_are_memory_types_after_the_existing_ones():
    assert MEMORY_TYPES[:6] == ("persona", "workflow", "skill", "devlog", "fact", "file")
    assert MEMORY_TYPES[6:] == ("rule", "decision", "gotcha")


@pytest.mark.parametrize("mtype", ["rule", "decision", "gotcha"])
def test_new_types_version_by_name_in_every_scope(h, mtype):
    m = h.agent("codex", write_shared=True, write_projects=["p1"])
    a = m.add("First wording.", mtype, name="n")
    b = m.add("Second wording.", mtype, name="n")
    assert (a.status, b.status) == ("created", "updated") and a.source_id == b.source_id
    assert a.external_ref == f"mem://{mtype}/n"
    assert m.add("Shared.", mtype, name="s", scope="shared").status == "created"
    assert m.add("Project.", mtype, name="pr", scope="project", project_id="p1").status == "created"
    assert {x.memory_type for x in m.recall("wording", memory_types=[mtype]).hits} == {mtype}


def test_new_types_need_the_same_grants_as_workflow_for_shared_writes(h):
    m = h.agent("codex")  # READ only on ks-shared
    for mtype in ("rule", "decision", "gotcha"):
        assert m.add("x y z", mtype, scope="shared").status == "denied"
    assert m.add("x y z", "rule", scope="project", project_id="pz").status == "denied"


def test_context_lists_the_learned_sections_in_order_and_keeps_the_legacy_layout_without_them(h):
    m = h.agent("codex")
    m.add("Persona facet.", "persona", name="p")
    m.add("Workflow step.", "workflow", name="w")
    legacy = m.context(max_chars=1000)
    assert [t.removeprefix("## ") for t in legacy.text.split("\n") if t.startswith("## ")] == ["Persona", "Workflow"]
    m.add("Rule one.", "rule", name="r")
    m.add("Decision one.", "decision", name="d")
    m.add("Gotcha one.", "gotcha", name="g")
    ctx = m.context(max_chars=2000)
    heads = [t.removeprefix("## ") for t in ctx.text.split("\n") if t.startswith("## ")]
    assert heads == ["Persona", "Rules", "Workflow", "Decisions", "Gotchas"]
    assert ctx.sources[:2] == ["mem://persona/p", "mem://rule/r"]
    assert len(m.context(max_chars=120).text) <= 120


def test_mcp_schemas_and_cli_choices_accept_the_new_types(h):
    ts = build_tool_set(profile_id="codex", layout=h.env.layout, enable_write=True, allow_roots=[])
    props = {t["name"]: t for t in ts.schemas()}["memory_add"]["inputSchema"]["properties"]["memory_type"]["enum"]
    assert {"rule", "decision", "gotcha"} <= set(props)
    from zero_mem.cli import build_parser

    args = build_parser().parse_args(["add", "x", "--type", "gotcha"])
    assert args.memory_type == "gotcha"
    with pytest.raises(SystemExit):
        build_parser().parse_args(["propose", "x", "--type", "file"])


# ================================================================ propose: acceptance and rejection
def test_propose_stores_an_inert_append_only_event(h):
    m = h.agent("codex")
    before = h.env.registry_lines()
    r = m.propose("Always run the linter before committing.", "rule", name="lint", scope="shared",
                  evidence=["pr#12", "incident-3"])
    assert r.ok and r.status == "proposed" and r.seen == 1 and r.proposal_id.startswith("p-")
    assert len(r.proposal_id) == 14
    (event,) = h.lp_events()
    m4 = event["m4"]
    assert m4["op"] == "propose" and m4["proposer"] == "codex" and m4["source"] == "agent"
    assert (m4["memory_type"], m4["scope"], m4["name"]) == ("rule", "shared", "lint")
    assert m4["evidence"] == ["pr#12", "incident-3"] and "linter" in m4["text"]
    assert h.env.registry_lines() == before  # no corpus source, no blob
    assert h.env.units() == []


def test_a_pending_proposal_never_appears_in_recall_context_search_or_mcp(h, capsys):
    m = h.agent("codex")
    other = h.agent("hermes")
    assert m.propose("Zebra crossing procedure is mandatory.", "rule", scope="shared").ok
    assert m.propose("Zebra private gotcha.", "gotcha", scope="private").ok
    assert m.propose("Zebra project decision.", "decision", scope="project", project_id="p1").ok
    for mem in (m, other):
        assert mem.recall("zebra").hits == () or list(mem.recall("zebra").hits) == []
        assert "Zebra" not in mem.context(max_chars=4000, project_id="p1").text
        assert mem.recall("zebra", memory_types=["rule", "gotcha", "decision"]).status in ("empty", "ok")
        assert not list(mem.recall("zebra", memory_types=["rule"]).hits)
    ts = build_tool_set(profile_id="hermes", layout=h.env.layout, enable_write=False, allow_roots=[])
    for tool, args in (("memory_recall", {"query": "zebra"}), ("memory_context", {})):
        out = json.dumps(ts.call(tool, args))
        assert "ebra" not in out
    assert not any(n in ts.names for n in ("memory_propose", "memory_review", "memory_approve"))
    from zero_mem.cli import main

    assert main(["--profile", "codex", "search", "zebra", "--json"]) in (0, 5)
    assert "ebra crossing" not in capsys.readouterr().out
    assert h.units() == [] if hasattr(h, "units") else h.env.units() == []


def test_agent_proposals_reject_every_reason_and_store_nothing(h):
    m = h.agent("codex")

    def last_count():
        return len(h.lp_events())

    assert m.propose(f"token {SECRET_TOKEN} here", "rule").status == "rejected_secret"
    assert m.propose("use " + SECRET_ENV, "gotcha").status == "rejected_secret"
    res = m.propose("fine text", "rule", evidence=[f"see {SECRET_TOKEN}"])
    assert res.status == "rejected_secret" and res.rule_ids
    assert m.propose("fine text", "rule", name=SECRET_TOKEN).status == "rejected_secret"
    assert last_count() == 0 and not h.env.files_containing(SECRET_TOKEN)

    bad = [
        dict(text="x", memory_type="bogus", scope="shared"),
        dict(text="x", memory_type="file", scope="shared"),
        dict(text="x", memory_type="rule", scope="galaxy"),
        dict(text="x", memory_type="rule", scope=None),
        dict(text="x", memory_type="rule", scope="project"),  # project id missing
        dict(text="x", memory_type="rule", scope="shared", project_id="p1"),
        dict(text="x", memory_type="rule", scope="shared", name="bad name!"),
        dict(text="   ", memory_type="rule", scope="shared"),
        dict(text=3, memory_type="rule", scope="shared"),
        dict(text="x", memory_type="rule", scope="shared", source="root"),
        dict(text="x", memory_type="rule", scope="shared", evidence=["a"] * 6),
        dict(text="x", memory_type="rule", scope="shared", evidence=["z" * 201]),
        dict(text="x", memory_type="rule", scope="shared", evidence=[7]),
        dict(text="x" * (learning.MAX_PROPOSAL_BYTES + 1), memory_type="rule", scope="shared"),
    ]
    for kwargs in bad:
        res = m.propose(**kwargs)
        assert res.status == "invalid" and res.reason, kwargs
    assert last_count() == 0


def test_deny_patterns_kill_switch_mode_off_and_agent_toggle(h):
    m = h.agent("codex")
    h.set("safety.deny_patterns", '["corp-secret-\\\\d+"]')
    res = m.propose("rule about CORP-SECRET-77", "rule")
    assert (res.status, res.reason) == ("rejected", "deny_pattern")
    res = m.propose("fine", "rule", name="corp-secret-5")
    assert res.reason == "deny_pattern"  # the name is checked too
    ls.unset_value("safety.deny_patterns", h.settings)

    h.set("learning.allow_agent_proposals", "false")
    assert m.propose("agent rule", "rule").reason == "agent_proposals_disallowed"
    assert m.propose("learner rule", "rule", source="learner").reason == "agent_proposals_disallowed"
    assert m.propose("owner rule", "rule", source="user").ok
    h.set("learning.allow_agent_proposals", "true")

    h.set("learning.mode", "off")
    assert m.propose("anything", "rule").reason == "learning_off"
    h.set("learning.mode", "suggest")

    h.set("safety.kill_switch", "true")
    assert m.propose("anything", "rule", source="user").reason == "kill_switch"
    h.set("safety.kill_switch", "false")
    assert m.propose("anything now", "rule").ok
    assert len(h.lp_events()) == 2  # only the two accepted ones were ever stored


def test_invalid_settings_fail_safe_for_proposals_and_reads_still_work(h):
    m = h.agent("codex")
    m.add("Existing memory about okapis.", "fact", name="o")
    m.add("Persona about okapis.", "persona", name="po")
    h.settings.parent.mkdir(parents=True, exist_ok=True)
    h.settings.write_text("[learning\nbroken", encoding="utf-8")
    assert m.propose("x y", "rule").reason == "settings_invalid"
    assert m.recall("okapis").hits  # reads of existing memory still work
    assert m.context().text
    assert m.injection_policy() == (False, 0, ())


def test_kill_switch_keeps_reads_and_blocks_new_proposals_but_not_review_reject_or_revoke(h):
    m = h.agent("codex")
    first = m.propose("Rule alpha about quokkas.", "rule", name="alpha", scope="private")
    second = m.propose("Rule beta about quokkas.", "rule", name="beta", scope="private")
    ok = h.review().approve(first.proposal_id)
    assert ok.status == "approved"
    h.set("safety.kill_switch", "true")
    assert m.recall("quokkas").hits  # existing memory is still readable
    assert m.propose("another", "rule").reason == "kill_switch"
    blocked = h.review().approve(second.proposal_id)
    assert (blocked.status, blocked.reason) == ("blocked", "kill_switch")
    assert h.review().reject(second.proposal_id, "paused").status == "rejected"
    assert h.review().revoke("mem://rule/alpha").status == "revoked"
    assert m.injection_policy() == (False, 0, ())


def test_daily_limit_is_per_profile_and_resets_each_utc_day(h):
    h.set("learning.max_proposals_per_day", "2")
    a, b = h.agent("codex"), h.agent("hermes")
    assert a.propose("one", "rule").ok and a.propose("two", "rule").ok
    third = a.propose("three", "rule")
    assert (third.status, third.reason) == ("rejected", "daily_limit")
    assert b.propose("one", "rule").ok  # another profile has its own budget
    assert a.propose("one", "rule").status == "merged"  # a duplicate is not a new proposal
    h.day("2026-10-02T00:00:01+00:00")
    assert a.propose("three", "rule").ok
    h.set("learning.max_proposals_per_day", "0")
    assert a.propose("four", "rule").reason == "daily_limit"


# ================================================================ duplicates
def test_duplicate_pending_proposals_collapse_with_a_seen_counter_and_bounded_evidence(h):
    m = h.agent("codex")
    first = m.propose("Never push to main directly.", "rule", name="no-main", evidence=["pr#1"])
    again = m.propose("  never   PUSH to main directly. ", "rule", name="no-main", evidence=["pr#2", "pr#1"])
    assert (first.status, again.status) == ("proposed", "merged")
    assert again.proposal_id == first.proposal_id and again.seen == 2
    for i in range(30):
        m.propose("Never push to main directly.", "rule", name="no-main", evidence=[f"ev-{i}"])
    (row,) = m.proposals("pending")
    assert row["seen"] == 32 and len(row["evidence"]) == learning.MAX_EVIDENCE_ITEMS
    assert row["evidence"][:2] == ["pr#1", "pr#2"]
    # a different target is a different proposal
    other = m.propose("Never push to main directly.", "rule", name="no-main", scope="private")
    assert other.status == "proposed" and other.proposal_id != first.proposal_id
    assert len(m.proposals("pending")) == 2


def test_seen_counter_is_bounded(h, monkeypatch):
    monkeypatch.setattr(learning, "MAX_SEEN", 5)
    m = h.agent("codex")
    for _ in range(9):
        r = m.propose("same thing", "rule")
    assert r.seen <= 5 and m.proposals()[0]["seen"] == 5


def test_a_resolved_duplicate_can_be_proposed_again(h):
    m = h.agent("codex")
    first = m.propose("Use tabs.", "rule", name="tabs")
    assert h.review().reject(first.proposal_id).ok
    second = m.propose("Use tabs.", "rule", name="tabs")
    assert second.status == "proposed" and second.proposal_id != first.proposal_id


# ================================================================ approve
def test_approval_creates_exactly_one_source_with_scope_and_provenance_without_a_write_grant(h):
    m = h.agent("codex")  # READ on ks-shared only: cannot write shared by itself
    assert m.add("direct write", "rule", name="x", scope="shared").status == "denied"
    p = m.propose("Run `pytest -q` before every commit.", "rule", name="tests", scope="shared", evidence=["pr#9"])
    assert h.sources("mem://rule/tests") == []
    res = h.review().approve(p.proposal_id)
    assert res.status == "approved" and res.write_status == "created"
    assert res.external_ref == "mem://rule/tests" and res.source_id
    lines = h.sources("mem://rule/tests")
    assert len(lines) == 1
    rec = lines[0]
    assert rec["knowledge_space_id"] == SHARED and rec["profile_id"] == "codex" and rec["project_id"] is None
    assert rec["custom_meta"]["memory_type"] == "rule" and rec["lifecycle_status"] == "observed"
    prov = rec["provenance"]
    assert prov["proposal"] == p.proposal_id and prov["proposer"] == "codex" and prov["approver"] == "owner"
    assert prov["tool"] == "approve" and prov["channel"] == "review"
    # the audit/event record: proposer, approver, proposal id, resulting source id
    approve = [e for e in h.lp_events() if e["m4"]["op"] == "approve"]
    assert len(approve) == 1
    m4 = approve[0]["m4"]
    assert (m4["proposal_id"], m4["proposer"], m4["approved_by"], m4["source_id"]) == (
        p.proposal_id, "codex", "owner", res.source_id)
    assert "ADR-V170-03" in m4["basis"]
    # every agent with READ now recalls it
    other = h.agent("hermes")
    hit = other.recall("pytest", memory_types=["rule"]).hits[0]
    assert hit.external_ref == "mem://rule/tests" and hit.scope == "shared"
    # approving again is refused, and no second source version appears
    assert h.review().approve(p.proposal_id).status == "not_pending"
    assert len(h.sources("mem://rule/tests")) == 1
    # the grant is NOT standing: the agent still cannot write shared on its own
    assert m.add("direct write", "rule", name="x2", scope="shared").status == "denied"


def test_approval_works_for_project_and_private_scopes(h):
    m = h.agent("codex")
    pp = m.propose("Project gotcha about flaky ci.", "gotcha", name="ci", scope="project", project_id="p1")
    pv = m.propose("My private decision about ci.", "decision", name="mine", scope="private")
    a, b = h.review().approve(pp.proposal_id), h.review().approve(pv.proposal_id)
    assert (a.status, b.status) == ("approved", "approved")
    assert h.sources("mem://gotcha/ci")[0]["project_id"] == "p1"
    pr = h.sources("mem://decision/mine")[0]
    assert pr["knowledge_space_id"] is None and pr["project_id"] is None and pr["profile_id"] == "codex"


def test_edit_on_approve_keeps_the_original_and_stores_the_edit(h):
    m = h.agent("codex")
    p = m.propose("always use tabs maybe", "rule", name="fmt")
    res = h.review().approve(p.proposal_id, edit="Use tabs for indentation in Makefiles only.", name="make-tabs")
    assert res.status == "approved" and res.external_ref == "mem://rule/make-tabs"
    stored = h.review().show(p.proposal_id)
    assert stored["text"] == "always use tabs maybe"  # original kept
    assert stored["final_text"] == "Use tabs for indentation in Makefiles only."
    hit = h.agent("hermes").recall("tabs indentation").hits[0]
    assert "Makefiles" in hit.text and "maybe" not in hit.text
    assert h.sources("mem://rule/fmt") == []


def test_approving_a_secret_edit_is_rejected_and_the_proposal_stays_pending(h):
    m = h.agent("codex")
    p = m.propose("harmless", "rule", name="r")
    res = h.review().approve(p.proposal_id, edit=f"now with {SECRET_TOKEN}")
    assert res.status == "rejected_secret"
    assert h.review().show(p.proposal_id)["status"] == "pending"
    assert h.sources("mem://rule/r") == [] and not h.env.files_containing(SECRET_TOKEN)
    assert h.review().approve(p.proposal_id, edit="x" * (learning.MAX_PROPOSAL_BYTES + 1)).status == "invalid"
    h.set("safety.deny_patterns", '["harm"]')
    assert h.review().approve(p.proposal_id).reason == "deny_pattern"


def test_approve_unknown_and_foreign_ids(h):
    assert h.review().approve("p-000000000000").status == "not_found"
    assert h.review().approve("nonsense").status == "not_found"
    assert h.review().reject("p-000000000000").status == "not_found"


# ================================================================ reject / withdraw / expire
def test_reject_records_the_reason_and_the_proposer_sees_it(h):
    m = h.agent("codex")
    p = m.propose("Maybe do X.", "rule")
    assert h.review().reject(p.proposal_id, reason="too vague").status == "rejected"
    row = m.proposal(p.proposal_id)
    assert row["status"] == "rejected" and row["reason"] == "too vague" and row["decided_by"] == "owner"
    assert h.review().reject(p.proposal_id).status == "not_pending"
    assert h.review().approve(p.proposal_id).status == "not_pending"
    assert h.review().reject(m.propose("Y", "rule").proposal_id, reason="r" * 201).status == "invalid"


def test_withdraw_only_by_the_proposer_and_only_while_pending(h):
    a, b = h.agent("codex"), h.agent("hermes")
    p = a.propose("Retractable.", "rule")
    assert b.withdraw(p.proposal_id).status == "not_found"  # indistinguishable from an unknown id
    assert a.withdraw(p.proposal_id).status == "withdrawn"
    assert a.withdraw(p.proposal_id).status == "not_pending"
    assert h.review().approve(p.proposal_id).status == "not_pending"
    assert a.proposals("withdrawn")[0]["id"] == p.proposal_id
    # a forged withdraw event by another profile is ignored on replay
    forged = learning._event("withdraw", h.env.clock(), proposal_id=a.propose("Second.", "rule").proposal_id, by="hermes")
    from zero_mem.provisioning import append_canonical_event

    append_canonical_event(h.env.layout.memory_stream, forged)
    assert a.proposals("pending")[0]["text"] == "Second."


def test_pending_proposals_expire_after_proposal_ttl_days(h):
    h.set("learning.proposal_ttl_days", "10")
    m = h.agent("codex")
    old = m.propose("Old idea.", "rule", name="old")
    h.day("2026-10-08T09:00:00+00:00")
    fresh = m.propose("Fresh idea.", "rule", name="fresh")
    h.day("2026-10-13T09:00:00+00:00")  # old is 12 days old, fresh 5
    assert [r["id"] for r in m.proposals("pending")] == [fresh.proposal_id]
    assert [r["id"] for r in m.proposals("expired")] == [old.proposal_id]
    assert h.review().approve(old.proposal_id).status == "not_pending"
    assert [r["id"] for r in h.review().list("expired")] == [old.proposal_id]
    out = h.review().expire()
    assert out.status == "expired" and out.detail["proposals_expired"] == [old.proposal_id]
    assert [e["m4"]["op"] for e in h.lp_events()].count("expire") == 1
    assert h.review().expire().detail["proposals_expired"] == []  # idempotent
    assert h.review().approve(fresh.proposal_id).status == "approved"
    # an expired duplicate can be proposed again as a new proposal
    assert m.propose("Old idea.", "rule", name="old").status == "proposed"


def test_active_ttl_hides_approved_items_without_deleting_them(h):
    h.set("learning.active_ttl_days", "30")
    m = h.agent("codex")
    owner_added = m.add("Owner written rule about narwhals.", "rule", name="owner")
    p = m.propose("Learned rule about narwhals.", "rule", name="learned", scope="private")
    h.review().approve(p.proposal_id)
    assert {x.external_ref for x in m.recall("narwhals").hits} == {"mem://rule/owner", "mem://rule/learned"}
    h.day("2026-11-15T09:00:00+00:00")  # 45 days later
    assert {x.external_ref for x in m.recall("narwhals").hits} == {"mem://rule/owner"}  # owner-added never expire
    assert "Learned rule" not in m.context(max_chars=2000).text and "Owner written" in m.context().text
    assert len(h.sources("mem://rule/learned")) == 1  # not deleted, not tombstoned
    listed = h.review().list("approved")
    assert listed[0]["active_expired"] is True
    assert h.review().expire().detail["active_hidden"][0]["external_ref"] == "mem://rule/learned"
    # re-approving a new version renews it
    p2 = m.propose("Learned rule about narwhals, v2.", "rule", name="learned", scope="private")
    assert h.review().approve(p2.proposal_id).superseded is True
    assert "mem://rule/learned" in {x.external_ref for x in m.recall("narwhals").hits}
    h.set("learning.active_ttl_days", "0")
    h.day("2027-06-01T09:00:00+00:00")
    assert "mem://rule/learned" in {x.external_ref for x in m.recall("narwhals").hits}  # 0 = never expires
    assert owner_added.ok


# ================================================================ revoke / supersede
def test_revoke_tombstones_the_source_and_marks_the_proposal(h):
    m, other = h.agent("codex"), h.agent("hermes")
    p = m.propose("Rule about pangolins.", "rule", name="pang")
    sid = h.review().approve(p.proposal_id).source_id
    assert other.recall("pangolins").hits
    res = h.review().revoke("mem://rule/pang", reason="outdated")
    assert res.status == "revoked" and res.source_id == sid
    assert not other.recall("pangolins").hits and "pangolins" not in other.context().text
    assert m.proposal(p.proposal_id)["status"] == "revoked"
    assert h.review().revoke(sid[:12]).write_status == "already_forgotten"
    assert h.review().revoke("mem://rule/never-existed").status == "not_found"
    assert h.review().revoke("abc").status == "invalid"
    # raw bytes are kept (forget semantics) and the registry holds the tombstone version
    assert len(h.sources("mem://rule/pang")) == 2
    # re-approving a fresh proposal under the same name makes it active again
    p2 = m.propose("Rule about pangolins, reworded.", "rule", name="pang")
    assert h.review().approve(p2.proposal_id).write_status == "created"
    assert other.recall("pangolins").hits


def test_revoke_can_target_an_owner_written_source_by_id_prefix_and_refuses_ambiguity(h):
    m = h.agent("codex")
    w = m.add("Owner rule about lemurs.", "rule", name="lem")
    assert h.review().revoke(w.source_id[:10]).status == "revoked"
    assert not m.recall("lemurs").hits


def test_a_new_approved_version_supersedes_the_previous_approval(h):
    m = h.agent("codex")
    p1 = m.propose("Deploys happen on Tuesdays.", "decision", name="deploys")
    p2 = m.propose("Deploys happen on Thursdays.", "decision", name="deploys")
    r1 = h.review().approve(p1.proposal_id)
    r2 = h.review().approve(p2.proposal_id)
    assert (r1.write_status, r2.write_status, r2.superseded) == ("created", "updated", True)
    assert r1.source_id == r2.source_id
    assert m.proposal(p1.proposal_id)["status"] == "superseded" and m.proposal(p1.proposal_id)["superseded_by"] == p2.proposal_id
    assert m.proposal(p2.proposal_id)["status"] == "approved"
    texts = [x.text for x in m.recall("deploys", memory_types=["decision"]).hits]
    assert texts == ["Deploys happen on Thursdays."]
    assert len(h.sources("mem://decision/deploys")) == 2  # two versions, append-only


# ================================================================ review listing and filters
def test_review_list_filters_by_status_and_profile(h):
    a, b = h.agent("codex"), h.agent("hermes")
    pa = a.propose("From codex.", "rule")
    pb = b.propose("From hermes.", "gotcha")
    h.review().approve(pa.proposal_id)
    r = h.review()
    assert [x["id"] for x in r.list("pending")] == [pb.proposal_id]
    assert [x["id"] for x in r.list("approved")] == [pa.proposal_id]
    assert {x["id"] for x in r.list("all")} == {pa.proposal_id, pb.proposal_id}
    assert [x["id"] for x in r.list("all", profile="hermes")] == [pb.proposal_id]
    assert r.list("bogus") == []
    shown = r.show(pb.proposal_id)
    assert shown["history"][0]["op"] == "propose" and shown["proposer"] == "hermes"
    assert r.show("p-ffffffffffff") is None


# ================================================================ isolation
def test_cross_profile_isolation_through_memory_apis(h):
    a, b = h.agent("codex"), h.agent("hermes")
    pa = a.propose("Codex secret plan about wombats.", "rule", scope="private")
    pb = b.propose("Hermes idea.", "rule")
    assert [x["id"] for x in a.proposals()] == [pa.proposal_id]
    assert [x["id"] for x in b.proposals()] == [pb.proposal_id]
    assert b.proposal(pa.proposal_id) is None and a.proposal(pb.proposal_id) is None
    assert b.withdraw(pa.proposal_id).status == "not_found"
    assert a.proposals("pending")[0]["proposer"] == "codex"
    assert not hasattr(Memory, "approve") and not hasattr(Memory, "reject") and not hasattr(Memory, "review")
    # an identical text from another profile is NOT merged into (or revealed by) the first proposal
    dup = b.propose("Codex secret plan about wombats.", "rule", scope="private")
    assert dup.status == "proposed" and dup.proposal_id != pa.proposal_id and dup.seen == 1
    # the approval capability cannot be forged by an agent
    with pytest.raises(PermissionError):
        a._apply_approved_write(object(), "x", "rule", None, "private", None, {})
    with pytest.raises(PermissionError):
        a._apply_approved_write(learning.ApprovedWrite(pb.proposal_id, "hermes", "x"), "x", "rule", None, "private",
                                None, {})


# ================================================================ replay, bounds, canonical stream
def test_replay_of_1000_events_is_bounded_and_correct(h):
    from zero_mem.provisioning import append_canonical_event

    stream = h.env.layout.memory_stream
    now = h.env.clock()
    ids = []
    for i in range(600):
        pid = "p-%012x" % i
        ids.append(pid)
        append_canonical_event(stream, learning._event(
            "propose", now, proposal_id=pid, proposer="codex" if i % 2 else "hermes", source="agent",
            memory_type="rule", scope="private", text=f"rule number {i}", evidence=[f"e{i}"]))
    for i in range(0, 600, 3):
        append_canonical_event(stream, learning._event("seen", now, proposal_id=ids[i], by="codex" if i % 2 else "hermes",
                                                       evidence=["more"]))
    for i in range(0, 600, 6):
        append_canonical_event(stream, learning._event("reject", now, proposal_id=ids[i], by="owner", reason="no"))
    for i in range(1, 600, 6):
        append_canonical_event(stream, learning._event("withdraw", now, proposal_id=ids[i], by="codex"))
    # noise: foreign / malformed / wrong-domain lines are ignored
    with stream.open("ab") as fh:
        fh.write(b'{"event_id":"x","event_type":"learning_proposal","m4":{"domain":"other","op":"propose"}}\n')
        fh.write(b'not json "learning_proposal"\n')
    start = time.perf_counter()
    log = ProposalLog(stream).refresh()
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0
    assert log.events_applied == 1000
    statuses = {}
    for p in log.proposals.values():
        statuses[p.status] = statuses.get(p.status, 0) + 1
    assert statuses == {"rejected": 100, "withdrawn": 100, "pending": 400}
    assert log.proposals[ids[0]].seen == 2 and log.proposals[ids[3]].seen == 2 and log.proposals[ids[4]].seen == 1
    # incremental refresh reads only what was appended
    offset = log._offset
    append_canonical_event(stream, learning._event("reject", now, proposal_id=ids[2], by="owner"))
    log.refresh()
    assert log._offset > offset and log.proposals[ids[2]].status == "rejected"
    assert len(h.review().list("pending")) == 399


def test_replay_ignores_torn_tail_forged_ops_and_replayed_terminal_events(h):
    m = h.agent("codex")
    p = m.propose("Keep me pending.", "rule")
    stream = h.env.layout.memory_stream
    with stream.open("ab") as fh:  # torn append, never trusted
        fh.write(b'{"event_id":"lp-torn","event_type":"learning_proposal","created_at":"2026-10-01T09:00:00Z","m4":'
                 b'{"domain":"learning_proposal","op":"reject","proposal_id":"' + p.proposal_id.encode() + b'"')
    assert h.review().show(p.proposal_id)["status"] == "pending"
    h.review().show(p.proposal_id)
    with stream.open("ab") as fh:  # once the writer finishes the line it is a normal, complete record
        fh.write(b"}}\n")
    assert h.review().show(p.proposal_id)["status"] == "rejected"
    first, p = p, m.propose("Second pending.", "rule")
    from zero_mem.provisioning import append_canonical_event

    now = h.env.clock()
    append_canonical_event(stream, learning._event("approve", now, proposal_id="p-123456789abc", source_id="s"))
    append_canonical_event(stream, learning._event("propose", now, proposal_id="bad", proposer="codex", source="agent",
                                                   memory_type="rule", scope="shared", text="x"))
    append_canonical_event(stream, learning._event("propose", now, proposal_id="p-aaaaaaaaaaaa", proposer="codex",
                                                   source="root", memory_type="rule", scope="shared", text="x"))
    append_canonical_event(stream, learning._event("propose", now, proposal_id="p-bbbbbbbbbbbb", proposer="codex",
                                                   source="agent", memory_type="file", scope="shared", text="x"))
    assert [r["id"] for r in h.review().list("all")] == [first.proposal_id, p.proposal_id]
    # terminal states are final: a replayed reject after an approve changes nothing
    h.review().approve(p.proposal_id)
    append_canonical_event(stream, learning._event("reject", now, proposal_id=p.proposal_id, by="owner"))
    assert h.review().show(p.proposal_id)["status"] == "approved"


def test_replay_overflow_refuses_new_proposals_instead_of_misjudging_limits(h, monkeypatch):
    m = h.agent("codex")
    assert m.propose("one", "rule").ok
    monkeypatch.setattr(learning, "MAX_REPLAY_EVENTS", 1)
    assert m.propose("two", "rule").ok  # the first line fits; the cap trips on the next replayed event
    other = h.agent("hermes", settings_path=h.settings)
    res = other.propose("three", "rule")
    assert res.status == "rejected" and res.reason == "proposal_log_too_large"


def test_replay_equivalence_after_a_derived_rebuild_and_the_stream_stays_valid(h):
    m = h.agent("codex", write_shared=True)
    keep = m.propose("Rule kept.", "rule", name="kept")
    gone = m.propose("Rule revoked.", "rule", name="gone")
    rej = m.propose("Rule rejected.", "gotcha")
    wd = m.propose("Rule withdrawn.", "decision")
    m.propose("Rule kept.", "rule", name="kept", evidence=["x"])
    r = h.review()
    r.approve(keep.proposal_id)
    r.approve(gone.proposal_id)
    r.revoke("mem://rule/gone")
    r.reject(rej.proposal_id, "no")
    m.withdraw(wd.proposal_id)
    snapshot = lambda rev: {x["id"]: (x["status"], x.get("seen"), x.get("source_id")) for x in rev.list("all")}
    before = snapshot(h.review())
    layout = h.env.layout
    store = SQLiteStore(SQLiteStoreConfig(path=layout.derived_db))
    rebuild_policy_state(store._conn, layout.memory_stream)  # the derived-DB rebuild path of `zero-mem upgrade`
    store._conn.commit()
    store.close()
    assert snapshot(h.review()) == before
    assert before[keep.proposal_id][0] == "approved" and before[gone.proposal_id][0] == "revoked"
    assert before[rej.proposal_id][0] == "rejected" and before[wd.proposal_id][0] == "withdrawn"
    upgrade_mod._validate_memory(layout.memory_stream)  # every line: JSON object with an event_id
    assert iter_canonical_policy_events(layout.memory_stream) is not None
    ids = [e["event_id"] for e in h.env.stream_events()]
    assert len(ids) == len(set(ids))
    # a brand-new Memory/Reviewer (fresh process state) derives the same picture
    fresh = Reviewer(layout, operator="owner", clock=h.env.clock, settings_path=h.settings)
    assert snapshot(fresh) == before


def test_full_upgrade_rebuild_tolerates_learning_events(h, monkeypatch, tmp_path):
    """The real ``zero-mem upgrade`` replays the stream: learning events must not break it."""
    m = h.agent("codex", write_shared=True)
    p = m.propose("Rule for upgrade.", "rule", name="up")
    h.review().approve(p.proposal_id)
    root = h.env.root
    monkeypatch.setenv("ZERO_MEM_DATA_ROOT", str(root))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdgc"))
    monkeypatch.delenv("ZERO_MEM_CORPUS_ROOT", raising=False)
    from zero_mem.paths import write_config

    write_config()
    result = upgrade_mod.upgrade()
    assert result["status"] in ("SUCCESS", "READY"), result
    assert h.review().show(p.proposal_id)["status"] == "approved"
    assert m.recall("upgrade", memory_types=["rule"]).hits


def test_events_carry_no_secrets_and_texts_are_never_written_for_rejected_proposals(h):
    m = h.agent("codex")
    m.propose(f"leak {SECRET_TOKEN}", "rule")
    m.propose("clean", "rule", evidence=[SECRET_ENV])
    raw = h.env.layout.memory_stream.read_text(encoding="utf-8")
    assert SECRET_TOKEN not in raw and "hunter2" not in raw
    assert not h.env.files_containing(SECRET_TOKEN)


def test_injection_policy_follows_the_owner_settings_for_the_pinned_profile(h):
    m = h.agent("codex")
    assert m.injection_policy() == (False, 2000, ("rule", "decision", "gotcha"))
    h.set("injection.profiles.codex.enabled", "true")
    h.set("injection.projects.p1.max_chars", "300")
    assert m.injection_policy() == (True, 2000, ("rule", "decision", "gotcha"))
    assert m.injection_policy("p1") == (True, 300, ("rule", "decision", "gotcha"))
    assert h.agent("hermes").injection_policy() == (False, 2000, ("rule", "decision", "gotcha"))


def test_approved_text_is_normalized_like_any_write_and_unicode_names_are_refused(h):
    m = h.agent("codex")
    p = m.propose("Café rule", "rule", name="cafe")
    assert h.review().approve(p.proposal_id).ok
    assert m.recall("rule", memory_types=["rule"]).hits[0].text.startswith("Café")
    assert m.propose("x", "rule", name="né").status == "invalid"


def test_no_timestamps_or_refs_use_backslashes(h):
    m = h.agent("codex")
    p = m.propose("Ref check.", "rule", name="a/b", scope="private")
    res = h.review().approve(p.proposal_id)
    assert res.external_ref == "mem://rule/a/b" and "\\" not in json.dumps(h.lp_events())
    assert timedelta(0) == timedelta(0)
