"""T14 - ``zero-mem settings | propose | review`` CLI (in process, isolated data root and settings file)."""
from __future__ import annotations

import json

import pytest

from tests.unit.t5_memory_helpers import SECRET_TOKEN
from tests.unit.t6b_helpers import apply_env
from zero_mem import cli, commands_doctor


@pytest.fixture
def zm(tmp_path, monkeypatch):
    apply_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ZERO_MEM_SETTINGS", str(tmp_path / "cfg" / "settings.toml"))
    monkeypatch.setattr("sys.stdin", _NoTty())
    assert cli.main(["setup"]) == 0

    def run(*argv):
        return cli.main(list(argv))

    return run


class _NoTty:
    def isatty(self):
        return False

    def read(self, *_a):
        return ""


def out_json(capsys):
    return json.loads(capsys.readouterr().out)


def test_settings_show_set_unset_validate_path(zm, capsys, tmp_path):
    assert zm("settings", "path") == 0
    assert capsys.readouterr().out.strip() == (tmp_path / "cfg" / "settings.toml").as_posix()
    assert zm("settings", "show", "--json") == 0
    doc = out_json(capsys)
    assert doc["exists"] is False and doc["valid"] is True and doc["settings"]["learning"]["mode"] == "suggest"
    assert doc["settings"]["injection"]["enabled"] is False
    assert zm("settings", "set", "learning.mode", "off") == 0
    assert zm("settings", "set", "injection.projects.my.proj.max_chars", "500", "--json") == 0
    capsys.readouterr()
    assert zm("settings", "show") == 0
    text = capsys.readouterr().out
    assert "learning.mode = off" in text and "injection.projects.my.proj.max_chars = 500" in text
    assert zm("settings", "validate") == 0
    assert zm("settings", "unset", "learning.mode") == 0
    assert zm("settings", "unset", "learning.mode") == 5
    capsys.readouterr()
    assert zm("settings", "set", "learning.mode", "loud") == 2
    assert "invalid setting" in capsys.readouterr().err
    assert zm("settings", "set", "injection.max_chars", "8001") == 2
    assert zm("settings", "set", "nope", "1") == 2


def test_validate_and_doctor_report_an_unusable_file_and_fail_safe(zm, capsys, tmp_path):
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "settings.toml").write_text("[learning\n", encoding="utf-8")
    capsys.readouterr()
    assert zm("settings", "validate") == 2
    assert "Fail-safe" in capsys.readouterr().err
    assert zm("settings", "show", "--json") == 0
    shown = out_json(capsys)
    assert shown["valid"] is False and shown["effective_mode"] == "off"
    check = {c["id"]: c for c in commands_doctor.collect()["checks"]}["learning_settings"]
    assert check["status"] == "WARN" and "fail-safe" in check["message"]
    assert commands_doctor.collect()["overall"] == "READY"  # a warning, never a blocker
    assert zm("--profile", "codex", "propose", "x", "--type", "rule") == 3  # learning off while fail-safe
    assert zm("--profile", "codex", "search", "anything") in (0, 5)  # reads never crash


def test_doctor_is_pass_with_no_settings_file(zm):
    check = {c["id"]: c for c in commands_doctor.collect()["checks"]}["learning_settings"]
    assert check["status"] == "PASS" and "defaults" in check["message"]


def test_propose_review_approve_flow(zm, capsys):
    capsys.readouterr()
    assert zm("--profile", "codex", "propose", "Run", "the", "linter", "first.", "--type", "rule", "--name", "lint",
              "--evidence", "pr#1", "--json") == 0
    prop = out_json(capsys)
    pid = prop["proposal_id"]
    assert prop["status"] == "proposed"
    assert zm("--profile", "codex", "propose", "run the LINTER first.", "--type", "rule", "--name", "lint",
              "--evidence", "pr#2", "--json") == 0
    assert out_json(capsys)["status"] == "merged"
    capsys.readouterr()
    assert zm("--profile", "codex", "search", "linter", "--json") in (0, 5)
    assert out_json(capsys)["hits"] == []  # a pending proposal is never a search hit
    assert zm("--profile", "codex", "context", "--json") == 0
    assert "linter" not in json.dumps(out_json(capsys))
    assert zm("review", "list") == 0
    listing = capsys.readouterr().out
    assert pid in listing and "pending" in listing and "x2" in listing
    assert zm("review", "list", "--status", "approved", "--json") == 0
    assert out_json(capsys)["count"] == 0
    assert zm("review", "list", "--profile", "hermes", "--json") == 0
    assert out_json(capsys)["count"] == 0
    assert zm("review", "show", pid) == 0
    shown = capsys.readouterr().out
    assert "codex" in shown and "pr#1, pr#2" in shown and "history" in shown
    assert zm("review", "show", "p-000000000000") == 5
    capsys.readouterr()
    # approving needs --yes (no TTY): refused, nothing committed
    assert zm("review", "approve", pid) == 2
    assert "--yes" in capsys.readouterr().err
    assert zm("review", "list", "--status", "approved", "--json") == 0
    assert out_json(capsys)["count"] == 0
    assert zm("review", "approve", pid, "--edit", "Run the linter before committing.", "--yes", "--json") == 0
    done = out_json(capsys)
    assert done["status"] == "approved" and done["external_ref"] == "mem://rule/lint"
    assert zm("agents", "add", "hermes") == 0
    capsys.readouterr()
    assert zm("--profile", "hermes", "search", "linter", "--json") == 0
    hits = out_json(capsys)["hits"]
    assert hits and hits[0]["external_ref"] == "mem://rule/lint" and "before committing" in hits[0]["text"]
    assert zm("review", "approve", pid, "--yes") == 2  # already approved
    capsys.readouterr()
    assert zm("review", "show", pid, "--json") == 0
    assert out_json(capsys)["final_text"].startswith("Run the linter before")
    # revoke needs --yes too
    capsys.readouterr()
    assert zm("review", "revoke", "mem://rule/lint") == 2
    assert zm("review", "revoke", "mem://rule/lint", "--yes", "--reason", "obsolete") == 0
    capsys.readouterr()
    assert zm("--profile", "hermes", "search", "linter", "--json") in (0, 5)
    assert out_json(capsys)["hits"] == []
    assert zm("review", "revoke", "mem://rule/none", "--yes") == 5


def test_propose_rejections_map_to_exit_codes_and_messages(zm, capsys):
    capsys.readouterr()
    assert zm("--profile", "codex", "propose", f"key {SECRET_TOKEN}", "--type", "gotcha") == 4
    err = capsys.readouterr().err
    assert "credential" in err and SECRET_TOKEN not in err
    assert zm("settings", "set", "safety.deny_patterns", '["forbidden-\\\\w+"]') == 0
    assert zm("--profile", "codex", "propose", "about forbidden-thing", "--type", "rule") == 3
    assert "deny pattern" in capsys.readouterr().err
    assert zm("settings", "set", "safety.kill_switch", "true") == 0
    capsys.readouterr()
    assert zm("--profile", "codex", "propose", "anything", "--type", "rule", "--json") == 3
    assert out_json(capsys)["reason"] == "kill_switch"
    assert zm("--profile", "codex", "propose", "x", "--scope", "project") == 2  # project id missing -> invalid


def test_reject_and_expire_commands(zm, capsys, monkeypatch):
    capsys.readouterr()
    assert zm("--profile", "codex", "propose", "A rule", "--source", "user", "--json") == 0
    pid = out_json(capsys)["proposal_id"]
    assert zm("review", "reject", pid, "--reason", "nope") == 0
    capsys.readouterr()
    assert zm("review", "reject", pid) == 2
    capsys.readouterr()
    assert zm("review", "list", "--status", "rejected", "--json") == 0
    assert out_json(capsys)["proposals"][0]["reason"] == "nope"
    assert zm("review", "expire") == 0
    assert "expired 0 pending" in capsys.readouterr().out
    assert zm("review", "expire", "--json") == 0
    assert out_json(capsys)["status"] == "expired"
