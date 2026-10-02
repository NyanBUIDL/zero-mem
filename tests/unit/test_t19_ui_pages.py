"""T19 - control panel pages and flows: empty and populated stores, XSS escaping, approve/reject/revoke, add, browse, forget,
brief, agents, settings, kill switch, eval, audit. State changes must equal what the CLI does."""
from __future__ import annotations

import json
import re
from urllib.parse import quote

import pytest

from tests.unit.t19_helpers import (  # noqa: F401  (fixtures)
    ROUTES, SECRET_TOKEN, XSS, Client, env, layout, panel, populate, populated, ppanel, state_fingerprint,
)
from zero_mem import learning_settings as ls
from zero_mem.learning import Reviewer
from zero_mem.memory import Memory
from zero_mem.memory_layout import Layout
from zero_mem.provisioning import Provisioner


def settings_doc():
    return ls.load_settings()


def recall_texts(profile="codex", query="force"):
    with Memory.open(profile, channel="test") as mem:
        return [h.text for h in mem.recall(query).hits]


# ----------------------------------------------------------------------------------------------- render
@pytest.mark.parametrize("route", ROUTES)
def test_each_page_renders_with_an_empty_store(panel, route):
    body = panel.page(route)
    assert "<h1>" in body and "Zero-Mem control panel" in body and 'lang="en"' in body
    assert "Traceback" not in body


@pytest.mark.parametrize("route", ROUTES)
def test_each_page_renders_with_a_populated_store(ppanel, route):
    body = ppanel.page(route)
    assert "<h1>" in body


def test_overview_shows_the_facts_an_owner_needs(ppanel):
    body = ppanel.page("/")
    for needle in ("Data root", "codex", "Live sources", "shared", "private", "rule", "Learning mode", "suggest",
                   "Pending proposals", "Injection", "Kill switch", "Last writes", "Doctor", "Agents", "write"):
        assert needle in body, needle
    assert re.search(r"Pending proposals</dt><dd><a href=\"/inbox\">2</a>", body)
    assert "mem://rule/nofp" in body


def test_pages_have_accessible_structure_and_scrolling_tables(ppanel):
    body = ppanel.page("/agents")
    assert '<main id="main">' in body and 'class="skip"' in body and "<nav aria-label=\"Main\">" in body
    assert 'class="scroll"' in body and "overflow-x:auto" in body
    assert "prefers-color-scheme:dark" in body and 'name="viewport"' in body
    for label in re.findall(r'<label for="([^"]+)"', body):
        assert f'id="{label}"' in body, label


# ----------------------------------------------------------------------------------------------- XSS
def test_xss_payloads_are_escaped_on_every_page(env, layout):
    populate()
    with Memory.open("codex", channel="test") as mem:
        mem.propose(f"proposal text {XSS}", "rule", name="xss", evidence=[f"evidence {XSS}"])
    from zero_mem import cli

    assert cli.main(["--profile", "codex", "add", f"memory text {XSS}", "--type", "rule", "--scope", "shared",
                     "--name", "xss-rule"]) == 0
    from tests.unit.t19_helpers import start, stop

    server, thread = start(profile="codex")
    try:
        c = Client(server)
        enc = quote(XSS, safe="")
        sid = None
        with Memory.open("codex", channel="test") as mem:
            sid = mem.recall("memory text").hits[0].source_id
        routes = ROUTES + [f"/search?q={enc}", f"/search?q=memory&type={enc}&scope={enc}&project={enc}&profile={enc}",
                           f"/search?q=memory&profile=codex&project={enc}", f"/brief?profile={enc}&project={enc}&task={enc}&max_chars={enc}",
                           f"/brief?profile=codex&task={enc}", f"/source?id={sid}&profile=codex", f"/source?id={enc}&profile={enc}",
                           f"/inbox?status={enc}", f"/audit?page={enc}", f"/ingest/preview?id={enc}", f"/nonexistent/{enc}",
                           f"/search?q=memory%20text&profile=codex&flash={enc}"]
        for route in routes:
            status, _h, body = c.get(route)
            assert status in (200, 400, 404), (route, status)
            assert "<script" not in body.lower(), route
            assert "<img src=x" not in body, route
            assert "onerror=alert" not in body.replace("onerror=alert(2)&gt;", ""), route
        inbox = c.page("/inbox")
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in inbox and "&lt;img src=x onerror=alert(2)&gt;" in inbox
        detail = c.page(f"/source?id={sid}&profile=codex")
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in detail
        assert "&lt;script&gt;" in c.page(f"/brief?profile=codex&task={enc}")
    finally:
        stop(server, thread)


def test_xss_in_form_posts_filenames_and_errors_is_escaped(panel):
    # add: a bad project id echoes back into the form
    status, _h, body = panel.post("/add", {"text": XSS, "memory_type": "fact", "scope": "project", "project_id": XSS})
    assert status == 422 and "<script" not in body.lower() and "&lt;script&gt;" in body
    # agents / settings / eval echo errors
    for path, fields in (("/agents/add", {"profile": XSS}), ("/agents/grant-read", {"profile": XSS, "kind": "space", "target": XSS}),
                         ("/settings/override", {"kind": "profile", "name": XSS, "enabled": "true"}),
                         ("/eval/run", {"cases": XSS, "profile": "codex"}), ("/inbox/approve", {"id": XSS, "approve": "1"}),
                         ("/inbox/revoke", {"ref": XSS, "approve": "1"}), ("/forget", {"id": XSS, "approve": "1"})):
        status, _h, body = panel.post(path, fields)
        assert "<script" not in body.lower() and "<img src=x" not in body, path
    # upload file name
    name = "<img src=x onerror=alert(1)>.txt"
    status, _h, body = panel.multipart("/ingest/preview", {"mode": "upload", "memory_type": "fact"}, name, b"harmless words here")
    assert status == 200 and "<img src=x" not in body and "&lt;img src=x" in body
    key = re.search(r'name="id" value="([^"]+)"', body).group(1)
    status, _h, body = panel.post("/ingest/confirm", {"id": key, "approve": "1"})
    assert status == 200 and "<img src=x" not in body and "Ingest report" in body


def test_evidence_and_proposer_cannot_break_out_of_attributes(env):
    from tests.unit.t19_helpers import start, stop

    populate()
    with Memory.open("codex", channel="test") as mem:
        res = mem.propose("break out", "rule", name="attr", evidence=['" onfocus="alert(1)" autofocus="', "'><svg onload=alert(1)>"])
        assert res.ok
    server, thread = start(profile="codex")
    try:
        body = Client(server).page("/inbox")
        assert "<svg" not in body and 'onfocus="alert' not in body and "&quot; onfocus=&quot;" in body
    finally:
        stop(server, thread)


# ----------------------------------------------------------------------------------------------- inbox flows
def test_approve_changes_state_exactly_like_the_cli(ppanel, layout):
    pid = ppanel.ids["pending"]
    inbox = ppanel.page("/inbox")
    assert pid in inbox and "Run the linter before every commit." in inbox and "PR #12" in inbox and "codex" in inbox
    assert recall_texts(query="linter") == []
    status, _h, body = ppanel.post("/inbox/approve", {"id": pid, "edit": "Run the linter and the tests before every commit.",
                                                      "name": "lint-and-test", "approve": "1"})
    assert status == 200 and "Approved" in body and "mem://rule/lint-and-test" in body and "Source id" in body
    shown = Reviewer(layout).show(pid)
    assert shown["status"] == "approved" and shown["external_ref"] == "mem://rule/lint-and-test"
    assert shown["final_text"] == "Run the linter and the tests before every commit."
    assert recall_texts(query="linter tests") == ["Run the linter and the tests before every commit."]
    assert shown["decided_by"].endswith("@ui")


def test_approve_requires_the_confirmation_checkbox(ppanel, layout):
    pid = ppanel.ids["pending"]
    status, _h, body = ppanel.post("/inbox/approve", {"id": pid, "edit": "x", "name": ""})
    assert "not confirmed" in body.lower()
    assert Reviewer(layout).show(pid)["status"] == "pending" and recall_texts(query="linter") == []


def test_approve_unchanged_text_is_not_recorded_as_an_edit(ppanel, layout):
    pid = ppanel.ids["pending"]
    ppanel.post("/inbox/approve", {"id": pid, "edit": "Run the linter before every commit.", "name": "", "approve": "1"})
    assert "final_text" not in Reviewer(layout).show(pid)


def test_approve_a_secret_edit_is_refused_and_nothing_is_stored(ppanel, layout):
    pid = ppanel.ids["pending"]
    _s, _h, body = ppanel.post("/inbox/approve", {"id": pid, "edit": f"token {SECRET_TOKEN}", "approve": "1"})
    assert "credential-like" in body and SECRET_TOKEN not in body
    assert Reviewer(layout).show(pid)["status"] == "pending"


def test_reject_with_reason_and_a_second_decision_is_refused(ppanel, layout):
    pid = ppanel.ids["pending"]
    _s, _h, body = ppanel.post("/inbox/reject", {"id": pid, "reason": "too vague"})
    assert "Rejected" in body
    shown = Reviewer(layout).show(pid)
    assert shown["status"] == "rejected" and shown["reason"] == "too vague"
    _s, _h, body = ppanel.post("/inbox/approve", {"id": pid, "approve": "1"})
    assert "already rejected" in body
    assert Reviewer(layout).show(pid)["status"] == "rejected"


def test_revoke_an_approved_memory_hides_it_from_recall(ppanel, layout):
    pid = ppanel.ids["pending"]
    ppanel.post("/inbox/approve", {"id": pid, "name": "lint", "approve": "1"})
    assert recall_texts(query="linter")
    approved = ppanel.page("/inbox?status=approved")
    sid = re.search(r'name="ref" value="([0-9a-f]{64})"', approved).group(1)
    _s, _h, body = ppanel.post("/inbox/revoke", {"ref": sid, "reason": "obsolete", "approve": "1"})
    assert "Revoked" in body
    assert recall_texts(query="linter") == []
    assert Reviewer(layout).show(pid)["status"] == "revoked"
    _s, _h, body = ppanel.post("/inbox/revoke", {"ref": sid})  # no confirmation
    assert "not confirmed" in body.lower()


def test_expire_button_applies_the_ttl(ppanel):
    _s, _h, body = ppanel.post("/inbox/expire", {})
    assert "TTLs applied" in body


def test_kill_switch_blocks_approval_in_the_ui_too(ppanel, layout):
    ppanel.post("/settings/kill", {"state": "on", "approve": "1"})
    _s, _h, body = ppanel.post("/inbox/approve", {"id": ppanel.ids["pending"], "approve": "1"})
    assert "kill switch" in body.lower()
    assert Reviewer(layout).show(ppanel.ids["pending"])["status"] == "pending"


def test_unknown_proposal_is_a_clean_error(ppanel):
    _s, _h, body = ppanel.post("/inbox/approve", {"id": "p-000000000000", "approve": "1"})
    assert "no such proposal" in body.lower() or "unknown_proposal" in body


# ----------------------------------------------------------------------------------------------- add
def test_add_text_goes_through_the_owner_path_and_shows_the_source_id(ppanel):
    _s, _h, body = ppanel.post("/add", {"text": "Use tabs in Makefiles.", "memory_type": "rule", "scope": "shared",
                                        "name": "tabs", "project_id": "", "profile": "codex"})
    assert "Saved" in body and "mem://rule/tabs" in body and "Source id" in body and "created" in body
    assert recall_texts(query="tabs Makefiles") == ["Use tabs in Makefiles."]
    _s, _h, body = ppanel.post("/add", {"text": "Use tabs in Makefiles.", "memory_type": "rule", "scope": "shared",
                                        "name": "tabs", "profile": "codex"})
    assert "unchanged" in body


def test_add_defaults_to_the_panels_profile_and_private_scope(panel):
    panel.post("/add", {"text": "Bob likes tea.", "memory_type": "fact", "scope": "", "profile": ""})
    assert recall_texts(query="tea") == ["Bob likes tea."]


def test_add_rejects_secrets_denied_scopes_and_bad_input_without_storing(panel, layout):
    before = state_fingerprint(layout)
    status, _h, body = panel.post("/add", {"text": f"key {SECRET_TOKEN}", "memory_type": "fact"})
    assert status == 422 and "credential-like" in body and SECRET_TOKEN not in body
    status, _h, body = panel.post("/add", {"text": "shared note", "memory_type": "fact", "scope": "shared"})
    assert status == 422 and "denied" in body.lower() and "grant-write" in body  # codex has no grant in an empty store
    status, _h, body = panel.post("/add", {"text": "x", "memory_type": "fact", "scope": "project", "project_id": ""})
    assert status == 422 and "project" in body
    status, _h, body = panel.post("/add", {"text": "x", "memory_type": "nonsense"})
    assert status == 422
    status, _h, body = panel.post("/add", {"text": "x", "memory_type": "fact", "name": "bad name!"})
    assert status == 422 and "may use letters" in body
    status, _h, body = panel.post("/add", {"text": "   ", "memory_type": "fact"})
    assert status == 422
    status, _h, body = panel.post("/add", {"text": "x", "memory_type": "fact", "profile": "bad profile"})
    assert status == 422 and "invalid profile" in body
    assert "SECRET" not in body
    from zero_mem.memory import Memory as M

    with M.open("codex", channel="t") as m:
        assert m.status()["sources"]["total"] == 0


def test_add_text_size_limit(panel):
    status, _h, body = panel.post("/add", {"text": "a " * (200 * 1024), "memory_type": "fact"})
    assert status == 422 and "larger than" in body


# ----------------------------------------------------------------------------------------------- browse
def test_search_shows_provenance_and_filters(ppanel):
    body = ppanel.page("/search?q=force+push")
    for needle in ("mem://rule/nofp", "rule", "shared", "Score", "Version", "sv_", "Source id"):
        assert needle in body, needle
    assert "PostgreSQL" not in ppanel.page("/search?q=force&type=fact")
    assert "mem://rule/nofp" not in ppanel.page("/search?q=force&scope=private")
    assert "Alice" in ppanel.page("/search?q=PostgreSQL&scope=private")
    assert "0 result(s)" in ppanel.page("/search?q=zzzznothing")
    status, _h, body = ppanel.get("/search?q=%21%21%21")
    assert status == 400 and "no searchable words" in body
    assert ppanel.get("/search?q=a&type=bogus")[0] == 400
    assert ppanel.get("/search?q=a&project=bad%20id")[0] == 400


def test_browse_lists_the_newest_sources_and_pages(ppanel):
    body = ppanel.page("/search")
    assert "mem://rule/nofp" in body and "source(s)" in body
    assert "mem://fact/" in body
    assert "mem://rule/nofp" not in ppanel.page("/search?type=fact")
    assert "mem://rule/nofp" in ppanel.page("/search?scope=shared")


def test_private_memory_of_another_profile_is_not_visible_as_another_profile(ppanel):
    assert "PostgreSQL" in ppanel.page("/search?q=PostgreSQL&profile=codex")
    assert "Alice prefers" not in ppanel.page("/search?q=PostgreSQL&profile=other")
    assert Provisioner(Layout.resolve(None)).add_agent("other")["status"] == "added"
    assert "mem://rule/nofp" in ppanel.page("/search?q=force&profile=other")  # ks-shared is readable by everyone


def test_source_detail_and_forget_with_confirmation(ppanel):
    sid = re.search(r"/source\?id=([0-9a-f]{64})", ppanel.page("/search?q=PostgreSQL")).group(1)
    body = ppanel.page(f"/source?id={sid}&profile=codex")
    for needle in ("Alice prefers PostgreSQL.", "Provenance", "Version", "Forget", "channel", "private"):
        assert needle in body, needle
    assert ppanel.get(f"/source?id={sid}&profile=stranger")[0] == 404
    assert ppanel.get("/source?id=zz")[0] == 404 and ppanel.get("/source?id=" + "0" * 64)[0] == 404
    _s, _h, body = ppanel.post("/forget", {"id": sid, "profile": "codex"})  # no confirmation
    assert "not confirmed" in body.lower() and recall_texts(query="PostgreSQL")
    _s, _h, body = ppanel.post("/forget", {"id": sid, "profile": "codex", "approve": "1"})
    assert "Forgotten" in body and recall_texts(query="PostgreSQL") == []
    detail = ppanel.page(f"/source?id={sid}&profile=codex")
    assert "forgotten" in detail and "Alice" not in detail
    _s, _h, body = ppanel.post("/forget", {"id": sid, "profile": "codex", "approve": "1"})
    assert "already_forgotten" in body
    assert "PostgreSQL" not in ppanel.page("/search?profile=codex")


def test_forget_of_an_unreadable_source_is_not_found(ppanel):
    sid = re.search(r"/source\?id=([0-9a-f]{64})", ppanel.page("/search?q=PostgreSQL")).group(1)
    _s, _h, body = ppanel.post("/forget", {"id": sid, "profile": "stranger", "approve": "1"})
    assert "not_found" in body and recall_texts(query="PostgreSQL")


# ----------------------------------------------------------------------------------------------- brief
def test_brief_preview_matches_memory_brief_and_explains_why_injection_is_off(ppanel):
    body = ppanel.page("/brief?profile=codex&project=&task=force+push&max_chars=")
    with Memory.open("codex", channel="test") as mem:
        expected = mem.brief("force push", preview=True)
    assert "Injection OFF" in body and "injection_disabled" not in body.replace("Injection is OFF", "") or "Injection is OFF" in body
    assert "mem://rule/nofp" in body and "Never force push to main." in body
    assert f"{len(expected.text)} of {expected.max_chars} characters used" in body
    assert "<progress" in body
    ls.set_value("injection.enabled", "true")
    body = ppanel.page("/brief?profile=codex&task=force+push")
    assert "Injection ON" in body and "an agent would receive exactly this text" in body
    ls.set_value("safety.kill_switch", "true")
    assert "kill switch is ON" in ppanel.page("/brief?profile=codex&task=force+push")
    status, _h, body = ppanel.get("/brief?profile=codex&max_chars=99999")
    assert status == 400 and "between 1 and 8000" in body
    assert ppanel.get("/brief?profile=codex&max_chars=abc")[0] == 400
    assert ppanel.get("/brief?profile=bad%20id")[0] == 400
    assert ppanel.get("/brief?profile=codex&project=bad%20id")[0] == 400


def test_brief_respects_a_small_budget(ppanel):
    body = ppanel.page("/brief?profile=codex&task=force&max_chars=60")
    assert "of 60 characters used" in body


# ----------------------------------------------------------------------------------------------- agents
def test_agents_flow_add_grant_revoke_like_the_cli(panel, layout):
    assert "No agents registered" in panel.page("/agents")
    _s, _h, body = panel.post("/agents/add", {"profile": "claude-code"})
    assert "Agent added" in body and "claude-code" in body
    status, _h, body = panel.post("/agents/add", {"profile": "bad name!"})
    assert status == 422 and "profile" in body.lower()
    _s, _h, body = panel.post("/agents/grant-read", {"profile": "claude-code", "kind": "project", "target": "zero-mem"})
    assert "granted" in body
    status, _h, body = panel.post("/agents/grant-write", {"profile": "claude-code", "kind": "space", "target": "ks-shared"})
    assert status == 422 and "I approve" in body
    rows = {a["profile"]: a for a in Provisioner(layout).list_agents()}
    assert not rows["claude-code"]["can_write_shared"]
    _s, _h, body = panel.post("/agents/grant-write", {"profile": "claude-code", "kind": "space", "target": "ks-shared",
                                                      "basis": "owner said so", "approve": "1"})
    assert "Write access granted" in body and "opapp-" in body and "@ui" in body
    rows = {a["profile"]: a for a in Provisioner(layout).list_agents()}
    assert rows["claude-code"]["can_write_shared"]
    events = [json.loads(line) for line in layout.memory_stream.read_text(encoding="utf-8").splitlines()]
    approvals = [e["m4"] for e in events if e["event_type"] == "operator_approval"]
    assert approvals and approvals[-1]["approved_by"].endswith("@ui") and approvals[-1]["basis"] == "owner said so"
    page = panel.page("/agents")
    assert "(approved)" in page and "project:zero-mem" in page
    _s, _h, body = panel.post("/agents/revoke", {"profile": "claude-code", "kind": "space", "target": "ks-shared", "operation": "WRITE"})
    assert "Revoked 1 grant" in body
    assert not {a["profile"]: a for a in Provisioner(layout).list_agents()}["claude-code"]["can_write_shared"]
    _s, _h, body = panel.post("/agents/revoke", {"profile": "claude-code", "kind": "", "target": ""})
    assert "Revoked" in body
    _s, _h, body = panel.post("/agents/revoke", {"profile": "claude-code"})
    assert "Nothing to revoke" in body


def test_agent_errors_are_inline(panel):
    status, _h, body = panel.post("/agents/grant-read", {"profile": "nobody", "kind": "space", "target": "ks-shared"})
    assert status == 422 and "not registered" in body
    status, _h, body = panel.post("/agents/grant-read", {"profile": "nobody", "kind": "", "target": ""})
    assert status == 422
    status, _h, body = panel.post("/agents/revoke", {"profile": "nobody", "kind": "project", "target": ""})
    assert status == 422 and "project id" in body


# ----------------------------------------------------------------------------------------------- settings
def test_settings_save_valid_values_through_the_validated_api(panel):
    fields = {"mode": "off", "max_proposals_per_day": "7", "allow_agent_proposals": "false", "proposal_ttl_days": "5",
              "active_ttl_days": "9", "injection_enabled": "true", "injection_max_chars": "1500", "deny_patterns": "foo-\\d+\nbar"}
    _s, _h, body = panel.post("/settings/save", fields, lists=[("injection_types", "rule"), ("injection_types", "persona")])
    assert "Settings saved" in body
    cfg = ls.load_settings()
    assert cfg.valid and cfg.mode == "off" and cfg.max_proposals_per_day == 7 and not cfg.allow_agent_proposals
    assert cfg.proposal_ttl_days == 5 and cfg.active_ttl_days == 9 and cfg.injection_enabled and cfg.injection_max_chars == 1500
    assert set(cfg.injection_types) == {"rule", "persona"} and cfg.deny_patterns == ("foo-\\d+", "bar")
    body = panel.page("/settings")
    assert 'value="1500"' in body and "foo-\\d+" in body
    _s, _h, body = panel.post("/settings/save", fields, lists=[("injection_types", "rule"), ("injection_types", "persona")])
    assert "No changes" in body


@pytest.mark.parametrize("fields,needle,key", [
    ({"mode": "bogus"}, "mode", "learning.mode"),
    ({"injection_max_chars": "99999"}, "max_chars", "injection.max_chars"),
    ({"max_proposals_per_day": "abc"}, "integer", None),
    ({"proposal_ttl_days": "-1"}, "", None),
    ({"deny_patterns": "(a+)+"}, "", None),
    ({"deny_patterns": "[unclosed"}, "", None),
])
def test_settings_invalid_input_is_shown_inline_and_nothing_is_written(panel, fields, needle, key):
    path = ls.settings_path()
    existed = path.exists()
    before = path.read_bytes() if existed else None
    full = {"mode": "suggest", "max_proposals_per_day": "20", "allow_agent_proposals": "true", "proposal_ttl_days": "30",
            "active_ttl_days": "0", "injection_enabled": "false", "injection_max_chars": "2000", "deny_patterns": ""}
    full.update(fields)
    status, _h, body = panel.post("/settings/save", full, lists=[("injection_types", "rule")])
    assert status == 422 and 'class="err"' in body and needle in body
    assert (path.read_bytes() if path.exists() else None) == before
    assert ls.load_settings().valid


def test_one_bad_field_blocks_the_whole_save(panel):
    full = {"mode": "off", "max_proposals_per_day": "x", "allow_agent_proposals": "true", "proposal_ttl_days": "30",
            "active_ttl_days": "0", "injection_enabled": "false", "injection_max_chars": "2000", "deny_patterns": ""}
    status, _h, body = panel.post("/settings/save", full, lists=[("injection_types", "rule")])
    assert status == 422 and ls.load_settings().mode == "suggest"
    assert 'value="x"' in body  # the owner's input is kept


def test_settings_overrides_add_and_remove(panel):
    _s, _h, body = panel.post("/settings/override", {"kind": "profile", "name": "codex", "enabled": "true", "max_chars": "900",
                                                      "types": "rule,gotcha"})
    assert "Override saved" in body
    cfg = ls.load_settings()
    assert cfg.profiles["codex"].enabled is True and cfg.profiles["codex"].max_chars == 900
    assert "codex" in panel.page("/settings") and "rule, gotcha" in panel.page("/settings")
    status, _h, body = panel.post("/settings/override", {"kind": "project", "name": "p", "max_chars": "99999"})
    assert status == 422 and 'class="err"' in body
    status, _h, body = panel.post("/settings/override", {"kind": "project", "name": "p"})
    assert status == 422 and "at least one" in body
    status, _h, body = panel.post("/settings/override", {"kind": "profile", "name": "bad name"})
    assert status == 422
    _s, _h, body = panel.post("/settings/unset", {"kind": "profile", "name": "codex"})
    assert "Override removed" in body and "codex" not in ls.load_settings().profiles
    _s, _h, body = panel.post("/settings/unset", {"kind": "profile", "name": "codex"})
    assert "No such override" in body


def test_kill_switch_needs_confirmation_and_toggles(panel):
    assert "KILL SWITCH" in panel.page("/settings")
    _s, _h, body = panel.post("/settings/kill", {"state": "on"})
    assert "Not confirmed" in body and not ls.load_settings().kill_switch
    _s, _h, body = panel.post("/settings/kill", {"state": "on", "approve": "1"})
    assert "Kill switch ON" in body and ls.load_settings().kill_switch
    page = panel.page("/settings")
    assert "Turn kill switch OFF" in page
    # while on, a proposal from an agent is refused (same as the CLI)
    with Memory.open("codex", channel="t") as mem:
        assert mem.propose("something", "rule").status == "rejected"
    _s, _h, body = panel.post("/settings/kill", {"state": "off"})
    assert "Not confirmed" in body and ls.load_settings().kill_switch
    _s, _h, body = panel.post("/settings/kill", {"state": "off", "approve": "1"})
    assert "Kill switch OFF" in body and not ls.load_settings().kill_switch
    assert "Unknown state" in panel.post("/settings/kill", {"state": "maybe", "approve": "1"})[2]


def test_settings_page_survives_an_unusable_file_and_says_so(panel):
    path = ls.settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[injection\n", encoding="utf-8")
    body = panel.page("/settings")
    assert "unusable" in body and "fail-safe" in body
    status, _h, body = panel.post("/settings/kill", {"state": "on", "approve": "1"})
    assert status == 422 and "not valid TOML" in body
    assert path.read_text(encoding="utf-8") == "[injection\n"  # never overwritten
    assert "unusable" in panel.page("/")


# ----------------------------------------------------------------------------------------------- eval
def test_eval_safety_suite_runs_and_reports(panel):
    _s, _h, body = panel.post("/eval/safety", {})
    assert "all invariants hold" in body and "PASS" in body and "other_profile_private_never_appears" in body


def test_eval_cases_run_record_history_and_show_it(ppanel):
    ls.set_value("injection.enabled", "true")
    cases = json.dumps({"id": "nofp", "task": "force push", "must_include": ["mem://rule/nofp"], "profile": "codex"}) + "\n" + \
        json.dumps({"id": "leak", "task": "force push", "must_not_include": ["mem://rule/nofp"], "profile": "codex"}) + "\n"
    _s, _h, body = ppanel.post("/eval/run", {"cases": cases, "profile": "codex"})
    assert "1 of 2 passed" in body and "mem://rule/nofp" in body and "PASS" in body and "FAIL" in body
    page = ppanel.page("/eval")
    assert "control-panel.jsonl" in page and "History" in page
    status, _h, body = ppanel.post("/eval/run", {"cases": "not json", "profile": "codex"})
    assert status == 422 and "not valid JSON" in body
    status, _h, body = ppanel.post("/eval/run", {"cases": '{"id":"x","task":"t","bogus":1}', "profile": "codex"})
    assert status == 422 and "unknown key" in body
    status, _h, body = ppanel.post("/eval/run", {"cases": cases, "profile": "bad profile"})
    assert status == 422


def test_eval_page_shows_doctor_output(panel):
    body = panel.page("/eval")
    assert "Doctor" in body and "learning_settings" in body and "sqlite" in body


# ----------------------------------------------------------------------------------------------- audit
def test_audit_log_is_newest_first_and_pages(ppanel, layout):
    prov = Provisioner(layout)
    for i in range(30):
        prov.add_agent(f"agent-{i:02d}")
    body = ppanel.page("/audit")
    assert body.index("agent-29") < body.index("agent-10")
    assert "Older" in body and "Newer" not in body
    page2 = ppanel.page("/audit?page=2")
    assert "Newer" in page2 and "agent-" in page2
    for needle in ("proposal", "approval", "grant", "write"):
        assert needle in ppanel.page("/audit?page=2") + body, needle
    assert ppanel.page("/audit?page=999") and ppanel.page("/audit?page=abc")


def test_audit_log_records_ui_decisions(ppanel):
    pid = ppanel.ids["pending"]
    ppanel.post("/inbox/approve", {"id": pid, "name": "lint", "approve": "1"})
    body = ppanel.page("/audit")
    assert "approve" in body and "@ui" in body and "mem://rule/lint" in body
    sid = re.search(r"/source\?id=([0-9a-f]{64})", ppanel.page("/search?q=PostgreSQL")).group(1)
    ppanel.post("/forget", {"id": sid, "profile": "codex", "approve": "1"})
    assert "forgotten" in ppanel.page("/audit")


def test_overview_settings_path_is_rendered_as_code_not_escaped_markup(ppanel):
    body = ppanel.page("/")
    assert "&lt;code&gt;" not in body and "<code>" in body
