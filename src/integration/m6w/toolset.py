"""T6b - the MCP memory tool set: five agent-oriented tools that delegate to :class:`zero_mem.memory.Memory`.

``memory_recall`` / ``memory_context`` / ``memory_brief`` (read; the brief is gated by the owner's injection settings),
``memory_propose`` (only with ``--enable-propose``: an inert proposal for the owner's review) and ``memory_add`` / ``memory_ingest`` / ``memory_forget`` (write, only
when the server was started with ``--enable-write``). Every call:

* runs as the ONE profile the server is pinned to (the tool set has no way to act as another profile and rejects
  any identity / scope-authority argument);
* is validated against the closed JSON schema it advertises;
* goes through ``Memory`` (authorize -> secret pre-scan -> cross-process lock -> register -> project), so a write
  is exactly as safe as ``zero-mem add``;
* returns an MCP ``tools/call`` result ``{content, structuredContent, isError}`` with a structured status
  (``SUCCESS`` / ``EMPTY`` / ``PARTIAL`` / ``DENIED`` / ``REJECTED_SECRET`` / ``REJECTED_CONTENT`` / ``INVALID`` /
  ``NOT_FOUND`` / ``ERROR``), bounded in size, and NEVER raises or leaks a path, SQL or exception text.

A fresh ``Memory`` is built per call (no stale registry or grant cache in a long-lived server process: a grant the
operator adds or revokes takes effect on the next call).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from zero_mem.memory import Memory
from zero_mem.memory_bootstrap import ensure_layout
from zero_mem.memory_layout import Layout, LayoutError
from zero_mem.provisioning import valid_id

from . import contracts as c
from .pathguard import PathGuard, RootsConfigError, normalize_roots

_ENV_MAX_FILES = "ZM_M6_INGEST_MAX_FILES"
_ENV_MAX_BYTES = "ZM_M6_INGEST_MAX_BYTES"
_DEVLOG_PROJECT_RE = re.compile(r"^mem://devlog/([^/]+)/")


class ToolSetConfigError(ValueError):
    """The memory tool set cannot be built (sanitized message, never a path or a value)."""


@dataclass(frozen=True)
class ToolSetConfig:
    """Bounds of ``memory_ingest`` and of its report (the per-file cap is the library's 16 MiB)."""

    max_ingest_files: int = 200
    max_ingest_bytes: int = 64 * 1024 * 1024
    report_items: int = 10

    def __post_init__(self) -> None:
        for name in ("max_ingest_files", "max_ingest_bytes", "report_items"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ToolSetConfigError(f"{name} must be a positive integer")


def _config_from_env() -> ToolSetConfig:
    values: Dict[str, int] = {}
    for env_name, key in ((_ENV_MAX_FILES, "max_ingest_files"), (_ENV_MAX_BYTES, "max_ingest_bytes")):
        raw = (os.environ.get(env_name) or "").strip()
        if not raw:
            continue
        try:
            number = int(raw)
        except ValueError:
            raise ToolSetConfigError(f"{env_name} must be a positive integer") from None
        if number < 1:
            raise ToolSetConfigError(f"{env_name} must be a positive integer")
        values[key] = number
    return ToolSetConfig(**values)


# ----------------------------------------------------------------------------------------------------------------
# results
# ----------------------------------------------------------------------------------------------------------------
def _flat(text: Any) -> str:
    return " ".join(str(text).split())


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1].rstrip() + "…"


def _snippet(text: str, terms: Sequence[str], limit: int) -> "tuple[str, bool]":
    """``text`` cut to at most ``limit`` characters, as ``(snippet, was_cut)``.

    A text that fits is returned whole. A longer one keeps its head, unless the first query term only occurs later:
    then the window is centred on that term (so a hit never hides the very words it matched), with an ellipsis on
    every side that was cut. Always a word boundary, never longer than ``limit``.
    """
    if len(text) <= limit:
        return text, False
    lower = text.lower()
    found = [i for i in (lower.find(t) for t in terms) if i >= 0]
    first = min(found) if found else -1
    if first < limit - 40:
        return _clip(text, limit), True
    start = max(0, first - 60)
    space = text.find(" ", start, first)
    if space >= 0:
        start = space + 1
    end = start + limit - 2  # room for the two ellipses
    body = text[start:end]
    if end < len(text):
        cut = body.rfind(" ")
        if cut > len(body) // 2:
            body = body[:cut]
    tail = "…" if end < len(text) else ""
    return "…" + body.rstrip() + tail, True


def _short(source_id: Optional[str]) -> Optional[str]:
    return source_id[: c.SOURCE_ID_SHORT] if source_id else None


def make_result(tool: str, status: str, *, reason_code: Optional[str] = None, message: Optional[str] = None,
                data: Optional[Dict[str, Any]] = None, text: Optional[str] = None) -> Dict[str, Any]:
    """One MCP ``tools/call`` result. ``content`` is what a text-only client shows the model.

    Token budget: ``structuredContent`` is what some clients hand to the model, so it carries no echo of the tool name
    (the caller knows what it called); only ``content[0].text`` names the tool, for a human reading a failure.
    """
    structured: Dict[str, Any] = {"status": status}
    if reason_code:
        structured["reason_code"] = reason_code
    if message:
        structured["message"] = message
    for key, value in (data or {}).items():
        if value is not None:
            structured[key] = value
    if text is None:
        text = f"{tool}: {status}" + (f" ({reason_code})" if reason_code else "") + (f" - {message}" if message else "")
        hint = structured.get("operator_hint")
        if hint:
            text += f" {hint}."
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
        "isError": status not in c.OK_STATUSES,
    }


def _hint(profile: str, scope: Optional[str], project_id: Optional[str], space: str) -> str:
    if scope == "shared":
        return f"Ask the operator to run: zero-mem agents grant-write {profile} --space {space}"
    if scope == "project" and project_id:
        return f"Ask the operator to run: zero-mem agents grant-write {profile} --project {project_id}"
    return "Ask the operator to review this agent's grants: zero-mem agents list"


_INVALID_MESSAGES = {
    "invalid_text": "The text is empty or not valid text.",
    "text_too_large": "The text is too large; ingest a file instead.",
    "invalid_name": "The name may use letters, digits and . _ : ~ + @ % - with / between parts (max 128).",
    "invalid_project_id": "The project id may use letters, digits and . _ - (max 64).",
    "project_id_required": "scope=project needs a project_id.",
    "project_id_not_allowed": "project_id only applies to scope=project.",
    "devlog_requires_project_scope": "A devlog entry belongs to a project: use scope=project with a project_id.",
    "invalid_memory_type": "Unknown memory_type.",
    "invalid_scope": "Unknown scope.",
    "empty_query": "The query has no searchable words.",
    "name_too_long": "The name is too long.",
    "invalid_task": "The task must be text.",
    "invalid_max_chars": "max_chars must be between 1 and 8000.",
    "invalid_evidence": "evidence must be up to 5 short strings.",
    "text_too_large": "The text is too large.",
}
_REJECT_MESSAGES = {
    "learning_off": "The owner has switched learning off. Tell the user if it matters; do not retry.",
    "kill_switch": "The owner's kill switch is on. Do not retry.",
    "agent_proposals_disallowed": "The owner does not accept agent proposals. Tell the user instead.",
    "daily_limit": "The daily proposal limit is reached. Do not retry today.",
    "deny_pattern": "The owner's policy refuses this text. Do not retry it.",
    "settings_invalid": "Learning is off: the owner's settings file is unusable. Tell the user.",
    "proposal_log_too_large": "The proposal queue is full. Tell the user.",
}


# ----------------------------------------------------------------------------------------------------------------
# the tool set
# ----------------------------------------------------------------------------------------------------------------
class MemoryToolSet:
    """Mountable extension of the pinned M6 server (see ``mcp_server.mount_tool_set``)."""

    def __init__(self, profile_id: str, layout: Layout, *, enable_write: bool, guard: PathGuard,
                 config: ToolSetConfig, enable_propose: bool = False) -> None:
        self._profile = profile_id
        self._layout = layout
        self._write = bool(enable_write)
        self._propose = bool(enable_propose)
        self._guard = guard
        self._config = config
        self._handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
            c.TOOL_RECALL: self._recall,
            c.TOOL_CONTEXT: self._context,
            c.TOOL_BRIEF: self._brief,
        }
        if self._write:
            self._handlers.update({c.TOOL_ADD: self._add, c.TOOL_INGEST: self._ingest, c.TOOL_FORGET: self._forget})
        if self._propose:
            self._handlers[c.TOOL_PROPOSE] = self._propose_memory

    # -- the mount protocol ---------------------------------------------------------------------------------
    @property
    def profile_id(self) -> str:
        return self._profile

    @property
    def store_path(self) -> Path:
        return self._layout.derived_db

    @property
    def write_enabled(self) -> bool:
        return self._write

    @property
    def propose_enabled(self) -> bool:
        return self._propose

    @property
    def names(self) -> tuple:
        return c.READ_TOOLS + (c.WRITE_TOOLS if self._write else ()) + (c.PROPOSE_TOOLS if self._propose else ())

    @property
    def instructions(self) -> str:
        """Short usage guide for the ``initialize`` result (clients such as Claude Code show it to the model)."""
        return (c.SERVER_INSTRUCTIONS + (c.SERVER_INSTRUCTIONS_WRITE if self._write else "")
                + (c.SERVER_INSTRUCTIONS_PROPOSE if self._propose else ""))

    def startup_notes(self) -> List[str]:
        """Operator-facing warnings for the server's stderr (never sent to a client)."""
        notes: List[str] = []
        try:
            memory = self._memory()
            try:
                status = memory.status()
            finally:
                memory.close()
            if not status.get("can_read_shared"):
                notes.append(f"WARNING profile '{self._profile}' cannot read the shared space {self._space()} "
                             f"(a typo in --profile-id?): run `zero-mem agents add {self._profile}`")
        except Exception:  # noqa: BLE001 - a warning must never stop the server
            pass
        return notes

    def schemas(self) -> List[Dict[str, Any]]:
        return c.tool_definitions(write=self._write, propose=self._propose)

    def handles(self, name: Any) -> bool:
        return isinstance(name, str) and name in self._handlers

    def call(self, name: Any, arguments: Any) -> Dict[str, Any]:
        """Run one tool call. Total: every outcome, including an unexpected failure, is a structured result."""
        tool = name if isinstance(name, str) and len(name) <= 64 else "unknown"
        try:
            if not isinstance(name, str) or name not in self._handlers:
                return make_result(tool, c.INVALID, reason_code=c.UNKNOWN_TOOL, message="Unknown tool.")
            if not isinstance(arguments, dict):
                return make_result(tool, c.INVALID, reason_code=c.INVALID_ARGUMENTS,
                                   message="Arguments must be an object.")
            denial = c.authority_violation(arguments)
            if denial is not None:
                return make_result(tool, c.DENIED, reason_code=denial[0], message=denial[1])
            problem = c.validate_arguments(name, arguments)
            if problem is not None:
                return make_result(tool, c.INVALID, reason_code=problem[0], message=problem[1])
            return self._handlers[name](arguments)
        except Exception:  # noqa: BLE001 - never raise to the client, never leak the cause
            return make_result(tool, c.ERROR, reason_code=c.INTERNAL_ERROR,
                               message="The memory operation failed. Nothing was changed that you can rely on.")

    # -- helpers ---------------------------------------------------------------------------------------------
    def _memory(self) -> Memory:
        return Memory(self._profile, self._layout, channel="mcp")

    def _space(self) -> str:
        return Memory.SHARED_SPACE

    def _failure(self, tool: str, status: str, reason: Optional[str], **kw: Any) -> Dict[str, Any]:
        """Map a library failure status to the MCP vocabulary (fixed codes, no detail from exceptions)."""
        if status == "error" or (reason or "").startswith("internal_error"):
            return make_result(tool, c.ERROR, reason_code=c.INTERNAL_ERROR,
                               message="The memory operation failed. Try again later or tell the operator.")
        if status == "invalid":
            message = _INVALID_MESSAGES.get(reason or "", "The request is not valid.")
            return make_result(tool, c.INVALID, reason_code=reason or c.SCHEMA_VIOLATION, message=message)
        return make_result(tool, c.ERROR, reason_code=c.INTERNAL_ERROR, message="The memory operation failed.")

    def _denied(self, tool: str, reason: Optional[str], scope: Optional[str], project_id: Optional[str]) -> Dict[str, Any]:
        if reason == "learned_type_requires_proposal":
            return make_result(tool, c.DENIED, reason_code=reason,
                               message="rule, decision and gotcha are not written directly. Use memory_propose; the "
                                       "owner reviews it before it becomes memory.")
        hint = _hint(self._profile, scope, project_id, self._space())
        forgetting = tool == c.TOOL_FORGET
        verb = "Forgetting" if forgetting else "Writing to"
        target = {"shared": "a shared memory" if forgetting else "the shared space",
                  "project": "a project memory" if forgetting else "this project"}.get(scope or "")
        if target:
            message = f"{verb} {target} needs the operator's approval. Tell the user" + (
                "." if forgetting else ", or use scope=private.")
        else:
            message = "This is not permitted for this agent."
        return make_result(tool, c.DENIED, reason_code=reason or "DENIED", message=message,
                           data={"operator_hint": hint})

    # -- memory_recall ---------------------------------------------------------------------------------------
    def _recall(self, args: Dict[str, Any]) -> Dict[str, Any]:
        tool = c.TOOL_RECALL
        memory = self._memory()
        try:
            result = memory.recall(
                args["query"], memory_types=args.get("memory_types"),
                limit=args.get("limit", c.RECALL_DEFAULT_LIMIT), project_id=args.get("project_id"))
        finally:
            memory.close()
        if result.status == "denied":
            return make_result(tool, c.DENIED, reason_code=result.reason or "DENIED",
                               message="This agent may not read memory.")
        if result.status != "ok" and result.status != "empty":
            return self._failure(tool, result.status, result.reason)
        terms = [w for w in re.findall(r"\w+", str(args["query"]).lower()) if len(w) >= 3]
        hits: List[Dict[str, Any]] = []
        used = 0
        truncated = False
        for hit in result.hits:
            text, cut = _snippet(_flat(hit.text), terms, c.HIT_TEXT_CHARS)
            if hits and used + len(text) > c.RECALL_TOTAL_CHARS:
                truncated = True
                break
            used += len(text)
            truncated = truncated or cut
            row = {"id": _short(hit.source_id), "type": hit.memory_type, "ref": hit.external_ref,
                   "score": round(float(hit.score), 2), "text": text}
            hits.append({k: v for k, v in row.items() if v is not None})
        warning = None
        project = args.get("project_id")
        if project and str(result.notes.get("project", "")).startswith("DENY"):
            warning = "That project's dev log is not readable by this agent (needs the operator's read grant)."
        if not hits:
            return make_result(tool, c.EMPTY, data={"warning": warning},
                               text=f"{tool}: EMPTY - " + (warning or "nothing matched"))
        lines = []
        for index, h in enumerate(hits, 1):
            lines.append(f"{index}. {h.get('type', '-')} {h.get('ref', '-')} {h['score']} id={h['id']}")
            lines.append(f"   {h['text']}")
        if truncated:
            lines.append("(text was trimmed or hits were cut for size)")
        if warning:
            lines.append(warning)
        return make_result(tool, c.SUCCESS, data={"hits": hits, "truncated": truncated or None, "warning": warning},
                           text="\n".join(lines))

    # -- memory_context --------------------------------------------------------------------------------------
    def _context(self, args: Dict[str, Any]) -> Dict[str, Any]:
        tool = c.TOOL_CONTEXT
        max_chars = args.get("max_chars", c.CONTEXT_DEFAULT_CHARS)
        memory = self._memory()
        try:
            bundle = memory.context(max_chars=max_chars, project_id=args.get("project_id"))
        finally:
            memory.close()
        if bundle.status not in ("ok", "empty"):
            return self._failure(tool, bundle.status, bundle.reason)
        text = bundle.text
        # Only the text (and a cut flag): clients such as Claude Code hand ``structuredContent`` to the model, so every
        # field costs tokens. The size, the section counts and the source list are not echoed.
        if not text:
            return make_result(tool, c.EMPTY, message="Nothing saved yet.")
        return make_result(tool, c.SUCCESS, data={"text": text, "truncated": True if bundle.truncated else None},
                           text=text)

    # -- memory_brief ----------------------------------------------------------------------------------------
    def _brief(self, args: Dict[str, Any]) -> Dict[str, Any]:
        tool = c.TOOL_BRIEF
        memory = self._memory()
        try:
            bundle = memory.brief(args.get("task"), max_chars=args.get("max_chars"))
        finally:
            memory.close()
        if bundle.status == "disabled":
            return make_result(tool, c.EMPTY, reason_code=bundle.reason,
                               message="Injection is off; the owner enables it in settings (injection.enabled).")
        if bundle.status not in ("ok", "empty"):
            return self._failure(tool, bundle.status, bundle.reason)
        if not bundle.text:
            return make_result(tool, c.EMPTY, message="No rules or matching memory yet.")
        # like memory_context: only the text (refs are inside it) and a cut flag
        return make_result(tool, c.SUCCESS, data={"text": bundle.text, "truncated": True if bundle.truncated else None},
                           text=bundle.text)

    # -- memory_propose --------------------------------------------------------------------------------------
    def _propose_memory(self, args: Dict[str, Any]) -> Dict[str, Any]:
        tool = c.TOOL_PROPOSE
        memory = self._memory()
        try:
            result = memory.propose(args["text"], args["memory_type"], name=args.get("name"), scope=args["scope"],
                                    project_id=args.get("project_id"), evidence=args.get("evidence"), source="agent")
        finally:
            memory.close()
        if result.ok:
            return make_result(
                tool, c.PROPOSED,
                message="Recorded for the owner's review. It is not memory until the owner approves it.",
                data={"proposal_id": result.proposal_id},
                text=f"{tool}: PROPOSED {result.proposal_id} - pending the owner's review; not saved or recalled yet")
        if result.status == "rejected_secret":
            return make_result(
                tool, c.REJECTED_SECRET, reason_code=result.reason or "secret_detected",
                message="A credential-like value was detected. Nothing was stored. Remove the secret and retry.",
                data={"rule_ids": list(result.rule_ids or ())})
        if result.status == "rejected":
            message = _REJECT_MESSAGES.get(result.reason or "", "The owner's settings do not allow this proposal.")
            return make_result(tool, c.REJECTED, reason_code=result.reason or "rejected", message=message)
        return self._failure(tool, result.status, result.reason)

    # -- memory_add ------------------------------------------------------------------------------------------
    def _add(self, args: Dict[str, Any]) -> Dict[str, Any]:
        tool = c.TOOL_ADD
        scope, project = args["scope"], args.get("project_id")
        memory = self._memory()
        try:
            result = memory.add(args["text"], args["memory_type"], name=args.get("name"), scope=scope,
                                project_id=project)
        finally:
            memory.close()
        return self._write_outcome(tool, result, scope, project)

    def _write_outcome(self, tool: str, result: Any, scope: Optional[str], project: Optional[str]) -> Dict[str, Any]:
        if result.ok:
            data = {"result": result.status, "ref": result.external_ref, "id": _short(result.source_id),
                    "scope": result.scope}
            text = f"{tool}: SUCCESS - {result.status} {result.external_ref} ({result.scope})"
            return make_result(tool, c.SUCCESS, data=data, text=text)
        if result.status == "denied":
            return self._denied(tool, result.reason, scope, project)
        if result.status == "rejected_secret":
            return make_result(
                tool, c.REJECTED_SECRET, reason_code=result.reason or "secret_detected",
                message="A credential-like value was detected. Nothing was stored. Remove the secret and retry.",
                data={"rule_ids": list(result.rule_ids or ())})
        if result.status == "rejected_content":
            return make_result(tool, c.REJECTED_CONTENT, reason_code=result.reason or "unsupported_format",
                               message="This content cannot be stored (unsupported, corrupt or empty). "
                                       "Nothing was stored.")
        return self._failure(tool, result.status, result.reason)

    # -- memory_forget ---------------------------------------------------------------------------------------
    def _forget(self, args: Dict[str, Any]) -> Dict[str, Any]:
        tool = c.TOOL_FORGET
        memory = self._memory()
        try:
            result = memory.forget(args["source_id"])
        finally:
            memory.close()
        if result.ok:
            data = {"result": result.status, "ref": result.external_ref, "id": _short(result.source_id)}
            return make_result(tool, c.SUCCESS, data=data,
                               text=f"{tool}: SUCCESS - {result.status} {result.external_ref or ''}".rstrip())
        if result.status == "not_found":
            return make_result(tool, c.NOT_FOUND, reason_code=result.reason or "unknown_source",
                               message="No memory with that id or ref is visible to you.")
        if result.status == "ambiguous":
            # the library lists only sources this agent can read (T8); candidates are still not forwarded: the agent
            # picks by the id memory_recall printed
            return make_result(tool, c.INVALID, reason_code=c.AMBIGUOUS_REFERENCE,
                               message="Several memories match that ref. Pass the id from memory_recall.")
        if result.status == "denied":
            if result.reason == "DENY_GLOBAL_WRITE":
                return make_result(tool, c.DENIED, reason_code=result.reason,
                                   message="Operator-curated memory cannot be forgotten by an agent.")
            project = _DEVLOG_PROJECT_RE.match(result.external_ref or "")
            scope = "project" if project else "shared"
            return self._denied(tool, result.reason, scope, project.group(1) if project else None)
        return self._failure(tool, result.status, result.reason)

    # -- memory_ingest ---------------------------------------------------------------------------------------
    def _ingest(self, args: Dict[str, Any]) -> Dict[str, Any]:
        tool = c.TOOL_INGEST
        verdict = self._guard.check(args["path"])
        if not verdict.ok:
            return self._path_refusal(tool, verdict)
        scope, project = args["scope"], args.get("project_id")
        memory = self._memory()
        try:
            report = memory.ingest(
                verdict.path, memory_type=args["memory_type"], scope=scope, project_id=project,
                allow_roots=self._guard.real_roots, max_files=self._config.max_ingest_files,
                max_total_bytes=self._config.max_ingest_bytes)
        finally:
            memory.close()
        single_file = verdict.path is not None and verdict.path.is_file()
        return self._ingest_outcome(tool, report, scope, project, single_file)

    def _path_refusal(self, tool: str, verdict: Any) -> Dict[str, Any]:
        messages = {
            c.DENY_NO_ALLOWED_ROOTS: "Ingest is disabled: the operator has not allowed any folder (--allow-root).",
            c.DENY_PATH_OUTSIDE_ALLOWLIST: "That path is outside the folders the operator allowed for ingest.",
            c.DENY_SYMLINK: "Symlinks are not followed. Pass the real path of a regular file or folder.",
            c.DENY_PATH_RESERVED: "That path belongs to the memory store itself and cannot be ingested.",
            c.PATH_MUST_BE_ABSOLUTE: "path must be absolute (no ~ and no relative path).",
            c.PATH_NOT_FOUND: "No such file or folder.",
            c.UNSUPPORTED_PATH_TYPE: "Only regular files and folders can be ingested.",
            c.INVALID_ARGUMENTS: "path is not valid.",
        }
        return make_result(tool, verdict.status, reason_code=verdict.code,
                           message=messages.get(verdict.code, "That path cannot be ingested."))

    def _ingest_outcome(self, tool: str, report: Any, scope: str, project: Optional[str], single_file: bool) -> Dict[str, Any]:
        if report.status == "denied":
            return self._denied(tool, report.reason, scope, project)
        if report.status == "invalid":
            reason = report.reason or c.SCHEMA_VIOLATION
            if reason in ("path_not_found",):
                return make_result(tool, c.INVALID, reason_code=c.PATH_NOT_FOUND, message="No such file or folder.")
            if reason in ("path_outside_allow_roots",):
                return make_result(tool, c.DENIED, reason_code=c.DENY_PATH_OUTSIDE_ALLOWLIST,
                                   message="That path is outside the folders the operator allowed for ingest.")
            return self._failure(tool, "invalid", reason)
        if report.status == "error":
            return self._failure(tool, "error", report.reason)
        counts = report.counts
        stored = counts.get("created", 0) + counts.get("updated", 0) + counts.get("unchanged", 0)
        rejected_secret = counts.get("rejected_secret", 0)
        rejected_other = sum(counts.get(k, 0) for k in ("rejected_content", "invalid", "error", "denied"))
        rejected = rejected_secret + rejected_other
        limit = self._config.report_items
        rejected_items = [
            {"name": _clip(_flat(f.name or f.external_ref or "?"), 120),
             "status": {"rejected_secret": c.REJECTED_SECRET, "rejected_content": c.REJECTED_CONTENT,
                        "denied": c.DENIED}.get(f.status, c.INVALID if f.status == "invalid" else c.ERROR),
             "reason": "secret_detected" if f.status == "rejected_secret" else (
                 c.INTERNAL_ERROR if f.status == "error" else (f.reason or "rejected"))}
            for f in report.files if f.status in ("rejected_secret", "rejected_content", "invalid", "error", "denied")]
        skipped_items = [{"name": _clip(_flat(s.get("name", "?")), 120), "reason": _flat(s.get("reason", "skipped"))}
                         for s in report.skipped]
        stored_refs = [f.external_ref for f in report.files if f.ok and f.status in ("created", "updated")]
        data = {
            "counts": {"created": counts.get("created", 0), "updated": counts.get("updated", 0),
                       "unchanged": counts.get("unchanged", 0), "rejected": rejected, "skipped": len(skipped_items)},
            # empty lists are omitted: Claude Code hands structuredContent to the model, so every key costs tokens
            "created": stored_refs[:limit] or None,
            "rejected": rejected_items[:limit] or None,
            "skipped": skipped_items[:limit] or None,
            "omitted": max(0, len(stored_refs) - limit) + max(0, len(rejected_items) - limit)
                       + max(0, len(skipped_items) - limit) or None,
        }
        loud_skip = report.status == "partial" and not rejected
        if rejected == 0 and not loud_skip:
            status = c.SUCCESS if stored else c.EMPTY
        elif stored == 0:
            if rejected_secret and not rejected_other:
                status = c.REJECTED_SECRET
            else:
                status = c.REJECTED_CONTENT if rejected else c.EMPTY
        else:
            status = c.PARTIAL
        if status == c.EMPTY and single_file and skipped_items:
            status = c.REJECTED_CONTENT  # the one file the caller named was not storable
        reason = None
        if status == c.REJECTED_CONTENT and not rejected_items and skipped_items:
            skip = skipped_items[0]["reason"]
            reason = {"unsupported_binary": "unsupported_format", "empty": "empty_source",
                      "oversized": "content_too_large"}.get(skip, skip)
        elif status == c.REJECTED_SECRET:
            reason = "secret_detected"
        elif status == c.REJECTED_CONTENT and rejected_items:
            reason = rejected_items[0]["reason"]
        head = (f"{tool}: {status} - {counts.get('created', 0)} created, {counts.get('updated', 0)} updated, "
                f"{counts.get('unchanged', 0)} unchanged, {rejected} rejected, {len(skipped_items)} skipped")
        lines = [head]
        for item in rejected_items[:limit]:
            lines.append(f"  rejected {item['name']}: {item['reason']}")
        for item in skipped_items[:limit]:
            lines.append(f"  skipped {item['name']}: {item['reason']}")
        if rejected_secret:
            lines.append("Files with a credential were rejected and NOT stored.")
        message = None
        if status == c.EMPTY:
            message = "Nothing ingestable was found there."
        return make_result(tool, status, reason_code=reason, message=message, data=data, text="\n".join(lines))


# ----------------------------------------------------------------------------------------------------------------
# construction
# ----------------------------------------------------------------------------------------------------------------
def build_tool_set(*, profile_id: Any, layout: Optional[Layout] = None, enable_write: bool = False,
                   allow_roots: Sequence[Any] = (), config: Optional[ToolSetConfig] = None,
                   enable_propose: bool = False) -> MemoryToolSet:
    """Validate the pin and the roots, ensure the storage layout, and return the mountable tool set.

    ``layout=None`` uses the standard data root (``ZERO_MEM_DATA_ROOT`` / XDG), exactly what ``zero-mem setup`` and
    the CLI use, so the tools and the M6 read tools see one database.
    """
    if not valid_id(profile_id):
        raise ToolSetConfigError("profile id must match [A-Za-z0-9][A-Za-z0-9._-]{0,63}")
    try:
        roots = normalize_roots(allow_roots)
    except RootsConfigError as exc:
        raise ToolSetConfigError(str(exc)) from None
    try:
        resolved = layout if layout is not None else Layout.resolve(None)
        ensure_layout(resolved)  # race-safe: every agent's server may start at the same moment
    except LayoutError:
        raise ToolSetConfigError("the zero-mem data root cannot be set up (run zero-mem doctor)") from None
    reserved = [resolved.data_root, resolved.corpus_root, resolved.memory_stream.parent, resolved.derived_db.parent]
    return MemoryToolSet(profile_id, resolved, enable_write=enable_write, guard=PathGuard(roots, reserved),
                         config=config if config is not None else _config_from_env(),
                         enable_propose=enable_propose)


__all__ = ["MemoryToolSet", "ToolSetConfig", "ToolSetConfigError", "build_tool_set", "make_result"]
