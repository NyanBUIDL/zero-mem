"""``zero-mem learn``: deterministic candidates from transcripts / git / text become PROPOSALS (never active memory).

Thin shell over :mod:`zero_mem.learner`. ``--from-hook`` is built for agent hooks: it reads the hook's JSON from standard
input, prints nothing and ALWAYS exits 0, so a hook can never break an agent session.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from . import learner
from .commands_memory import EXIT_ERROR, EXIT_OK, _common, _emit, _err, _wants_json


def add_learn_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "learn", parents=[_common()],
        help="turn user statements in a transcript / git history / text into PROPOSALS for `zero-mem review` (no LLM)")
    src = p.add_argument_group("source (exactly one)")
    src.add_argument("--from-transcript", metavar="PATH", help="Claude Code transcript JSONL (also generic chat JSONL / text logs)")
    src.add_argument("--from-git", action="store_true", help="commit messages of a git repository")
    src.add_argument("--from-hook", action="store_true",
                     help="read a Claude Code hook payload ({transcript_path, session_id, cwd}) from stdin; silent, always exit 0")
    src.add_argument("--from-text", metavar="FILE", help="a plain 'User: ...' log or text file ('-' reads standard input)")
    p.add_argument("--repo", default=None, help="git repository for --from-git (default: current directory)")
    p.add_argument("--since", default=None, help="--from-git: only commits after this commit / tag / branch")
    p.add_argument("--project", default=None, help="project name for evidence (default: working directory name)")
    p.add_argument("--dry-run", action="store_true", help="show the candidates; store nothing and remember nothing")
    p.add_argument("--max", dest="max_new", type=int, default=learner.DEFAULT_MAX_PER_RUN, metavar="N",
                   help=f"at most N proposals per run (default {learner.DEFAULT_MAX_PER_RUN}, hard cap {learner.HARD_MAX_PER_RUN})")
    p.set_defaults(_learn_run=True)


def _project(args, fallback_dir: Optional[str] = None) -> Optional[str]:
    if args.project:
        return args.project
    return learner.hook_project(fallback_dir or str(Path.cwd()))


def _run(args, messages, label: str, project: Optional[str], deadline: float) -> dict:
    from .memory import Memory

    memory = Memory.open(args.profile, channel="cli")
    try:
        return learner.learn(memory, messages, project=project, max_new=args.max_new, dry_run=args.dry_run,
                             source_label=label, deadline=deadline)
    finally:
        memory.close()


_WHY = {
    "learning_off": "learning is off (zero-mem settings set learning.mode suggest)",
    "kill_switch": "the owner's kill switch is on (settings: safety.kill_switch)",
    "settings_invalid": "the settings file is unusable, so learning is off (zero-mem settings validate)",
    "daily_limit": "the daily proposal limit was reached; the rest is kept for a later run",
    "max": "the per-run cap was reached; run again for more",
    "deadline": "the time budget ran out; run again for more",
}


def _print(report: dict) -> None:
    if report["disabled"]:
        print(f"nothing done: {_WHY.get(report['disabled'], report['disabled'])}")
        return
    head = "dry run: " if report["dry_run"] else ""
    if report["dry_run"]:
        print(f"{head}{len(report['candidates'])} candidate(s) from {report['messages']} message(s)")
        for c in report["candidates"]:
            print(f"  [{c['memory_type']}/{c['scope']}] {c['text']}   ({c['evidence'][0]})")
    else:
        print(f"{report['created']} proposed, {report['merged']} merged into existing proposals, "
              f"{report['skipped_processed']} already processed, from {report['messages']} message(s)")
        if report["created"] or report["merged"]:
            print("pending owner review: zero-mem review list")
    if report["rejected"]:
        print("refused: " + ", ".join(f"{k} x{v}" for k, v in sorted(report["rejected"].items())))
    if report["stopped"]:
        print(f"stopped: {_WHY.get(report['stopped'], report['stopped'])}")


def _from_hook(args) -> int:
    """Never raises, never prints, always 0."""
    try:
        raw = sys.stdin.read(learner.HOOK_STDIN_BYTES)
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return EXIT_OK
        path = payload.get("transcript_path")
        if not isinstance(path, str) or not path:
            return EXIT_OK
        file = Path(path)
        if not file.is_file():
            return EXIT_OK
        project = args.project or learner.hook_project(payload.get("cwd")) or _project(args)
        session = payload.get("session_id")
        messages = learner.iter_transcript(file, session=learner._session_id(session, "") or None)
        _run(args, messages, "hook", project, learner.HOOK_DEADLINE_SECONDS)
    except BaseException as exc:  # noqa: BLE001 - a hook must never break the agent session (incl. SystemExit)
        if isinstance(exc, KeyboardInterrupt):
            raise
    return EXIT_OK


def dispatch(args) -> Optional[int]:
    if not getattr(args, "_learn_run", False):
        return None
    chosen = [bool(args.from_transcript), bool(args.from_git), bool(args.from_hook), bool(args.from_text)]
    if args.from_hook and sum(chosen) == 1:
        return _from_hook(args)
    if sum(chosen) != 1:
        _err("give exactly one of --from-transcript, --from-git, --from-hook, --from-text")
        return EXIT_ERROR
    from .memory import MemoryConfigError
    from .provisioning import ProvisioningError

    try:
        if args.from_transcript:
            file = Path(args.from_transcript)
            if not file.is_file():
                _err("--from-transcript is not a file")
                return EXIT_ERROR
            messages, label = learner.load_messages(file), "transcript"
            project = _project(args)
        elif args.from_text:
            if args.from_text == "-":
                messages = learner.parse_plain_text(sys.stdin.read(learner.MAX_MESSAGE_CHARS * 50), session="stdin")
            else:
                file = Path(args.from_text)
                if not file.is_file():
                    _err("--from-text is not a file")
                    return EXIT_ERROR
                messages = learner.load_messages(file)
            label, project = "text", _project(args)
        else:
            from .devlog_git import GitLogError

            repo = Path(args.repo) if args.repo else Path.cwd()
            try:
                messages = learner.git_messages(repo, since=args.since)
            except GitLogError as exc:
                _err(str(exc))
                return EXIT_ERROR
            label, project = "git", _project(args, str(repo.resolve()))
        report = _run(args, messages, label, project, learner.DEFAULT_DEADLINE_SECONDS)
    except (MemoryConfigError, ProvisioningError) as exc:
        _err(getattr(exc, "message", None) or str(exc))
        return EXIT_ERROR
    if _wants_json(args):
        _emit(report)
    else:
        _print(report)
    return EXIT_OK


__all__ = ["add_learn_parser", "dispatch"]
