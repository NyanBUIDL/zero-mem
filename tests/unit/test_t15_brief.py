"""T15 - ``Memory.brief``: the task-aware briefing (settings-gated, deterministic, budgeted, never unapproved)."""
from __future__ import annotations

import json

import pytest

from tests.unit.t5_memory_helpers import Env
from zero_mem import learning_settings as ls
from zero_mem.learning import Reviewer
from zero_mem.memory import Memory
from zero_mem.memory_results import BriefBundle


class H:
    def __init__(self, tmp_path):
        self.env = Env(tmp_path)
        self.settings = tmp_path / "cfg" / "settings.toml"

    def agent(self, profile, **kw) -> Memory:
        kw.setdefault("settings_path", self.settings)
        return self.env.agent(profile, **kw)

    def set(self, key, value):
        ls.set_value(key, value, self.settings)

    def enable(self, types=None):
        self.set("injection.enabled", "true")
        if types:
            self.set("injection.types", ",".join(types))

    def reviewer(self):
        return Reviewer(self.env.layout, operator="owner", clock=self.env.clock, settings_path=self.settings)


@pytest.fixture
def h(tmp_path):
    harness = H(tmp_path)
    yield harness
    harness.env.close()


def seed(m: Memory):
    assert m.add("Never force push to main.", "rule", name="no-force-push", scope="shared").ok
    assert m.add("Run the unit tests before every commit.", "rule", name="test-first", scope="shared").ok
    assert m.add("We chose sqlite over postgres because the store is local.", "decision", name="db-choice",
                 scope="shared").ok
    assert m.add("The derived database locks under concurrent writers; retry on busy.", "gotcha", name="db-busy",
                 scope="shared").ok
    assert m.add("Release flow: tag, build wheel, publish.", "workflow", name="release", scope="shared").ok
    assert m.add("The user prefers short answers.", "persona", name="style", scope="shared").ok


# ============================================================ gating
def test_brief_is_empty_with_a_reason_while_injection_is_disabled_by_default(h):
    m = h.agent("codex", write_shared=True)
    seed(m)
    b = m.brief("fix the database locking bug")
    assert isinstance(b, BriefBundle)
    assert (b.status, b.text, b.reason, b.enabled, b.preview) == ("disabled", "", "injection_disabled", False, False)
    assert b.ok and b.sources == [] and b.truncated is False
    d = b.as_dict()
    assert d["reason"] == "injection_disabled" and d["text"] == "" and d["chars"] == 0


def test_the_kill_switch_wins_over_an_enabled_injection(h):
    m = h.agent("codex", write_shared=True)
    seed(m)
    h.enable()
    h.set("safety.kill_switch", "true")
    b = m.brief("database")
    assert (b.status, b.text, b.reason) == ("disabled", "", "kill_switch")


def test_an_unusable_settings_file_fails_safe(h):
    m = h.agent("codex", write_shared=True)
    seed(m)
    h.settings.parent.mkdir(parents=True, exist_ok=True)
    h.settings.write_text("[injection\n", encoding="utf-8")
    b = m.brief("database")
    assert b.text == "" and b.reason == "settings_invalid" and b.status == "disabled"


def test_enabled_injection_returns_rules_always_and_rules_only_by_default_types(h):
    m = h.agent("codex", write_shared=True)
    seed(m)
    h.enable()
    b = m.brief()  # no task: rules (and nothing task-matched)
    assert b.status == "ok" and b.enabled is True and b.reason is None
    assert b.sources == ["mem://rule/no-force-push", "mem://rule/test-first"]
    assert b.text.startswith("## Rules\n- mem://rule/no-force-push: Never force push to main.")
    assert "workflow" not in b.text.lower() and "persona" not in b.text.lower()


def test_preview_shows_what_would_be_injected_and_why_it_is_off(h):
    m = h.agent("codex", write_shared=True)
    seed(m)
    b = m.brief("database locking", preview=True)
    assert b.preview is True and b.enabled is False and b.reason == "injection_disabled"
    assert "mem://rule/no-force-push" in b.sources and b.text
    h.set("safety.kill_switch", "true")
    k = m.brief("database locking", preview=True)
    assert k.reason == "kill_switch" and k.sources == b.sources  # same content, different reason
    h.enable()
    h.set("safety.kill_switch", "false")
    on = m.brief("database locking", preview=True)
    assert on.enabled is True and on.reason is None


def test_types_setting_limits_the_briefing(h):
    m = h.agent("codex", write_shared=True)
    seed(m)
    h.enable(["rule"])
    b = m.brief("database locking sqlite")
    assert b.sources == ["mem://rule/no-force-push", "mem://rule/test-first"]
    h.set("injection.types", "rule,gotcha")
    refs = m.brief("database locking sqlite").sources
    assert refs == ["mem://rule/no-force-push", "mem://rule/test-first", "mem://gotcha/db-busy"]
    h.set("injection.types", "gotcha")  # rules are only included when allowed
    assert m.brief("database locking").sources == ["mem://gotcha/db-busy"]


def test_profile_and_project_overrides_apply(h):
    m = h.agent("codex", write_shared=True)
    seed(m)
    h.set("injection.profiles.codex.enabled", "true")
    assert m.brief().status == "ok"
    h.set("injection.projects.quiet.enabled", "false")
    assert m.brief(project_id="quiet").reason == "injection_disabled"
    h.set("injection.projects.loud.max_chars", "60")
    assert len(m.brief(project_id="loud").text) <= 60
    other = h.agent("claude-code")
    assert other.brief().reason == "injection_disabled"  # the override is per profile


# ============================================================ content and order
def test_sections_follow_the_documented_order_and_every_line_carries_its_ref(h):
    m = h.agent("codex", write_shared=True, write_projects=["zm"])
    seed(m)
    assert m.add("day one: wired the harness", "devlog", scope="project", project_id="zm").ok
    h.enable(["rule", "decision", "gotcha", "workflow", "skill", "persona", "devlog"])
    b = m.brief("sqlite database locks and release", project_id="zm", max_chars=4000)
    titles = [ln[3:] for ln in b.text.splitlines() if ln.startswith("## ")]
    assert titles == ["Rules", "Decisions", "Gotchas", "Workflows", "Recent devlog", "Persona"]
    for line in b.text.splitlines():
        if not line.startswith("## "):
            assert line.startswith("- mem://"), line
    assert b.sections == {"Rules": 2, "Decisions": 1, "Gotchas": 1, "Workflows": 1, "Recent devlog": 1, "Persona": 1}
    assert b.sources[0].startswith("mem://rule/") and b.sources[-1] == "mem://persona/style"


def test_task_matched_lines_state_why(h):
    m = h.agent("codex", write_shared=True)
    seed(m)
    h.enable()
    b = m.brief("investigate the sqlite database locks")
    line = next(ln for ln in b.text.splitlines() if "mem://gotcha/db-busy" in ln)
    assert "(matched: " in line and "locks" in line
    rule_line = next(ln for ln in b.text.splitlines() if "mem://rule/no-force-push" in ln)
    assert "matched" not in rule_line  # rules are always included, not matched
    item = next(i for i in b.items if i["ref"] == "mem://gotcha/db-busy")
    assert item["type"] == "gotcha" and "locks" in item["why"]
    assert all("why" not in i for i in b.items if i["type"] == "rule")


def test_an_unrelated_task_gets_rules_only_and_a_blank_task_is_like_none(h):
    m = h.agent("codex", write_shared=True)
    seed(m)
    h.enable()
    assert m.brief("paint the fence blue").sources == ["mem://rule/no-force-push", "mem://rule/test-first"]
    assert m.brief("   ").sources == m.brief(None).sources
    assert m.brief("the of and").status == "ok"  # only function words: no crash


def test_only_the_newest_version_of_a_named_item_appears(h):
    m = h.agent("codex", write_shared=True)
    assert m.add("Old wording about merging.", "rule", name="merge", scope="shared").status == "created"
    assert m.add("New wording about squash.", "rule", name="merge", scope="shared").status == "updated"
    h.enable()
    b = m.brief()
    assert "New wording" in b.text and "Old wording" not in b.text and b.sources == ["mem://rule/merge"]


def test_ordering_is_deterministic_and_ties_break_by_ref(h):
    m = h.agent("codex", write_shared=True)
    for name in ("zeta", "alpha", "mid"):
        assert m.add(f"Cache invalidation advice {name}.", "gotcha", name=name, scope="shared").ok
    h.enable(["gotcha"])
    first = m.brief("cache invalidation advice")
    assert first.sources == ["mem://gotcha/alpha", "mem://gotcha/mid", "mem://gotcha/zeta"]
    assert m.brief("cache invalidation advice").as_dict() == first.as_dict()


def test_recent_devlog_is_newest_first_for_the_project_only(h):
    m = h.agent("codex", write_projects=["zm", "other"])
    h.env.clock.set("2026-09-29T09:00:00+00:00")
    m.add("oldest entry", "devlog", scope="project", project_id="zm")
    h.env.clock.set("2026-10-01T09:00:00+00:00")
    m.add("newest entry", "devlog", scope="project", project_id="zm")
    m.add("other project entry", "devlog", scope="project", project_id="other")
    h.enable(["devlog"])
    b = m.brief(project_id="zm")
    assert [r.split("/")[-2] for r in b.sources] == ["2026-10-01", "2026-09-29"]
    assert "other project" not in b.text
    assert m.brief().sources == []  # no project, no devlog


# ============================================================ budget and truncation
def test_the_budget_is_never_exceeded_and_truncation_is_explicit(h):
    m = h.agent("codex", write_shared=True)
    for i in range(30):
        assert m.add(f"Rule number {i}: " + "keep every change small and reviewable. " * 4, "rule", name=f"r{i:02d}",
                     scope="shared").ok
    h.enable()
    for limit in (1, 10, 80, 300, 777, 2000, 8000):
        b = m.brief("x", max_chars=limit)
        assert len(b.text) <= limit and b.max_chars == limit, limit
    b = m.brief(max_chars=600)
    assert b.truncated is True and b.omitted["Rules"] == 30 - b.sections["Rules"] > 0
    assert len(b.text) <= 600 and b.as_dict()["omitted"] == b.omitted
    big = m.brief(max_chars=8000)
    assert big.truncated is False and big.sections["Rules"] == 30 and big.omitted == {}


def test_max_chars_defaults_from_settings_and_is_hard_capped(h):
    m = h.agent("codex", write_shared=True)
    seed(m)
    h.enable()
    assert m.brief().max_chars == 2000
    h.set("injection.max_chars", "500")
    assert m.brief().max_chars == 500
    assert m.brief(max_chars=3000).max_chars == 3000
    for bad in (0, -1, 8001, True, "5", 1.5):
        b = m.brief(max_chars=bad)
        assert (b.status, b.reason) == ("invalid", "invalid_max_chars"), bad


def test_invalid_input_never_raises(h):
    m = h.agent("codex")
    assert m.brief(task=5).reason == "invalid_task"
    assert m.brief(project_id="bad id").reason == "invalid_project_id"
    assert m.brief(preview="yes").reason == "invalid_preview"
    assert m.brief(task="x" * 5000).status in ("ok", "disabled")  # clipped, not an error


# ============================================================ never unapproved / never foreign
def test_proposals_forgotten_and_expired_items_never_appear(h):
    m = h.agent("codex", write_shared=True)
    seed(m)
    h.enable()
    pending = m.propose("Always deploy on fridays pending-secret-rule.", "rule", name="friday")
    assert pending.status == "proposed"
    rejected = m.propose("Rejected rule text zebra.", "rule", name="zebra")
    h.reviewer().reject(rejected.proposal_id)
    for task in (None, "deploy friday zebra"):
        for pv in (False, True):
            b = m.brief(task, preview=pv)
            assert "friday" not in b.text and "zebra" not in b.text and "mem://rule/friday" not in b.sources
    gone = m.recall("force push").hits[0].source_id
    assert m.forget(gone).ok
    assert "force push" not in m.brief().text
    h.set("learning.active_ttl_days", "5")
    approved = m.propose("Temporary rule about quokkas.", "rule", name="quokka")
    assert h.reviewer().approve(approved.proposal_id).ok
    assert "quokka" in m.brief().text
    h.env.clock.set("2026-10-20T09:00:00+00:00")
    assert "quokka" not in m.brief().text and "quokka" not in m.brief("quokka", preview=True).text


def test_other_profiles_private_items_never_appear_and_shared_ones_do(h):
    a = h.agent("codex", write_shared=True)
    b = h.agent("claude-code", write_shared=True)
    assert b.add("Private rule of claude-code about walruses.", "rule", name="walrus", scope="private").ok
    assert b.add("Shared rule about otters.", "rule", name="otter", scope="shared").ok
    assert a.add("Private rule of codex about lemurs.", "rule", name="lemur", scope="private").ok
    h.enable()
    for pv in (False, True):
        text = a.brief("walruses otters lemurs", preview=pv).text
        assert "walrus" not in text and "otters" in text and "lemurs" in text
    assert "lemurs" not in b.brief("lemurs").text


def test_an_unreadable_project_contributes_nothing(h):
    owner = h.agent("codex", write_projects=["secret-proj"])
    assert owner.add("Project rule about badgers.", "rule", name="badger", scope="project",
                     project_id="secret-proj").ok
    reader = h.agent("claude-code")
    h.enable()
    assert "badgers" not in reader.brief(project_id="secret-proj").text
    assert "badgers" in owner.brief(project_id="secret-proj").text


def test_the_full_loop_propose_pending_approve_brief(h):
    agent = h.agent("codex")  # no shared write grant: only the owner's approval can make it memory
    h.enable()
    result = agent.propose("Prefer small pull requests about falcons.", "rule", name="small-prs")
    assert result.status == "proposed"
    assert agent.recall("falcons").hits == [] and "falcons" not in agent.brief("falcons").text
    approved = h.reviewer().approve(result.proposal_id)
    assert approved.status == "approved"
    b = agent.brief("falcons")
    assert "mem://rule/small-prs" in b.sources and "falcons" in b.text


def test_context_is_unchanged_by_brief(h):
    m = h.agent("codex", write_shared=True)
    seed(m)
    before = m.context(max_chars=2000).as_dict()
    h.enable()
    m.brief("database")
    assert m.context(max_chars=2000).as_dict() == before
    json.dumps(m.brief("database").as_dict())  # JSON-safe
