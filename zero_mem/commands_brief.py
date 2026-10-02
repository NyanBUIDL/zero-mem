"""CLI: ``zero-mem brief`` (the task briefing) and ``zero-mem eval init | run | history | safety`` (does the memory deliver?).

Thin shells over :meth:`zero_mem.memory.Memory.brief` and :mod:`zero_mem.eval_harness`. ``brief`` prints the plain briefing on
stdout (so a hook can inject it) and explanations on stderr; while the owner's settings disable injection it prints nothing
and exits 0 (a session-start hook must never fail because injection is off). ``--preview`` is the owner's view: it shows
what WOULD be injected plus why it is off. Exit codes follow :mod:`zero_mem.commands_memory`: 0 ok, 1 an eval case or safety
check failed, 2 invalid usage / unusable file or store.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from . import eval_harness as eh
from .commands_memory import EXIT_ERROR, EXIT_OK, _common, _emit, _err, _open, _wants_json
from .memory_layout import Layout

EXIT_FAILED = 1
_REASON_HINT = {
    "injection_disabled": "injection is off (owner: zero-mem settings set injection.enabled true)",
    "kill_switch": "the owner's kill switch is on (settings: safety.kill_switch)",
    "settings_invalid": "the settings file is unusable, so injection is off (zero-mem settings validate)",
}
_INVALID_HINT = {
    "invalid_max_chars": "--max-chars must be between 1 and 8000",
    "invalid_project_id": "the project id may use letters, digits and . _ - (max 64)",
    "invalid_task": "the task must be text",
}


def add_brief_parsers(subparsers) -> None:
    common = _common()
    p = subparsers.add_parser("brief", parents=[common],
                              help="print the task briefing: active rules plus what matches --task (settings-gated)")
    p.add_argument("--task", default=None, help="what you are about to do (selects decisions, gotchas, workflows)")
    p.add_argument("--max-chars", type=int, default=None, help="size cap (1..8000; default: the injection setting, 2000)")
    p.add_argument("--project", dest="project_id", default=None, help="project id (also reads its rules and devlog)")
    p.add_argument("--preview", action="store_true",
                   help="OWNER view: show what WOULD be injected even while injection is off, and why it is off")
    p.set_defaults(_brief_cmd="brief")

    owner = argparse.ArgumentParser(add_help=False)
    owner.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output")
    ev = subparsers.add_parser("eval", help="measure whether the briefing contains what tasks need (owner-written cases)")
    sub = ev.add_subparsers(dest="eval_command", required=True)
    p = sub.add_parser("init", parents=[owner], help="write an example cases file")
    p.add_argument("path", nargs="?", default="brief-eval.jsonl")
    p.add_argument("--force", action="store_true", help="overwrite an existing file")
    p.set_defaults(_brief_cmd="eval_init")
    p = sub.add_parser("run", parents=[common], help="run a JSONL cases file; exit 1 when any case fails")
    p.add_argument("file")
    p.set_defaults(_brief_cmd="eval_run")
    p = sub.add_parser("history", parents=[owner], help="print the trend of recorded runs")
    p.add_argument("-n", "--last", type=int, default=20, help="how many runs (default 20)")
    p.set_defaults(_brief_cmd="eval_history")
    p = sub.add_parser("safety", parents=[owner],
                       help="build a temporary store and assert the harness invariants; exit 1 on a violation")
    p.set_defaults(_brief_cmd="eval_safety")


def _cmd_brief(args) -> int:
    memory = _open(args)
    try:
        bundle = memory.brief(args.task, max_chars=args.max_chars, project_id=args.project_id, preview=args.preview)
    finally:
        memory.close()
    if bundle.status in ("invalid", "error"):
        _err(_INVALID_HINT.get(bundle.reason, f"cannot build the briefing ({bundle.reason})"))
        return EXIT_ERROR
    if _wants_json(args):
        _emit(bundle.as_dict())
        return EXIT_OK
    if bundle.reason:
        hint = _REASON_HINT.get(bundle.reason, bundle.reason)
        _err(("preview: this is what WOULD be injected; " if bundle.preview else "no briefing: ") + f"{bundle.reason} - {hint}")
    if bundle.text:
        print(bundle.render())
    return EXIT_OK


def _cmd_eval_init(args) -> int:
    target = Path(args.path)
    if target.exists() and not args.force:
        _err("file exists (use --force to overwrite)")
        return EXIT_ERROR
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(eh.example_text())
    except OSError:
        _err("cannot write the example file")
        return EXIT_ERROR
    if _wants_json(args):
        _emit({"status": "ok", "path": target.as_posix()})
    else:
        print(f"wrote {target.as_posix()} - edit the refs, then: zero-mem eval run {target.as_posix()}")
    return EXIT_OK


def _cmd_eval_run(args) -> int:
    path = Path(args.file)
    try:
        cases = eh.load_cases(path)
    except eh.EvalFileError as exc:
        _err(str(exc))
        return EXIT_ERROR
    report = eh.run_cases(cases, args.profile)
    report["file"] = path.name
    layout = Layout.resolve(None)
    note = None
    try:
        eh.append_history(layout.data_root, eh.history_row(path.name, report["summary"]))
    except Exception:  # noqa: BLE001 - the history is a convenience; never fail an eval because of it
        note = "warning: the run was not recorded in eval-history.jsonl"
    if _wants_json(args):
        _emit(report)
    else:
        print(eh.render_report(path.name, report))
    if note:
        _err(note)
    return EXIT_OK if report["summary"]["failed"] == 0 else EXIT_FAILED


def _cmd_eval_history(args) -> int:
    rows = eh.read_history(Layout.resolve(None).data_root, max(1, args.last))
    if _wants_json(args):
        _emit({"count": len(rows), "runs": rows})
    else:
        print(eh.render_history(rows))
    return EXIT_OK


def _cmd_eval_safety(args) -> int:
    result = eh.run_safety_suite()
    if _wants_json(args):
        _emit(result)
    else:
        for check in result["checks"]:
            print(f"{'PASS' if check['ok'] else 'FAIL'} {check['name']}" + (f"  ({check['detail']})" if check["detail"] else ""))
        print("safety suite: " + ("all invariants hold" if result["passed"] else f"{result['failed']} invariant(s) VIOLATED"))
    return EXIT_OK if result["passed"] else EXIT_FAILED


_HANDLERS = {"brief": _cmd_brief, "eval_init": _cmd_eval_init, "eval_run": _cmd_eval_run,
             "eval_history": _cmd_eval_history, "eval_safety": _cmd_eval_safety}


def dispatch(args) -> Optional[int]:
    name = getattr(args, "_brief_cmd", None)
    if name is None:
        return None
    from .memory import MemoryConfigError
    from .memory_layout import LayoutError
    from .provisioning import ProvisioningError

    try:
        return _HANDLERS[name](args)
    except (MemoryConfigError, LayoutError) as exc:
        _err(str(exc))
        return EXIT_ERROR
    except ProvisioningError as exc:
        _err(exc.message)
        return EXIT_ERROR
    except KeyboardInterrupt:
        _err("interrupted")
        return 130
    except BrokenPipeError:
        return EXIT_OK
    except Exception as exc:  # noqa: BLE001 - never a traceback for the owner
        _err(f"unexpected error ({type(exc).__name__}); run zero-mem doctor")
        return EXIT_ERROR


__all__ = ["add_brief_parsers", "dispatch"]
