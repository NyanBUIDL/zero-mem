"""T15 - ``zero-mem brief`` and ``zero-mem eval ...`` (in process, isolated data root and settings file)."""
from __future__ import annotations

import json

import pytest

from tests.unit.t6b_helpers import apply_env
from zero_mem import cli


@pytest.fixture
def zm(tmp_path, monkeypatch):
    apply_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ZERO_MEM_SETTINGS", str(tmp_path / "cfg" / "settings.toml"))
    monkeypatch.setattr("sys.stdin", _NoTty())
    assert cli.main(["setup"]) == 0
    assert cli.main(["agents", "add", "codex"]) == 0
    assert cli.main(["agents", "grant-write", "codex", "--space", "ks-shared", "--yes"]) == 0

    def run(*argv):
        return cli.main(list(argv))

    return run


class _NoTty:
    def isatty(self):
        return False

    def read(self, *_a):
        return ""


def add(zm, text, mtype, name):
    assert zm("--profile", "codex", "add", text, "--type", mtype, "--scope", "shared", "--name", name) == 0


def test_brief_is_silent_and_explains_itself_while_injection_is_off(zm, capsys):
    add(zm, "Never force push to main.", "rule", "nofp")
    capsys.readouterr()
    assert zm("--profile", "codex", "brief", "--task", "push") == 0
    out = capsys.readouterr()
    assert out.out == "" and "injection_disabled" in out.err and "zero-mem settings set injection.enabled true" in out.err
    assert zm("--profile", "codex", "brief", "--json") == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["status"] == "disabled" and doc["reason"] == "injection_disabled" and doc["text"] == ""


def test_brief_prints_the_text_when_enabled_and_the_preview_when_not(zm, capsys):
    add(zm, "Never force push to main.", "rule", "nofp")
    add(zm, "Retry the sqlite writer when the database is busy.", "gotcha", "busy")
    capsys.readouterr()
    assert zm("--profile", "codex", "brief", "--task", "sqlite database busy", "--preview") == 0
    pv = capsys.readouterr()
    assert "mem://gotcha/busy" in pv.out and "mem://rule/nofp" in pv.out
    assert "preview" in pv.err and "injection_disabled" in pv.err
    assert zm("settings", "set", "injection.enabled", "true") == 0
    capsys.readouterr()
    assert zm("--profile", "codex", "brief", "--task", "sqlite database busy", "--max-chars", "500") == 0
    live = capsys.readouterr()
    assert live.out.startswith("## Rules\n- mem://rule/nofp") and live.err == "" and len(live.out.rstrip("\n")) <= 500
    assert zm("--profile", "codex", "brief", "--task", "sqlite database busy", "--json") == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["status"] == "ok" and doc["enabled"] is True and "mem://rule/nofp" in doc["sources"]
    assert zm("--profile", "codex", "brief", "--max-chars", "9000") == 2
    assert zm("--profile", "codex", "brief", "--project", "bad id") == 2
    capsys.readouterr()


# ================================================================ eval
def write_cases(tmp_path, *rows):
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return str(path)


def test_eval_init_writes_a_valid_example_and_refuses_to_overwrite(zm, tmp_path, capsys):
    target = tmp_path / "ex" / "cases.jsonl"
    assert zm("eval", "init", str(target)) == 0
    assert target.exists() and "must_include" in target.read_text(encoding="utf-8")
    assert zm("eval", "init", str(target)) == 2 and "exists" in capsys.readouterr().err
    assert zm("eval", "init", str(target), "--force") == 0
    assert zm("--profile", "codex", "eval", "run", str(target), "--json") in (0, 1)  # parses and runs


def test_eval_run_reports_pass_fail_missing_forbidden_budget_and_exit_code(zm, tmp_path, capsys):
    add(zm, "Never force push to main.", "rule", "nofp")
    add(zm, "Retry the sqlite writer when the database is busy.", "gotcha", "busy")
    path = write_cases(
        tmp_path,
        {"id": "db", "task": "sqlite database busy", "must_include": ["mem://gotcha/busy", "force push"],
         "must_not_include": ["kangaroo"], "max_chars": 600},
        {"id": "missing", "task": "paint the fence", "must_include": ["mem://gotcha/busy"],
         "must_not_include": ["force push"]},
    )
    capsys.readouterr()
    assert zm("--profile", "codex", "eval", "run", path, "--json") == 1
    doc = json.loads(capsys.readouterr().out)
    by_id = {c["id"]: c for c in doc["cases"]}
    assert by_id["db"]["passed"] is True and by_id["db"]["missing"] == [] and by_id["db"]["max_chars"] == 600
    assert by_id["db"]["chars"] <= 600 and by_id["db"]["injection_enabled"] is False  # injection off: reported apart
    assert by_id["missing"]["passed"] is False
    assert by_id["missing"]["missing"] == ["mem://gotcha/busy"] and by_id["missing"]["forbidden"] == ["force push"]
    s = doc["summary"]
    assert (s["cases"], s["passed"], s["failed"]) == (2, 1, 1)
    assert s["must_include_total"] == 3 and s["must_include_found"] == 2 and s["recall"] == round(2 / 3, 4)
    assert s["forbidden_hits"] == 1 and s["injection_off_cases"] == 2 and s["truncated"] == 0
    assert s["latency_ms_max"] >= 0
    assert zm("--profile", "codex", "eval", "run", path) == 1
    text = capsys.readouterr().out
    assert "PASS db" in text and "FAIL missing" in text and "missing: mem://gotcha/busy" in text
    assert "injection is OFF" in text


def test_a_worked_example_adding_the_right_rule_moves_a_case_from_fail_to_pass(zm, tmp_path, capsys):
    add(zm, "Never force push to main.", "rule", "nofp")
    path = write_cases(tmp_path, {"id": "migrations", "task": "write a database migration",
                                  "must_include": ["mem://rule/migrations-reversible"]})
    assert zm("--profile", "codex", "eval", "run", path) == 1
    add(zm, "Every database migration must be reversible and tested on a copy.", "rule", "migrations-reversible")
    capsys.readouterr()
    assert zm("--profile", "codex", "eval", "run", path) == 0
    assert "PASS migrations" in capsys.readouterr().out


def test_eval_files_are_validated_strictly(zm, tmp_path, capsys):
    bad = [
        ('{"id": "a", "task": "x", "extra": 1}', "unknown"),
        ('{"task": "x"}', "id"),
        ('{"id": "a"}', "task"),
        ('{"id": "a", "task": "x", "must_include": "str"}', "must_include"),
        ('{"id": "a", "task": "x", "max_chars": 9000}', "max_chars"),
        ('{"id": "a", "task": "x", "profile": "bad id"}', "profile"),
        ("not json", "line 1"),
    ]
    for line, needle in bad:
        p = tmp_path / "bad.jsonl"
        p.write_text(line + "\n", encoding="utf-8")
        assert zm("eval", "run", str(p)) == 2, line
        assert needle in capsys.readouterr().err, line
    dup = tmp_path / "dup.jsonl"
    dup.write_text('{"id":"a","task":"x"}\n{"id":"a","task":"y"}\n', encoding="utf-8")
    assert zm("eval", "run", str(dup)) == 2 and "duplicate" in capsys.readouterr().err
    assert zm("eval", "run", str(tmp_path / "nope.jsonl")) == 2
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n", encoding="utf-8")
    assert zm("eval", "run", str(empty)) == 2


def test_the_per_case_profile_and_project_are_honoured(zm, tmp_path, capsys):
    assert zm("agents", "add", "other") == 0
    assert zm("--profile", "other", "add", "Private rule about walruses.", "--type", "rule", "--name", "wal") == 0
    path = write_cases(
        tmp_path,
        {"id": "mine", "profile": "other", "task": "walruses", "must_include": ["walruses"]},
        {"id": "not-mine", "profile": "codex", "task": "walruses", "must_not_include": ["walruses"]})
    capsys.readouterr()
    assert zm("eval", "run", path) == 0, capsys.readouterr().out


def test_history_is_appended_privately_bounded_and_printed(zm, tmp_path, capsys, monkeypatch):
    from zero_mem import eval_harness

    add(zm, "Never force push to main.", "rule", "nofp")
    path = write_cases(tmp_path, {"id": "a", "task": "push", "must_include": ["mem://rule/nofp"]})
    assert zm("--profile", "codex", "eval", "run", path) == 0
    assert zm("--profile", "codex", "eval", "run", path) == 0
    history = tmp_path / "data" / "eval-history.jsonl"
    rows = [json.loads(x) for x in history.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2 and rows[0]["cases"] == 1 and rows[0]["file"] == "cases.jsonl"
    assert "push" not in history.read_text(encoding="utf-8")  # task text is never stored
    assert {"at", "passed", "failed", "recall", "forbidden_hits", "truncated", "latency_ms_avg"} <= set(rows[0])
    capsys.readouterr()
    assert zm("eval", "history") == 0
    shown = capsys.readouterr().out
    assert shown.count("cases.jsonl") == 2 and "recall" in shown
    assert zm("eval", "history", "--json") == 0
    assert len(json.loads(capsys.readouterr().out)["runs"]) == 2
    monkeypatch.setattr(eval_harness, "HISTORY_MAX_LINES", 6)
    monkeypatch.setattr(eval_harness, "HISTORY_KEEP_LINES", 3)
    for _ in range(8):
        assert zm("--profile", "codex", "eval", "run", path) == 0
    kept = history.read_text(encoding="utf-8").splitlines()
    assert 3 <= len(kept) <= 6
    history.write_text("garbage\n" + kept[-1] + "\n", encoding="utf-8")
    capsys.readouterr()
    assert zm("eval", "history") == 0 and capsys.readouterr().out.count("cases.jsonl") == 1  # corrupt lines skipped


def test_history_with_nothing_recorded_is_not_an_error(zm, capsys):
    assert zm("eval", "history") == 0
    assert "no eval runs" in capsys.readouterr().out


def test_eval_safety_builds_a_temp_store_and_passes_every_invariant(zm, tmp_path, capsys):
    before = sorted(p.name for p in (tmp_path / "data").iterdir())
    assert zm("eval", "safety", "--json") == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["passed"] is True and doc["failed"] == 0
    names = {c["name"] for c in doc["checks"]}
    for needle in ("pending", "rejected", "expired", "forgotten", "kill_switch", "injection_disabled",
                   "other_profile", "budget", "superseded", "settings_invalid", "deterministic"):
        assert any(needle in n for n in names), needle
    assert all(c["ok"] for c in doc["checks"])
    assert sorted(p.name for p in (tmp_path / "data").iterdir()) == before  # the real store was not touched
    assert zm("eval", "safety") == 0 and "PASS" in capsys.readouterr().out


def test_eval_safety_fails_when_an_invariant_is_broken(zm, capsys, monkeypatch):
    from zero_mem.memory import Memory

    monkeypatch.setattr(Memory, "_expired_sources", lambda self: frozenset())
    assert zm("eval", "safety", "--json") == 1
    doc = json.loads(capsys.readouterr().out)
    assert doc["passed"] is False and any(not c["ok"] and "expired" in c["name"] for c in doc["checks"])
    monkeypatch.undo()
    from zero_mem import learning_settings as ls

    monkeypatch.setattr(ls, "resolve_injection", lambda *a, **k: ls.InjectionPolicy(True, 2000, ("rule",)))
    assert zm("eval", "safety", "--json") == 1
    doc = json.loads(capsys.readouterr().out)
    assert any(not c["ok"] and ("kill_switch" in c["name"] or "disabled" in c["name"]) for c in doc["checks"])
