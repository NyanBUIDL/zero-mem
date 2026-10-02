"""Does the memory deliver? Owner-written briefing cases, a safety suite and a private run history (T15).

``zero-mem eval run FILE`` replays JSONL cases through :meth:`Memory.brief` with ``preview=True`` (so it measures the
content even while injection is switched off; that is reported separately). ``zero-mem eval safety`` builds a throw-away
store and asserts the invariants of the harness (nothing unapproved, expired, forgotten or foreign ever appears; the kill
switch and a disabled injection empty the briefing; the budget is never exceeded). Zero LLM calls, deterministic apart from
the measured latency, zero dependencies, Windows / macOS / Linux safe (UTF-8 everywhere, no POSIX-only calls).

Case line (JSON object, closed schema)::

    {"id": "db", "task": "...", "must_include": ["mem://rule/x", "plain words"], "must_not_include": [...],
     "profile": "codex", "project": "my-project", "max_chars": 2000}

A ``must_include`` / ``must_not_include`` entry that starts with ``mem://`` matches a ref in the briefing (exact, or as a
prefix when it ends with ``/``); any other entry is a case-insensitive substring of the briefing text.
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from . import learning_settings as ls
from .memory import Memory
from .provisioning import valid_id

HISTORY_FILENAME = "eval-history.jsonl"
HISTORY_MAX_LINES = 500
HISTORY_KEEP_LINES = 250
MAX_CASES = 500
MAX_FILE_BYTES = 1024 * 1024
MAX_TASK_CHARS = 1000
MAX_NEEDLES = 50
MAX_NEEDLE_CHARS = 300
_CASE_KEYS = ("id", "task", "must_include", "must_not_include", "profile", "project", "max_chars")
_LOCK_TIMEOUT = 15.0

EXAMPLE_CASES = (
    {"id": "no-force-push", "task": "clean up the git history of main",
     "must_include": ["mem://rule/no-force-push"], "must_not_include": ["TODO-unapproved"]},
    {"id": "database-locking", "task": "the sqlite database is locked under concurrent writers",
     "must_include": ["mem://gotcha/"], "max_chars": 1500},
    {"id": "release", "task": "cut a release", "must_include": ["release"], "project": "my-project"},
)


class EvalFileError(ValueError):
    """The cases file is unusable (the message names the line and the rule, never file content)."""


@dataclass(frozen=True)
class Case:
    id: str
    task: str
    must_include: tuple = ()
    must_not_include: tuple = ()
    profile: Optional[str] = None
    project: Optional[str] = None
    max_chars: Optional[int] = None


# ---------------------------------------------------------------------------------------------
# cases file
# ---------------------------------------------------------------------------------------------
def example_text() -> str:
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in EXAMPLE_CASES)


def _needles(value: Any, label: str, number: int) -> tuple:
    if not isinstance(value, list) or len(value) > MAX_NEEDLES:
        raise EvalFileError(f"line {number}: {label} must be a list of at most {MAX_NEEDLES} strings")
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item) > MAX_NEEDLE_CHARS:
            raise EvalFileError(f"line {number}: {label} entries must be non-empty strings "
                                f"(at most {MAX_NEEDLE_CHARS} characters)")
    return tuple(item.strip() for item in value)


def _case(row: Any, number: int) -> Case:
    if not isinstance(row, dict):
        raise EvalFileError(f"line {number}: each line must be a JSON object")
    unknown = sorted(set(row) - set(_CASE_KEYS))
    if unknown:
        raise EvalFileError(f"line {number}: unknown key {unknown[0]!r} (allowed: {', '.join(_CASE_KEYS)})")
    ident = row.get("id")
    if not isinstance(ident, str) or not ident.strip() or len(ident) > 64 or not ident.isprintable():
        raise EvalFileError(f"line {number}: id must be a printable string of 1-64 characters")
    task = row.get("task")
    if not isinstance(task, str) or not task.strip() or len(task) > MAX_TASK_CHARS:
        raise EvalFileError(f"line {number}: task must be a non-empty string of at most {MAX_TASK_CHARS} characters")
    profile, project = row.get("profile"), row.get("project")
    if profile is not None and (not isinstance(profile, str) or not valid_id(profile)):
        raise EvalFileError(f"line {number}: profile must be a valid profile id")
    if project is not None and (not isinstance(project, str) or not valid_id(project)):
        raise EvalFileError(f"line {number}: project must be a valid project id")
    max_chars = row.get("max_chars")
    if max_chars is not None and (not isinstance(max_chars, int) or isinstance(max_chars, bool)
                                  or not 1 <= max_chars <= ls.INJECTION_MAX_CHARS_HARD_CAP):
        raise EvalFileError(f"line {number}: max_chars must be an integer between 1 and "
                            f"{ls.INJECTION_MAX_CHARS_HARD_CAP}")
    return Case(id=ident.strip(), task=task.strip(),
                must_include=_needles(row.get("must_include", []), "must_include", number),
                must_not_include=_needles(row.get("must_not_include", []), "must_not_include", number),
                profile=profile, project=project, max_chars=max_chars)


def load_cases(path: Path) -> list:
    """Parse and validate a cases file. Raises :class:`EvalFileError` (never a traceback for a bad file)."""
    try:
        if not path.is_file():
            raise EvalFileError("cases file not found")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise EvalFileError("cases file is too large")
        raw = path.read_bytes().decode("utf-8-sig")
    except EvalFileError:
        raise
    except (OSError, UnicodeError):
        raise EvalFileError("cases file is unreadable (UTF-8 JSON lines expected)") from None
    cases: list = []
    seen: set = set()
    for number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            raise EvalFileError(f"line {number}: not valid JSON") from None
        case = _case(row, number)
        if case.id in seen:
            raise EvalFileError(f"line {number}: duplicate id {case.id!r}")
        seen.add(case.id)
        cases.append(case)
        if len(cases) > MAX_CASES:
            raise EvalFileError(f"more than {MAX_CASES} cases")
    if not cases:
        raise EvalFileError("cases file has no cases")
    return cases


# ---------------------------------------------------------------------------------------------
# running
# ---------------------------------------------------------------------------------------------
def matches(needle: str, bundle: Any) -> bool:
    if needle.startswith("mem://"):
        if needle.endswith("/"):
            return any(ref.startswith(needle) for ref in bundle.sources)
        return needle in bundle.sources
    return needle.casefold() in bundle.text.casefold()


def run_cases(cases: list, default_profile: str,
              open_memory: Optional[Callable[[str], Memory]] = None) -> dict:
    """Run every case; returns ``{"cases": [...], "summary": {...}}`` (JSON-safe)."""
    opener = open_memory or (lambda profile: Memory.open(profile, channel="eval"))
    opened: dict = {}
    rows: list = []
    try:
        for case in cases:
            profile = case.profile or default_profile
            if profile not in opened:
                opened[profile] = opener(profile)
            started = time.perf_counter()
            bundle = opened[profile].brief(case.task, max_chars=case.max_chars, project_id=case.project, preview=True)
            latency = (time.perf_counter() - started) * 1000.0
            missing = [n for n in case.must_include if not matches(n, bundle)]
            forbidden = [n for n in case.must_not_include if matches(n, bundle)]
            usable = bundle.status in ("ok", "empty")
            rows.append({
                "id": case.id, "profile": profile, "project": case.project,
                "passed": usable and not missing and not forbidden,
                "missing": missing, "forbidden": forbidden,
                "chars": len(bundle.text), "max_chars": bundle.max_chars, "truncated": bundle.truncated,
                "latency_ms": round(latency, 2), "injection_enabled": bool(bundle.enabled),
                "reason": bundle.reason, "sources": list(bundle.sources),
                **({"error": bundle.reason} if not usable else {}),
            })
    finally:
        for memory in opened.values():
            with contextlib.suppress(Exception):
                memory.close()
    return {"cases": rows, "summary": summarize(cases, rows)}


def summarize(cases: list, rows: list) -> dict:
    total = sum(len(c.must_include) for c in cases)
    found = total - sum(len(r["missing"]) for r in rows)
    latencies = [r["latency_ms"] for r in rows]
    return {
        "cases": len(rows), "passed": sum(1 for r in rows if r["passed"]),
        "failed": sum(1 for r in rows if not r["passed"]),
        "must_include_total": total, "must_include_found": found,
        "recall": round(found / total, 4) if total else None,
        "forbidden_hits": sum(len(r["forbidden"]) for r in rows),
        "truncated": sum(1 for r in rows if r["truncated"]),
        "latency_ms_avg": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        "latency_ms_max": max(latencies) if latencies else 0.0,
        "injection_off_cases": sum(1 for r in rows if not r["injection_enabled"]),
    }


def render_report(name: str, report: dict) -> str:
    lines = [f"eval {name}"]
    for row in report["cases"]:
        lines.append(f"{'PASS' if row['passed'] else 'FAIL'} {row['id']}  chars {row['chars']}/{row['max_chars']}"
                     f"{'  truncated' if row['truncated'] else ''}  {row['latency_ms']:.1f} ms")
        if row["missing"]:
            lines.append("     missing: " + ", ".join(row["missing"]))
        if row["forbidden"]:
            lines.append("     forbidden: " + ", ".join(row["forbidden"]))
        if row.get("error"):
            lines.append(f"     error: {row['error']}")
    s = report["summary"]
    recall = "n/a" if s["recall"] is None else f"{s['recall']} ({s['must_include_found']}/{s['must_include_total']})"
    lines.append(f"summary: {s['passed']}/{s['cases']} passed; recall {recall}; forbidden hits {s['forbidden_hits']}; "
                 f"truncated {s['truncated']}; latency avg {s['latency_ms_avg']} ms max {s['latency_ms_max']} ms")
    if s["injection_off_cases"]:
        lines.append(f"note: injection is OFF for {s['injection_off_cases']} case(s): results show what WOULD be "
                     "injected (preview). Turn it on with: zero-mem settings set injection.enabled true")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# history (private, bounded)
# ---------------------------------------------------------------------------------------------
def history_path(data_root: Path) -> Path:
    return Path(data_root) / HISTORY_FILENAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def history_row(name: str, summary: dict) -> dict:
    """One summary line; never the task text, only counts and the cases file's base name."""
    keys = ("cases", "passed", "failed", "recall", "forbidden_hits", "truncated", "latency_ms_avg", "latency_ms_max",
            "injection_off_cases")
    return {"at": _now_iso(), "file": os.path.basename(name)[:80], **{k: summary[k] for k in keys}}


def append_history(data_root: Path, row: dict) -> None:
    """Append one line (private file), trimming to the newest ``HISTORY_KEEP_LINES`` past ``HISTORY_MAX_LINES``."""
    from src.corpus._fsretry import retry_transient
    from src.storage.coordination import locked

    from . import paths

    path = history_path(data_root)
    paths.ensure_private_dir(path.parent, "data directory")
    payload = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    with locked(path.with_name(path.name + ".lock"), mode="exclusive", timeout=_LOCK_TIMEOUT):
        fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
        if os.name != "nt":
            os.chmod(path, 0o600)
        lines = path.read_bytes().splitlines(keepends=True)
        if len(lines) <= HISTORY_MAX_LINES:
            return
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(b"".join(lines[-HISTORY_KEEP_LINES:]))
                handle.flush()
                os.fsync(handle.fileno())
            retry_transient(lambda: os.replace(temporary, path))
        finally:
            with contextlib.suppress(OSError):
                os.unlink(temporary)


def read_history(data_root: Path, limit: int = 20) -> list:
    """The newest ``limit`` valid rows, oldest first (corrupt lines are skipped)."""
    path = history_path(data_root)
    try:
        data = path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return []
    rows: list = []
    for line in data.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and "at" in row and "cases" in row:
            rows.append(row)
    return rows[-limit:] if limit > 0 else rows


def render_history(rows: list) -> str:
    if not rows:
        return "no eval runs recorded yet (zero-mem eval run FILE)"
    lines = ["when (UTC)            file                  cases pass fail recall  forbidden trunc  lat avg ms"]
    previous = None
    for row in rows:
        recall = row.get("recall")
        trend = ""
        if previous is not None and isinstance(recall, (int, float)) and isinstance(previous, (int, float)):
            trend = " up" if recall > previous else (" down" if recall < previous else " =")
        previous = recall if isinstance(recall, (int, float)) else previous
        shown = "n/a" if recall is None else f"{recall:.4f}"
        lines.append(f"{str(row['at']):<21} {str(row.get('file', '')):<21} {row['cases']:>5} {row.get('passed', 0):>4} "
                     f"{row.get('failed', 0):>4} {shown:<7} {row.get('forbidden_hits', 0):>9} {row.get('truncated', 0):>5} "
                     f"{row.get('latency_ms_avg', 0):>11}{trend}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# safety suite
# ---------------------------------------------------------------------------------------------
class _Clock:
    def __init__(self, iso: str) -> None:
        self.now = datetime.fromisoformat(iso)

    def __call__(self) -> datetime:
        return self.now


class _Check:
    def __init__(self) -> None:
        self.rows: list = []

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.rows.append({"name": name, "ok": bool(ok), "detail": "" if ok else detail})


_T0 = "2026-10-01T09:00:00+00:00"
_MARKERS = {"pending": "zzpendingmark", "rejected": "zzrejectedmark", "expired": "zzexpiredmark",
            "forgotten": "zzforgottenmark", "foreign": "zzforeignmark", "old": "zzoldversionmark",
            "visible": "zzvisiblemark"}
_ALL_TYPES = "rule,decision,gotcha,workflow,skill,persona,devlog"


def _leaks(memory: Memory, marker: str, task: str) -> list:
    """Where ``marker`` shows up: brief (live and preview), context, recall."""
    where = []
    for preview in (False, True):
        if marker in memory.brief(task, max_chars=8000, preview=preview).text:
            where.append("brief(preview)" if preview else "brief")
    if marker in memory.context(max_chars=8000).text:
        where.append("context")
    if any(marker in hit.text for hit in memory.recall(marker, limit=50).hits):
        where.append("recall")
    return where


def run_safety_suite() -> dict:
    """Build a temp store, assert the invariants, delete it. Returns ``{"passed", "failed", "checks"}``."""
    from .memory_layout import Layout
    from .learning import Reviewer
    from .provisioning import Provisioner

    root = Path(os.path.realpath(tempfile.mkdtemp(prefix="zero-mem-eval-safety-")))
    checks = _Check()
    memories: list = []
    try:
        settings = root / "settings.toml"
        layout = Layout.resolve(root / "store")
        layout.ensure()
        clock = _Clock(_T0)
        prov = Provisioner(layout, operator="eval-safety", clock=clock)
        for profile in ("alpha", "beta"):
            prov.add_agent(profile)
            prov.grant_write(profile, space=Memory.SHARED_SPACE, basis="eval safety suite")

        def open_as(profile: str) -> Memory:
            mem = Memory.open(profile, data_root=root / "store", clock=clock, settings_path=settings, channel="eval")
            memories.append(mem)
            return mem

        for key, value in (("injection.enabled", "true"), ("injection.types", _ALL_TYPES),
                           ("learning.active_ttl_days", "5")):
            ls.set_value(key, value, settings)
        alpha, beta = open_as("alpha"), open_as("beta")
        reviewer = Reviewer(layout, operator="eval-safety", clock=clock, settings_path=settings)
        m = _MARKERS
        alpha.add(f"Always run the linter first {m['visible']}.", "rule", name="visible-rule", scope="shared")
        alpha.add(f"Retry on busy {m['visible']} database.", "gotcha", name="visible-gotcha", scope="shared")
        alpha.add(f"Old wording {m['old']}.", "rule", name="versioned", scope="shared")
        alpha.add(f"New wording {m['visible']} for the versioned rule.", "rule", name="versioned", scope="shared")
        alpha.add(f"Forget me {m['forgotten']}.", "gotcha", name="to-forget", scope="shared")
        beta.add(f"Private to beta {m['foreign']}.", "rule", name="beta-private", scope="private")
        pending = alpha.propose(f"A pending rule {m['pending']}.", "rule", name="pending-rule")
        rejected = alpha.propose(f"A rejected rule {m['rejected']}.", "rule", name="rejected-rule")
        expiring = alpha.propose(f"An approved gotcha that will expire {m['expired']}.", "gotcha", name="expiring")
        reviewer.reject(rejected.proposal_id, "eval")
        approved = reviewer.approve(expiring.proposal_id)
        forgot = alpha.recall(m["forgotten"]).hits
        if forgot:
            alpha.forget(forgot[0].source_id)
        checks.add("setup", pending.ok and rejected.ok and approved.ok and bool(forgot), "the fixture store was not built")
        clock.now = clock.now + timedelta(days=10)  # the approval is now past learning.active_ttl_days (5)
        task = " ".join(m.values()) + " linter database wording"
        alpha = open_as("alpha")

        # a control: without it the "never appears" checks could pass vacuously
        control = alpha.brief(task, max_chars=8000)
        checks.add("control_visible_items_present", m["visible"] in control.text
                   and "mem://rule/visible-rule" in control.sources, "approved, readable items must be briefed")

        for name, marker in (("pending", m["pending"]), ("rejected", m["rejected"]), ("expired", m["expired"]),
                             ("forgotten", m["forgotten"]), ("old", m["old"])):
            label = {"old": "superseded_version"}.get(name, name)
            where = _leaks(alpha, marker, task)
            checks.add(f"{label}_never_in_brief_context_or_recall", not where, "leaked into " + ", ".join(where))
        where = _leaks(alpha, m["foreign"], task)
        checks.add("other_profile_private_never_appears", not where, "leaked into " + ", ".join(where))
        checks.add("own_private_still_visible_to_owner",
                   m["foreign"] in open_as("beta").brief(task, max_chars=8000).text, "the owner must see its own item")

        first, second = alpha.brief(task, max_chars=2000), alpha.brief(task, max_chars=2000)
        checks.add("deterministic_repeat", first.as_dict() == second.as_dict(), "two identical calls differ")

        over = []
        for limit in (1, 7, 60, 200, 500, 2000, 8000):
            for preview in (False, True):
                bundle = alpha.brief(task, max_chars=limit, preview=preview)
                if len(bundle.text) > limit:
                    over.append(limit)
        checks.add("budget_never_exceeded", not over and alpha.brief(task, max_chars=8001).status == "invalid",
                   f"over budget at {sorted(set(over))}")

        ls.set_value("injection.enabled", "false", settings)
        off = alpha.brief(task)
        checks.add("injection_disabled_empties_non_preview_brief",
                   off.text == "" and off.reason == "injection_disabled" and off.status == "disabled",
                   "a disabled injection still returned content")
        ls.set_value("injection.enabled", "true", settings)
        ls.set_value("safety.kill_switch", "true", settings)
        killed, peek = alpha.brief(task), alpha.brief(task, preview=True)
        checks.add("kill_switch_empties_brief", killed.text == "" and killed.reason == "kill_switch"
                   and peek.reason == "kill_switch" and peek.enabled is False, "the kill switch did not empty the brief")
        ls.set_value("safety.kill_switch", "false", settings)
        settings.write_text("[injection\n", encoding="utf-8")
        broken = alpha.brief(task)
        checks.add("settings_invalid_fails_safe", broken.text == "" and broken.reason == "settings_invalid",
                   "an unusable settings file did not fail safe")
    except Exception as exc:  # noqa: BLE001 - report, do not crash the owner's terminal
        checks.add("suite_ran_to_completion", False, f"unexpected {type(exc).__name__}")
    finally:
        for mem in memories:
            with contextlib.suppress(Exception):
                mem.close()
        shutil.rmtree(root, ignore_errors=True)
    failed = sum(1 for c in checks.rows if not c["ok"])
    return {"passed": failed == 0, "failed": failed, "checks": checks.rows}


__all__ = [
    "Case", "EXAMPLE_CASES", "EvalFileError", "HISTORY_FILENAME", "append_history", "example_text", "history_row",
    "load_cases", "matches", "read_history", "render_history", "render_report", "run_cases", "run_safety_suite",
    "summarize",
]
