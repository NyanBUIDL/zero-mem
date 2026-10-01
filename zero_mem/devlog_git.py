"""``zero-mem devlog --from-git``: recent git commits as a development log, with no LLM.

One devlog source per day, ``mem://devlog/<project>/<YYYY-MM-DD>``, whose text lists that day's commits (newest first):
short hash, subject and the files changed (never a diff)::

    git commits:
    - 3f9a2c1 feat: add widgets [src/widgets.py, tests/test_widgets.py]
    - 7be10d4 fix: typo [README.md]

The text is a pure function of the commits, so running it again is a no-op (``unchanged``); a new commit on a day that
was already written makes a new version of that day's source (``updated``) and nothing else changes. Days are always
written whole: ``--since REF`` selects WHICH days are written (those with commits newer than REF), never how much of
a day. Output is bounded (40 commits a day, 3 files a commit, 120 characters a subject) so a devlog never costs more
tokens than a short paragraph in ``memory_context``.

Git is run with a fixed argument list (no shell), no pager and no prompt; a user supplied ref can never be read as an
option. Commit text is untrusted data: control characters are dropped and everything goes through the normal write
path (authorization, secret pre-scan) of :class:`zero_mem.memory.Memory`.
"""
from __future__ import annotations

import os
import re
import subprocess
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

MAX_COMMITS_PER_DAY = 40
MAX_FILES_SHOWN = 3
MAX_SUBJECT_CHARS = 120
MAX_DAYS = 36500
DEFAULT_DAYS = 7
HEADER = "git commits:"

_RS, _US = "\x1e", "\x1f"
_REF_RE = re.compile(r"^[A-Za-z0-9_./@~^{}+:-]{1,200}$")
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PROJECT_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


class GitLogError(Exception):
    """A sanitized, operator-facing failure (never a traceback, never git's raw stderr)."""


@dataclass(frozen=True)
class Commit:
    sha: str
    day: str
    subject: str
    files: tuple


def _flat(text: str) -> str:
    cleaned = "".join(" " if (ord(ch) < 32 or ord(ch) == 127) else ch for ch in text)
    return unicodedata.normalize("NFC", " ".join(cleaned.split()))


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _git(repo: Path, *args: str) -> str:
    # GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE (set when we run inside a git hook) would override ``-C repo``
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        done = subprocess.run(
            ["git", "--no-pager", "-c", "core.quotepath=false", "-c", "log.showSignature=false", "-C", str(repo), *args],
            capture_output=True, text=True, env=env, timeout=60, check=False, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        raise GitLogError("git is not installed or not on PATH") from None
    except subprocess.TimeoutExpired:
        raise GitLogError("git took too long (60 s)") from None
    except OSError:
        raise GitLogError("git could not be started") from None
    if done.returncode != 0:
        raise GitLogError(_git_failure(done.stderr))
    return done.stdout


def _git_failure(stderr: str) -> str:
    low = (stderr or "").lower()
    if "not a git repository" in low:
        return "not a git repository"
    if "unknown revision" in low or "bad revision" in low or "ambiguous argument" in low or "needed a single revision" in low:
        return "unknown revision for --since"
    if "dubious ownership" in low:
        return "git refuses this repository (dubious ownership: see git's safe.directory)"
    return "git log failed"


def default_project(repo: Path) -> Optional[str]:
    """The repository directory name made into a valid project id (``My Project`` -> ``My-Project``), or ``None``."""
    try:
        top = Path(_git(repo, "rev-parse", "--show-toplevel").strip() or repo)
    except GitLogError:
        top = repo
    name = _PROJECT_CHARS.sub("-", top.name).strip("-._")[:64]
    return name if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", name or "") else None


def check_repo(repo: Path) -> None:
    if not repo.is_dir():
        raise GitLogError("--repo is not a directory")
    out = _git(repo, "rev-parse", "--is-inside-work-tree").strip()
    if out != "true":
        raise GitLogError("not a git repository")


def check_ref(repo: Path, ref: str) -> None:
    if not isinstance(ref, str) or ref.startswith("-") or not _REF_RE.match(ref):
        raise GitLogError("invalid --since (give a commit, tag or branch name)")
    try:
        _git(repo, "rev-parse", "--verify", "--quiet", ref + "^{commit}")
    except GitLogError as exc:
        if str(exc) in ("git log failed", "unknown revision for --since"):
            raise GitLogError("unknown revision for --since") from None
        raise


def _parse(raw: str) -> list:
    commits = []
    for record in raw.split(_RS):
        if not record.strip():
            continue
        head, _sep, tail = record.partition("\n")
        parts = head.split(_US)
        if len(parts) < 3 or not _DAY_RE.match(parts[1]):
            continue
        files = tuple(_flat(line) for line in tail.splitlines() if line.strip())
        commits.append(Commit(sha=parts[0].strip(), day=parts[1], subject=_flat(_US.join(parts[2:])), files=files))
    return commits


_FORMAT = f"--format={_RS}%h{_US}%cs{_US}%s"


def collect(repo: Path, *, since: Optional[str], days: int, today: Optional[date] = None) -> dict:
    """``{day: [Commit, ...]}`` (newest commit first) for the days to write; every returned day is complete."""
    today = today or date.today()
    if since is not None:
        touched = {c.day for c in _parse(_git(repo, "log", "--name-only", _FORMAT, f"{since}..HEAD"))}
    else:
        first = today - timedelta(days=days - 1)
        touched = {c.day for c in _parse(_git(repo, "log", "--name-only", _FORMAT, f"--since={first.isoformat()}"))
                   if c.day >= first.isoformat()}
    if not touched:
        return {}
    # fetch from one day before the oldest touched day, so that the oldest one is whole whatever the time zones
    start = date.fromisoformat(min(touched)) - timedelta(days=1)
    grouped: dict = {}
    for commit in _parse(_git(repo, "log", "--name-only", _FORMAT, f"--since={start.isoformat()}")):
        if commit.day in touched:
            grouped.setdefault(commit.day, []).append(commit)
    return {day: grouped[day] for day in sorted(grouped)}


def render(day_commits: list) -> str:
    """The text of one day's devlog source (a pure function of its commits)."""
    lines = [HEADER]
    for commit in day_commits[:MAX_COMMITS_PER_DAY]:
        shown = list(commit.files[:MAX_FILES_SHOWN])
        more = len(commit.files) - len(shown)
        where = ""
        if shown:
            where = " [" + ", ".join(shown) + (f" +{more}" if more > 0 else "") + "]"
        lines.append(f"- {commit.sha} {_clip(commit.subject, MAX_SUBJECT_CHARS) or '(no subject)'}{where}")
    extra = len(day_commits) - MAX_COMMITS_PER_DAY
    if extra > 0:
        lines.append(f"... and {extra} more commit(s)")
    return "\n".join(lines)


__all__ = ["Commit", "DEFAULT_DAYS", "GitLogError", "MAX_DAYS", "check_ref", "check_repo", "collect",
           "default_project", "render"]
