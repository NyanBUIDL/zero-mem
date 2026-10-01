"""T10a - bug-review regressions (DEF-075..)."""
from __future__ import annotations

from tests.unit.test_t8_devlog_git import Repo, devlog, home, repo  # noqa: F401  (fixtures)


def test_def075_devlog_from_git_on_a_repo_without_commits_is_a_clean_noop(home, repo):  # noqa: F811
    """A freshly `git init`-ed repo (agent hook) must say 'nothing to record', not fail with 'git log failed'."""
    code, res, err = devlog(repo)
    assert code == 0, err
    assert res["days"] == [] and res["status"] == "ok"


def test_def076_import_notes_survives_deeply_nested_json_line(home):  # noqa: F811
    import json

    from zero_mem.memory import Memory
    from zero_mem.notes_import import import_notes

    notes = home / "notes.jsonl"
    good = json.dumps({"chunk_id": "c1", "text": "note one"}).encode()
    notes.write_bytes(b"[" * 200000 + b"\n" + good + b"\n")
    with Memory.open("claude-code") as memory:
        report = import_notes(memory, notes)
    assert report.counts["created"] == 1
    assert report.skipped == [{"name": "line 1", "reason": "malformed_json"}]


def test_def077_ingest_and_import_notes_reject_an_empty_path_instead_of_using_the_cwd(home, monkeypatch):  # noqa: F811
    from tests.unit.test_t8_devlog_git import run_cli

    work = home / "cwd"
    work.mkdir()
    (work / "stray.md").write_text("must not be ingested\n", encoding="utf-8")
    monkeypatch.chdir(work)
    code, out, err = run_cli("--profile", "claude-code", "ingest", "")
    assert code == 2 and "ingested" not in out, (out, err)
    code, out, err = run_cli("--profile", "claude-code", "import-notes", "--path", "")
    assert code == 2 and "imported" not in out, (out, err)
