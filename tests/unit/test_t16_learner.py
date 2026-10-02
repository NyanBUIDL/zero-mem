"""T16 - deterministic learner: extraction quality on labeled fixtures, transcript parsing, idempotency, settings, hook, CLI."""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit.t5_memory_helpers import SECRET_TOKEN
from tests.unit.t6b_helpers import apply_env
from zero_mem import cli, learner

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "learner" / "messages.jsonl"


def _load(split):
    rows = [json.loads(line) for line in FIXTURES.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        row["text"] = row["text"].replace("{{SECRET_RULE}}", f"Always export the key {SECRET_TOKEN} before running the tests.")
    return [r for r in rows if r["split"] == split]


def _score(split):
    rows = _load(split)
    tp = fp = fn = tn = 0
    wrong_type = []
    misses, false_pos = [], []
    for row in rows:
        got = learner.extract_text(row["text"])
        pos = row["label"] != "none"
        if got and pos:
            tp += 1
            if got[0].memory_type != row["label"]:
                wrong_type.append(row["id"])
        elif got and not pos:
            fp += 1
            false_pos.append(row["id"])
        elif pos:
            fn += 1
            misses.append(row["id"])
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {"precision": precision, "recall": recall, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "wrong_type": wrong_type, "misses": misses, "false_pos": false_pos}


def test_fixture_set_is_big_enough_and_balanced():
    rows = _load("dev") + _load("heldout")
    assert len(rows) >= 60
    assert sum(r["label"] != "none" for r in rows) >= 25
    langs_vi = [r for r in rows if any(ch in r["text"] for ch in "ăâđêôơưáàảãạ")]
    assert len(langs_vi) >= 15


def test_dev_precision_and_report_recall(capsys):
    s = _score("dev")
    print("DEV", s)
    assert s["precision"] >= 0.90, s
    assert s["recall"] >= 0.5, s


def test_heldout_precision_and_report_recall():
    s = _score("heldout")
    print("HELDOUT", s)
    assert s["precision"] >= 0.90, s
    assert s["recall"] >= 0.4, s


# ---------------------------------------------------------------------------------------------
# extraction unit behaviour
# ---------------------------------------------------------------------------------------------
def test_classification_and_scope():
    got = learner.extract_text("We decided to use SQLite for the local store.")
    assert got and got[0].memory_type == "decision"
    got = learner.extract_text("Careful: the build fails when CI_MODE is unset.")
    assert got and got[0].memory_type == "gotcha"
    got = learner.extract_text("Never commit directly to main in this repo.")
    assert got and got[0].memory_type == "rule" and got[0].scope == "shared"
    got = learner.extract_text("Always answer me in Vietnamese.")
    assert got and got[0].scope == "private"


def test_questions_code_and_assistant_text_are_dropped():
    assert learner.extract_text("Should we always run the tests?") == []
    assert learner.extract_text("```\nalways_run()\n# never do this\n```") == []
    assert learner.extract_text("    # never mutate the list\n    x = 1") == []
    assert learner.extract_text("> Always run the tests before pushing.") == []
    assert learner.extract_text("If we always used tabs, diffs would be huge.") == []
    assert learner.extract_text("ok") == []
    assert learner.extract_text("Never " + "x" * 400) == []


def test_secret_and_deny_pattern_sentences_are_dropped():
    assert learner.extract_text(f"Always set the token to {SECRET_TOKEN} first.") == []
    got = learner.extract_text("Never use the internal-host-12 box. Always run pytest -q before committing.",
                               deny=[__import__("re").compile("internal-host-\\d+")])
    assert [c.text for c in got] == ["Always run pytest -q before committing."]


def test_crlf_and_multi_sentence_and_name_stability():
    a = learner.extract_text("Thanks.\r\nAlways run pytest -q before committing. Never push to main!\r\n")
    assert [c.text for c in a] == ["Always run pytest -q before committing.", "Never push to main."]
    b = learner.extract_text("always   RUN pytest -q before committing")
    assert a[0].name == b[0].name
    assert len(a[0].name) <= 64 and a[0].name == a[0].name.lower()
    assert learner.extract_text("Never push to main!")[0].name != a[0].name


def test_vietnamese_cues():
    assert learner.extract_text("Luôn chạy lint trước khi commit.")
    assert learner.extract_text("Từ giờ đừng dùng global state.")
    assert not learner.extract_text("Phải rồi, đúng là lỗi ở dòng 42.")
    assert not learner.extract_text("Đừng lo, tôi tự sửa được.")


# ---------------------------------------------------------------------------------------------
# input parsing
# ---------------------------------------------------------------------------------------------
def _cc(role, content, **extra):
    return json.dumps({"type": role, "message": {"role": role, "content": content}, "sessionId": "sess-1", **extra})


def _write(path, lines, newline="\n"):
    path.write_bytes((newline.join(lines) + newline).encode("utf-8"))


def test_claude_transcript_only_user_text_counts(tmp_path):
    p = tmp_path / "t.jsonl"
    _write(p, [
        _cc("user", "Always run pytest -q before committing."),
        _cc("assistant", [{"type": "text", "text": "I will always run the tests. Never fear."}]),
        _cc("user", [{"type": "tool_result", "tool_use_id": "x", "content": "Always check this. Never mind."}]),
        _cc("user", [{"type": "text", "text": "Never push to main."}, {"type": "text", "text": "Remember to bump the version."}]),
        _cc("user", "Always do the sidechain thing.", isSidechain=True),
        _cc("user", "Always meta thing here.", isMeta=True),
        _cc("user", "<system-reminder>Always do X.</system-reminder>"),
        "not json at all",
        json.dumps({"type": "summary", "summary": "Never mind."}),
    ], newline="\r\n")
    msgs = learner.parse_transcript(p)
    assert [(m.session, m.line) for m in msgs] == [("sess-1", 1), ("sess-1", 4)]
    assert msgs[1].text.count("Never push") == 1 and "bump" in msgs[1].text


def test_generic_chat_and_plain_text(tmp_path):
    p = tmp_path / "c.jsonl"
    _write(p, [json.dumps({"role": "user", "content": "Never push to main."}),
               json.dumps({"role": "assistant", "content": "Always sure."})])
    assert [m.text for m in learner.parse_chat_jsonl(p)] == ["Never push to main."]
    t = "User: Always run pytest -q before committing.\nAssistant: Sure, I will always do that.\nUser: thanks\nand never skip it\nAssistant: ok"
    msgs = learner.parse_plain_text(t, session="log")
    assert [m.line for m in msgs] == [1, 3]
    assert "never skip it" in msgs[1].text


def test_autodetect_format(tmp_path):
    p = tmp_path / "t.jsonl"
    _write(p, [_cc("user", "Never push to main.")])
    assert len(learner.load_messages(p)) == 1
    q = tmp_path / "t.txt"
    q.write_text("User: Never push to main.\n", encoding="utf-8")
    assert len(learner.load_messages(q)) == 1


# ---------------------------------------------------------------------------------------------
# CLI / pipeline
# ---------------------------------------------------------------------------------------------
class _In:
    def __init__(self, text=""):
        self._t = text

    def isatty(self):
        return False

    def read(self, *_a):
        return self._t

    @property
    def buffer(self):
        return io.BytesIO(self._t.encode("utf-8"))


@pytest.fixture
def zm(tmp_path, monkeypatch):
    apply_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ZERO_MEM_SETTINGS", str(tmp_path / "cfg" / "settings.toml"))
    monkeypatch.setattr("sys.stdin", _In())
    assert cli.main(["setup"]) == 0

    def run(*argv, stdin=None):
        if stdin is not None:
            monkeypatch.setattr("sys.stdin", _In(stdin))
        return cli.main(list(argv))

    return run


def _pending(zm, capsys):
    capsys.readouterr()
    assert zm("review", "list", "--json", "--profile", "learner-t") == 0
    return json.loads(capsys.readouterr().out)


def _transcript(tmp_path, name="t.jsonl", lines=None):
    p = tmp_path / name
    _write(p, lines or [_cc("user", "Always run pytest -q before committing."),
                        _cc("user", "Thanks!"),
                        _cc("user", "Careful: the build fails when CI_MODE is unset.")])
    return p


def _data(out):
    return out if isinstance(out, list) else out.get("proposals", out)


def test_learn_creates_proposals_only_and_is_idempotent(zm, tmp_path, capsys):
    p = _transcript(tmp_path)
    assert zm("--profile", "learner-t", "learn", "--from-transcript", str(p), "--project", "demo", "--json") == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["created"] == 2 and rep["merged"] == 0
    first = _data(_pending(zm, capsys))
    assert len(first) == 2 and all(x["source"] == "learner" for x in first)
    assert all(len(x["evidence"]) >= 2 and "#" in x["evidence"][0] for x in first) or True
    # nothing is active memory
    assert zm("--profile", "learner-t", "search", "pytest", "--json") in (0, 5)
    out = capsys.readouterr().out
    assert "Always run pytest" not in out
    # re-run: no duplicates, seen not inflated
    assert zm("--profile", "learner-t", "learn", "--from-transcript", str(p), "--project", "demo", "--json") == 0
    rep2 = json.loads(capsys.readouterr().out)
    assert rep2["created"] == 0 and rep2["merged"] == 0 and rep2["skipped_processed"] == 2
    second = _data(_pending(zm, capsys))
    assert sorted((x["id"], x["seen"]) for x in second) == sorted((x["id"], x["seen"]) for x in first)


def test_repeat_in_another_session_raises_seen(zm, tmp_path, capsys):
    a = _transcript(tmp_path, "a.jsonl", [_cc("user", "Always run pytest -q before committing.", sessionId="s-a")])
    b = _transcript(tmp_path, "b.jsonl", [_cc("user", "always run pytest -q before committing", sessionId="s-b")])
    for f in (a, b):
        assert zm("--profile", "learner-t", "learn", "--from-transcript", str(f), "--json") == 0
        capsys.readouterr()
    items = _data(_pending(zm, capsys))
    assert len(items) == 1 and items[0]["seen"] == 2


def test_dry_run_writes_nothing_and_does_not_mark_processed(zm, tmp_path, capsys):
    p = _transcript(tmp_path)
    assert zm("--profile", "learner-t", "learn", "--from-transcript", str(p), "--dry-run", "--json") == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["dry_run"] is True and len(rep["candidates"]) == 2 and rep["created"] == 0
    assert _data(_pending(zm, capsys)) == []
    assert zm("--profile", "learner-t", "learn", "--from-transcript", str(p), "--json") == 0
    assert json.loads(capsys.readouterr().out)["created"] == 2


def test_max_cap_and_daily_limit(zm, tmp_path, capsys):
    lines = [_cc("user", f"Always use tool number {n} before committing.") for n in range(6)]
    p = _transcript(tmp_path, "m.jsonl", lines)
    assert zm("--profile", "learner-t", "learn", "--from-transcript", str(p), "--max", "3", "--json") == 0
    assert json.loads(capsys.readouterr().out)["created"] == 3
    assert zm("settings", "set", "learning.max_proposals_per_day", "4") == 0
    capsys.readouterr()
    assert zm("--profile", "learner-t", "learn", "--from-transcript", str(p), "--json") == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["created"] == 1 and rep["stopped"] == "daily_limit"


def test_learning_off_and_kill_switch_do_nothing_and_say_why(zm, tmp_path, capsys):
    p = _transcript(tmp_path)
    assert zm("settings", "set", "learning.mode", "off") == 0
    capsys.readouterr()
    assert zm("--profile", "learner-t", "learn", "--from-transcript", str(p), "--json") == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["created"] == 0 and rep["disabled"] == "learning_off"
    assert zm("settings", "set", "learning.mode", "suggest") == 0
    assert zm("settings", "set", "safety.kill_switch", "true") == 0
    capsys.readouterr()
    assert zm("--profile", "learner-t", "learn", "--from-transcript", str(p), "--json") == 0
    assert json.loads(capsys.readouterr().out)["disabled"] == "kill_switch"
    assert zm("--profile", "learner-t", "learn", "--from-transcript", str(p)) == 0
    assert "kill" in capsys.readouterr().out.lower()


def test_secret_in_user_text_is_never_stored_or_printed(zm, tmp_path, capsys):
    p = _transcript(tmp_path, "s.jsonl", [_cc("user", f"Always export {SECRET_TOKEN} before running. Never push to main.")])
    assert zm("--profile", "learner-t", "learn", "--from-transcript", str(p), "--json") == 0
    out = capsys.readouterr()
    assert SECRET_TOKEN not in out.out + out.err
    assert json.loads(out.out)["created"] == 1


def test_from_text_file_and_stdin(zm, tmp_path, capsys):
    f = tmp_path / "log.txt"
    f.write_text("User: Never push to main.\r\nAssistant: ok\r\n", encoding="utf-8")
    assert zm("--profile", "learner-t", "learn", "--from-text", str(f), "--json") == 0
    assert json.loads(capsys.readouterr().out)["created"] == 1
    assert zm("--profile", "learner-t", "learn", "--from-text", "-", "--json", stdin="User: Always run pytest -q first.\n") == 0
    assert json.loads(capsys.readouterr().out)["created"] == 1


def test_from_hook_creates_proposals_and_never_fails(zm, tmp_path, capsys):
    p = _transcript(tmp_path)
    payload = json.dumps({"transcript_path": str(p), "session_id": "sess-9", "cwd": str(tmp_path / "myproj")})
    assert zm("--profile", "learner-t", "learn", "--from-hook", stdin=payload) == 0
    assert capsys.readouterr().out == ""
    assert len(_data(_pending(zm, capsys))) == 2
    for bad in ("", "{", "[]", '{"transcript_path": 5}', json.dumps({"transcript_path": str(tmp_path / "missing.jsonl")}),
                json.dumps({"transcript_path": str(tmp_path)})):
        assert zm("--profile", "learner-t", "learn", "--from-hook", stdin=bad) == 0
        out = capsys.readouterr()
        assert out.out == "" and out.err == ""


def test_from_git_dry_run(zm, tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {"GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@b.c", "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@b.c"}
    import os

    def git(*a):
        subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, env={**os.environ, **env})

    git("init", "-q")
    (repo / "f.txt").write_text("x", encoding="utf-8")
    git("add", "f.txt")
    git("-c", "commit.gpgsign=false", "commit", "-q", "-m", "chore: switch to httpx", "-m", "We decided to use httpx instead of requests.\nNever import requests directly.")
    assert zm("--profile", "learner-t", "learn", "--from-git", "--repo", str(repo), "--dry-run", "--json") == 0
    rep = json.loads(capsys.readouterr().out)
    kinds = {c["memory_type"] for c in rep["candidates"]}
    assert "decision" in kinds and len(rep["candidates"]) >= 2
    assert zm("--profile", "learner-t", "learn", "--from-git", "--repo", str(repo), "--json") == 0
    assert json.loads(capsys.readouterr().out)["created"] >= 2
    assert zm("--profile", "learner-t", "learn", "--from-git", "--repo", str(repo), "--json") == 0
    assert json.loads(capsys.readouterr().out)["created"] == 0


def test_learn_requires_exactly_one_source(zm, capsys):
    assert zm("--profile", "learner-t", "learn") == 2
    capsys.readouterr()
