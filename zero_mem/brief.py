"""Task-aware briefing (``Memory.brief``): what an agent should know at the start of a task.

Order within the budget: (a) active ``rule`` items (always), (b) ``decision`` / ``gotcha`` / ``workflow`` / ``skill`` items
that match the task text (existing lexical retrieval, one query per type, ties by ref), (c) recent ``devlog`` of the
project, (d) ``persona``. A section is only included when its type is allowed by the owner's ``injection.types``.
Lines are filled whole and in priority order; a section that does not fit is cut and counted in ``omitted``.

Everything goes through the authorized read path of the pinned profile, so proposals (not corpus sources), forgotten
sources, other profiles' private memory and unreadable projects can never appear; ``active_ttl_days`` expiry is applied
exactly as in ``recall`` / ``context``. Deterministic, zero LLM calls, never raises.
"""
from __future__ import annotations

import dataclasses
import re
from typing import Any, Optional

from . import learning_settings as ls
from .memory_results import BriefBundle
from .provisioning import valid_id

MAX_TASK_CHARS = 1000
MAX_WHY_TERMS = 5
LINE_CHARS = 300
DEVLOG_ENTRIES = 5
TASK_SEARCH_LIMIT = 60
MIN_CLIP_CHARS = 60
RULES_SHARE = 0.6

#: (title, memory type) in priority order.
_RULES = ("Rules", "rule")
_MATCHED = (("Decisions", "decision"), ("Gotchas", "gotcha"), ("Workflows", "workflow"), ("Skills", "skill"))
_DEVLOG = ("Recent devlog", "devlog")
_PERSONA = ("Persona", "persona")

_WORDS = re.compile(r"\w+", re.UNICODE)


def _empty(status: str, reason: Optional[str], *, max_chars: int = 0, preview: bool = False,
           enabled: bool = False) -> BriefBundle:
    return BriefBundle(status=status, reason=reason, max_chars=max_chars, preview=preview, enabled=enabled)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _clip(text: str, limit: int) -> str:
    from .memory import _clip as clip

    return clip(text, limit)


def _disabled_reason(cfg: ls.Settings, enabled: bool) -> Optional[str]:
    if not cfg.valid:
        return "settings_invalid"
    if cfg.kill_switch:
        return "kill_switch"
    if not enabled:
        return "injection_disabled"
    return None


def _terms(memory: Any, task: str) -> list:
    """Distinct lower-case task words (function words removed), in task order."""
    seen: dict = {}
    for word in _WORDS.findall(memory._search_text(task).lower()):
        seen.setdefault(word, None)
    return list(seen)


def _why(terms: list, text: str, ref: str) -> str:
    haystack = set(_WORDS.findall((text + " " + ref).lower()))
    matched = [t for t in terms if t in haystack][:MAX_WHY_TERMS]
    return ", ".join(matched) if matched else "related"


def _line(ref: str, body: str, why: Optional[str], limit: int = LINE_CHARS) -> str:
    suffix = f" (matched: {why})" if why else ""
    return f"- {ref}: {_clip(_flat(body), max(1, limit - len(suffix)))}{suffix}"


def build_brief(memory: Any, task: Any, max_chars: Any, project_id: Any, preview: Any) -> BriefBundle:
    """Implementation of :meth:`Memory.brief` (see there)."""
    try:
        if not isinstance(preview, bool):
            return _empty("invalid", "invalid_preview")
        if task is not None and not isinstance(task, str):
            return _empty("invalid", "invalid_task", preview=preview)
        if max_chars is not None and (not isinstance(max_chars, int) or isinstance(max_chars, bool)
                                      or not 1 <= max_chars <= ls.INJECTION_MAX_CHARS_HARD_CAP):
            return _empty("invalid", "invalid_max_chars", preview=preview)
        if project_id is not None and (not isinstance(project_id, str) or not valid_id(project_id)):
            return _empty("invalid", "invalid_project_id", preview=preview)
        cfg = ls.load_settings(getattr(memory, "_settings_path", None))
        policy = ls.resolve_injection(memory.profile_id, project_id, cfg)
        reason = _disabled_reason(cfg, policy.enabled)
        if reason is not None and not preview:
            return _empty("disabled", reason, max_chars=max_chars or policy.max_chars)
        if reason is not None:  # preview: the owner's view of the policy that WOULD apply, whatever blocks it now
            policy = ls.resolve_injection(memory.profile_id, project_id,
                                          dataclasses.replace(cfg, kill_switch=False, valid=True))
        budget = max_chars if max_chars is not None else policy.max_chars
        return _assemble(memory, (task or "")[:MAX_TASK_CHARS].strip(), budget, project_id, set(policy.types),
                         preview, reason)
    except Exception as exc:  # noqa: BLE001 - a read helper must never raise into an agent session
        return _empty("error", f"internal_error:{type(exc).__name__}", preview=bool(preview) is True)


def _assemble(memory: Any, task: str, budget: int, project_id: Optional[str], types: set, preview: bool,
              reason: Optional[str]) -> BriefBundle:
    requests = memory._read_requests(True, project_id)
    expired = memory._expired_sources()

    def listing(mtype: str) -> list:
        merged, _notes, _errors = memory._search(requests, "", {"memory_type": mtype}, _res_limit())
        return memory._group_sources(h for h in merged.values() if h.source_id not in expired)

    plan: list = []  # (title, mtype, [(ref, line, why)])
    if _RULES[1] in types:
        plan.append((*_RULES, [(ref, _line(ref, _join(hits), None), None) for ref, hits in listing("rule")]))
    terms = _terms(memory, task) if task else []
    if terms:
        query = memory._search_text(task)
        for title, mtype in _MATCHED:
            if mtype not in types:
                continue
            merged, _notes, _errors = memory._search(requests, query, {"memory_type": mtype}, TASK_SEARCH_LIMIT)
            hits = [h for h in merged.values() if h.source_id not in expired]
            plan.append((title, mtype, _matched_lines(memory, mtype, hits, terms)))
    if _DEVLOG[1] in types and project_id is not None:
        groups = [g for g in listing("devlog") if all(h.project_id == project_id for h in g[1])]
        groups = memory._newest_first(groups)[:DEVLOG_ENTRIES]
        plan.append((*_DEVLOG, [(ref, _line(ref, _join(hits), None), None) for ref, hits in groups]))
    if _PERSONA[1] in types:
        plan.append((*_PERSONA, [(ref, _line(ref, _join(hits), None), None) for ref, hits in listing("persona")]))
    return _fill_sections(plan, budget, preview, reason)


def _res_limit() -> int:
    from .memory import _res_limit

    return _res_limit()


def _join(hits: list) -> str:
    return " ".join(_flat(h.normalized_text) for h in hits)


def _matched_lines(memory: Any, mtype: str, hits: list, terms: list) -> list:
    by_source: dict = {}
    for hit in hits:
        by_source.setdefault(hit.source_id, []).append(hit)
    ranked = []
    for source_hits in by_source.values():
        source_hits.sort(key=lambda h: (h.unit_order, h.unit_id))
        ref = source_hits[0].external_ref or ""
        score = max(h.combined_score for h in source_hits)
        ranked.append((-score, ref, source_hits))
    ranked.sort(key=lambda row: (row[0], row[1]))
    out = []
    for _neg, ref, source_hits in ranked:
        full = _join(source_hits)
        why = _why(terms, full, ref)
        body = full
        if mtype == "skill":  # the SKILL.md front-matter description when there is one, as context() does
            described = memory._skill_line(ref, source_hits)
            body = described.split(": ", 1)[1] if ": " in described else full
        out.append((ref, _line(ref, body, why), why))
    return out


def _take(entries: list, room: int) -> list:
    """The leading entries that fit ``room`` characters (each costs its length + 1); a first line that would otherwise
    hide the whole section is clipped when at least ``MIN_CLIP_CHARS`` remain."""
    kept: list = []
    for ref, line, why in entries:
        need = len(line) + 1
        if need <= room:
            kept.append((ref, line, why))
            room -= need
            continue
        if not kept and room - 1 >= MIN_CLIP_CHARS:
            kept.append((ref, _clip(line, room - 1), why))
        break
    return kept


def _blocks(live: list, chosen: dict) -> list:
    return [f"## {title}\n" + "\n".join(k[1] for k in chosen[mtype]) for title, mtype, _e in live if chosen.get(mtype)]


def _fill_sections(plan: list, budget: int, preview: bool, reason: Optional[str]) -> BriefBundle:
    """Fill the sections in priority order. Rules come first and are always included, but while anything else could be
    shown they take at most ``RULES_SHARE`` of the budget; whatever the later sections leave unused is handed back to
    the rules, so a large rule set never hides every task-matched line and a small one never wastes space."""
    live = [(title, mtype, entries) for title, mtype, entries in plan if entries]
    others = any(mtype != "rule" for _t, mtype, _e in live)
    chosen: dict = {}
    for title, mtype, entries in live:
        so_far = _blocks(live, chosen)
        room = budget - len("\n".join(so_far)) - (1 if so_far else 0) - len(f"## {title}")
        if mtype == "rule" and others:
            room = min(room, int(budget * RULES_SHARE) - len(f"## {title}"))
        chosen[mtype] = _take(entries, room)
    for title, mtype, entries in live:  # hand the unused remainder back to the rules
        if mtype != "rule" or len(chosen[mtype]) == len(entries):
            continue
        rest = _blocks([row for row in live if row[1] != "rule"], chosen)
        room = budget - len("\n".join(rest)) - (1 if rest else 0) - len(f"## {title}")
        chosen[mtype] = _take(entries, room)
    blocks: list = []
    sections: dict = {}
    omitted: dict = {}
    sources: list = []
    items: list = []
    truncated = False
    for title, mtype, entries in live:
        kept = chosen.get(mtype, [])
        if len(kept) < len(entries):
            truncated = True
            omitted[title] = len(entries) - len(kept)
        if not kept:
            continue
        blocks.append(f"## {title}\n" + "\n".join(k[1] for k in kept))
        sections[title] = len(kept)
        for ref, _line_text, why in kept:
            sources.append(ref)
            item = {"ref": ref, "type": mtype}
            if why:
                item["why"] = why
            items.append(item)
    text = "\n".join(blocks)
    if len(text) > budget:  # defensive: never exceed the bound
        raise AssertionError("brief exceeded its budget")
    return BriefBundle(status="ok" if text else "empty", text=text, reason=reason, enabled=reason is None,
                       preview=preview, sections=sections, omitted=omitted, sources=sources, items=items,
                       truncated=truncated, max_chars=budget)


__all__ = ["build_brief"]
