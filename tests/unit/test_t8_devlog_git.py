"""T8 - ``zero-mem devlog --from-git``: recent git commits (short hash, subject, files changed) become ONE devlog
source per day, deterministically and without any LLM; running it again is a no-op, a new commit the same day is a new
version of that day's source, and the whole thing is safe to call from an agent hook after every session.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

from tests.unit.t6b_helpers import SECRET_TOKEN, apply_env, grep_tree, registry_lines
from zero_mem import cli
from zero_mem.memory import Memory
from zero_mem.memory_layout import Layout
from zero_mem.provisioning import Provisioner

GIT_ENV_KEYS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE")


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(list(argv))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def jrun(*argv):
    code, out, err = run_cli(*argv)
    return code, (json.loads(out) if out.strip() else None), err


class Repo:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.n = 0

    def git(self, *args, when: str | None = None) -> str:
        env = {k: v for k, v in os.environ.items() if k not in GIT_ENV_KEYS}
        env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_AUTHOR_NAME": "T8", "GIT_AUTHOR_EMAIL": "t8@example.invalid",
                    "GIT_COMMITTER_NAME": "T8", "GIT_COMMITTER_EMAIL": "t8@example.invalid"})
        if when:
            env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when
        done = subprocess.run(["git", *args], cwd=self.path, env=env, capture_output=True, text=True, check=True)
        return done.stdout.strip()

    def commit(self, subject: str, files=("a.txt",), when: str = "2026-09-28T12:00:00+0000") -> str:
        for name in files:
            target = self.path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            self.n += 1
            target.write_text(f"change {self.n}\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", subject, when=when)
        return self.git("rev-parse", "--short", "HEAD")


@pytest.fixture
def home(tmp_path, monkeypatch):
    apply_env(monkeypatch, tmp_path)
    layout = Layout.resolve(None)
    layout.ensure()
    prov = Provisioner(layout, operator="tester")
    prov.add_agent("claude-code")
    prov.grant_write("claude-code", project="proj", basis="owner approved")
    return tmp_path


@pytest.fixture
def repo(tmp_path):
    return Repo(tmp_path / "work" / "proj")


def devlog(repo, *extra, project="proj"):
    args = ["--profile", "claude-code", "--json", "devlog", "--from-git", "--repo", str(repo.path), "--days", "36500"]
    if project:
        args += ["--project", project]
    return jrun(*args, *extra)


def recall_all(project="proj", query="commits"):
    with Memory.open("claude-code") as m:
        return [h.as_dict() for h in m.recall(query, memory_types=["devlog"], limit=20, project_id=project)]


def test_each_day_becomes_one_devlog_source_with_hash_subject_and_files(home, repo):
    a = repo.commit("feat: add widgets", ["src/widgets.py", "tests/test_widgets.py"], when="2026-09-28T09:00:00+0000")
    b = repo.commit("fix: typo in readme", ["README.md"], when="2026-09-29T10:00:00+0000")
    c = repo.commit("chore: bump", ["pyproject.toml"], when="2026-09-29T18:30:00+0000")
    code, res, err = devlog(repo)
    assert code == 0, err
    assert [d["day"] for d in res["days"]] == ["2026-09-28", "2026-09-29"]
    assert [d["commits"] for d in res["days"]] == [1, 2] and res["counts"]["created"] == 2
    assert [d["ref"] for d in res["days"]] == ["mem://devlog/proj/2026-09-28", "mem://devlog/proj/2026-09-29"]
    hits = {h["external_ref"]: h["text"] for h in recall_all()}
    day1, day2 = hits["mem://devlog/proj/2026-09-28"], hits["mem://devlog/proj/2026-09-29"]
    assert a in day1 and "feat: add widgets" in day1 and "src/widgets.py" in day1 and "tests/test_widgets.py" in day1
    assert b in day2 and c in day2 and "fix: typo in readme" in day2 and "chore: bump" in day2
    assert day2.index(c) < day2.index(b)  # newest first within the day
    assert all(h["memory_type"] == "devlog" and h["scope"] == "project" for h in recall_all())


def test_running_it_again_changes_nothing_and_a_new_commit_updates_only_its_day(home, repo):
    repo.commit("feat: one", ["a.py"], when="2026-09-28T09:00:00+0000")
    repo.commit("feat: two", ["b.py"], when="2026-09-29T09:00:00+0000")
    assert devlog(repo)[0] == 0
    lines = len(registry_lines(home / "data"))
    code, res, _ = devlog(repo)
    assert code == 0 and res["counts"]["unchanged"] == 2 and res["counts"]["created"] == 0
    assert len(registry_lines(home / "data")) == lines  # no new version, no new blob
    repo.commit("fix: three", ["c.py"], when="2026-09-29T20:00:00+0000")
    code, res, _ = devlog(repo)
    assert [d["status"] for d in res["days"]] == ["unchanged", "updated"]
    texts = [h["text"] for h in recall_all() if h["external_ref"].endswith("2026-09-29")]
    assert texts and "fix: three" in texts[0] and "feat: two" in texts[0]


def test_since_a_ref_writes_only_the_touched_days_but_each_one_complete(home, repo):
    first = repo.commit("feat: day one", ["a.py"], when="2026-09-28T09:00:00+0000")
    repo.commit("feat: morning of day two", ["b.py"], when="2026-09-29T08:00:00+0000")
    mid = repo.commit("feat: noon of day two", ["c.py"], when="2026-09-29T12:00:00+0000")
    repo.commit("feat: day three", ["d.py"], when="2026-09-30T09:00:00+0000")
    code, res, err = devlog(repo, "--since", mid)
    assert code == 0, err
    assert [d["day"] for d in res["days"]] == ["2026-09-30"]  # only what is NEWER than the ref
    code, res, _ = devlog(repo, "--since", first)
    assert [d["day"] for d in res["days"]] == ["2026-09-29", "2026-09-30"]
    day2 = [h["text"] for h in recall_all() if h["external_ref"].endswith("2026-09-29")][0]
    assert "morning of day two" in day2 and "noon of day two" in day2  # the day is complete, not cut at the ref


def test_the_default_window_is_the_last_days_and_never_cuts_a_day(home, repo):
    today = date.today()
    old = (today - timedelta(days=30)).isoformat()
    recent = (today - timedelta(days=2)).isoformat()
    repo.commit("old work", ["a.py"], when=f"{old}T12:00:00+0000")
    repo.commit("recent work", ["b.py"], when=f"{recent}T12:00:00+0000")
    code, res, err = jrun("--profile", "claude-code", "--json", "devlog", "--from-git", "--repo", str(repo.path),
                          "--project", "proj")
    assert code == 0, err
    assert [d["day"] for d in res["days"]] == [recent]
    code, res, _ = jrun("--profile", "claude-code", "--json", "devlog", "--from-git", "--repo", str(repo.path),
                        "--project", "proj", "--days", "1")
    assert code == 0 and res["days"] == [] and res["counts"]["created"] == 0


def test_the_project_defaults_to_the_repository_directory_name(home, tmp_path):
    odd = Repo(tmp_path / "work" / "My Project")
    odd.commit("feat: x", ["x.py"], when="2026-09-28T09:00:00+0000")
    Provisioner(Layout.resolve(None), operator="tester").grant_write("claude-code", project="My-Project", basis="x")
    code, res, err = devlog(odd, project=None)
    assert code == 0, err
    assert res["project"] == "My-Project" and res["days"][0]["ref"] == "mem://devlog/My-Project/2026-09-28"


def test_file_lists_and_subjects_are_bounded(home, repo):
    for i in range(45):
        repo.commit(f"commit number {i}", [f"f{i}.txt"], when="2026-09-28T09:00:00+0000")
    files = [f"pkg/module_{i}.py" for i in range(8)]
    repo.commit("x" * 300, files, when="2026-09-28T10:00:00+0000")  # the newest commit of the day
    assert devlog(repo)[0] == 0
    stored = _stored_text(home)
    assert "pkg/module_0.py" in stored and "pkg/module_2.py" in stored and "pkg/module_3.py" not in stored
    assert "+5]" in stored  # 3 files shown, 5 more
    assert "x" * 121 not in stored and "…" in stored  # the subject is cut at 120 characters
    assert "6 more commit(s)" in stored and stored.count("\n- ") == 40  # 46 commits, the newest 40 are listed
    assert len(stored) <= 6000 and recall_all(query="commit")


def _stored_text(home) -> str:
    blobs = [p for p in (home / "data").rglob("*") if p.is_file() and "blobs" in p.parts]
    return max((p.read_text(encoding="utf-8", errors="replace") for p in blobs), key=len)


def test_a_secret_in_a_subject_rejects_only_that_day_and_is_never_stored(home, repo):
    repo.commit("feat: fine", ["a.py"], when="2026-09-28T09:00:00+0000")
    repo.commit(f"oops pasted {SECRET_TOKEN}", ["b.py"], when="2026-09-29T09:00:00+0000")
    repo.commit("feat: also fine", ["c.py"], when="2026-09-30T09:00:00+0000")
    code, res, err = devlog(repo)
    assert code == 4  # content rejected
    assert [d["status"] for d in res["days"]] == ["created", "rejected_secret", "created"]
    assert SECRET_TOKEN not in json.dumps(res) and SECRET_TOKEN not in err
    assert grep_tree(home / "data", SECRET_TOKEN) == []


def test_without_the_operator_grant_it_stops_after_one_denial_with_the_hint(home, repo):
    repo.commit("feat: a", ["a.py"], when="2026-09-28T09:00:00+0000")
    repo.commit("feat: b", ["b.py"], when="2026-09-29T09:00:00+0000")
    code, res, err = jrun("--profile", "codex", "--json", "devlog", "--from-git", "--repo", str(repo.path),
                          "--days", "36500", "--project", "proj")
    assert code == 3 and res["status"] == "denied" and len(res["days"]) == 1
    code, _out, err = run_cli("--profile", "codex", "devlog", "--from-git", "--repo", str(repo.path),
                              "--days", "36500", "--project", "proj")
    assert code == 3 and "grant-write codex --project proj" in err


@pytest.mark.parametrize("repo_arg,project,days,since,needle", [
    ("{missing}", "proj", "7", None, "not a directory"),
    ("{plain}", "proj", "7", None, "not a git repository"),
    ("{repo}", "proj", "7", "-oops", "invalid --since"),
    ("{repo}", "proj", "7", "no-such-ref", "unknown revision"),
    ("{repo}", "proj", "0", None, "--days"),
    ("{repo}", "bad project!", "7", None, "project"),
])
def test_bad_input_is_a_clean_exit_2(home, repo, tmp_path, repo_arg, project, days, since, needle):
    repo.commit("feat: a", ["a.py"], when="2026-09-28T09:00:00+0000")
    plain = tmp_path / "plain"
    plain.mkdir()
    where = repo_arg.replace("{missing}", str(tmp_path / "nope")).replace("{plain}", str(plain)) \
        .replace("{repo}", str(repo.path))
    argv = ["--profile", "claude-code", "devlog", "--from-git", "--repo", where, "--project", project, "--days", days]
    if since is not None:
        argv.append(f"--since={since}")  # the '=' form lets an option-looking value reach the command
    code, out, err = run_cli(*argv)
    assert code == 2 and needle in err and "Traceback" not in err and out == ""


def test_git_missing_is_a_clean_error(home, repo, monkeypatch):
    from zero_mem import devlog_git

    def boom(*a, **k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(devlog_git.subprocess, "run", boom)
    code, _out, err = run_cli("--profile", "claude-code", "devlog", "--from-git", "--repo", str(repo.path),
                              "--project", "proj")
    assert code == 2 and "git" in err and "Traceback" not in err


def test_an_empty_range_is_fine(home, repo):
    repo.commit("feat: a", ["a.py"], when="2026-09-28T09:00:00+0000")
    head = repo.git("rev-parse", "--short", "HEAD")
    code, res, _ = devlog(repo, "--since", head)
    assert code == 0 and res["days"] == [] and res["status"] == "ok"
    code, out, _ = run_cli("--profile", "claude-code", "devlog", "--from-git", "--repo", str(repo.path),
                           "--project", "proj", "--since", head)
    assert code == 0 and "no commits" in out


def test_the_manual_devlog_command_is_unchanged(home):
    code, res, _ = jrun("--profile", "claude-code", "--json", "devlog", "fixed the flaky test", "--project", "proj")
    assert code == 0 and res["scope"] == "project" and res["external_ref"].startswith("mem://devlog/proj/")
    with pytest.raises(SystemExit):
        cli.main(["devlog", "text only"])  # --project is still required without --from-git
    with pytest.raises(SystemExit):
        cli.main(["devlog", "--project", "proj"])  # ... and so is the text
    code, _out, err = run_cli("devlog", "some text", "--from-git", "--project", "proj")
    assert code == 2 and "either" in err


def test_commit_text_never_becomes_an_instruction_channel_or_breaks_the_file(home, repo):
    repo.commit("feat: line one\n\nbody line that must not matter", ["a.py"], when="2026-09-28T09:00:00+0000")
    repo.commit("fix: control\x01chars and   spaces", ["b b.py"], when="2026-09-28T10:00:00+0000")
    assert devlog(repo)[0] == 0
    stored = _stored_text(home)
    assert "body line that must not matter" not in stored and "\x01" not in stored
    assert "b b.py" in stored and "control chars and spaces" in stored and stored.startswith("git commits")
