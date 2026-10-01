"""T10a - bug-review regressions (DEF-075..)."""
from __future__ import annotations

from tests.unit.test_t8_devlog_git import Repo, devlog, home, repo  # noqa: F401  (fixtures)


def test_def075_devlog_from_git_on_a_repo_without_commits_is_a_clean_noop(home, repo):  # noqa: F811
    """A freshly `git init`-ed repo (agent hook) must say 'nothing to record', not fail with 'git log failed'."""
    code, res, err = devlog(repo)
    assert code == 0, err
    assert res["days"] == [] and res["status"] == "ok"
