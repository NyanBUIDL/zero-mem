"""T4 — JSON / JSONL / NDJSON adapter: chat logs first, plain JSON documents second.

Recognised chat shapes (stdlib ``json`` only):

- ``{"role": ..., "content": ...}`` messages, as a JSON array or one per JSONL line
  (``content`` may be a string or a list of typed parts; non-text parts are ignored,
  ``tool_result`` text is kept)
- ``{"messages": [...]}`` conversations (OpenAI style, also one per JSONL line)
- ChatGPT export conversations: ``{"title", "mapping": {...}, "current_node"}`` - the
  active branch is linearised from ``current_node`` up through ``parent`` links
- Claude export conversations: ``{"name", "chat_messages": [{"sender", "text"}]}``
- Claude Code style transcript lines ``{"type": "user", "message": {...}}`` (the
  wrapper is unwrapped; non-message lines such as summaries are ignored)

Unit ids (1-based positions, so an id points back into the source):

- single conversation / message list: ``#m<pos>`` (+ ``#title`` heading when named)
- list of conversations: ``#c<k>`` heading + ``#c<k>m<pos>`` messages
- plain JSON: ``#j<n>``, leaves ``path.to.key: value`` packed up to ~800 chars

Message text is ``"<role>: <content>"`` (role prefix repeated on every chunk of a
long message). Anything that is not chat is flattened to key paths, bounded by
``max_leaves`` / ``max_depth``.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from .base import FormatAdapter, FormatKind
from ._common import (
    DEFAULT_MAX_UNITS,
    MAX_CHUNK_CHARS,
    UnitSink,
    build_result,
    chunk_text,
    collapse_ws,
    decode_text,
)
from ..extract import ExtractionResult, ExtractionStatus

DEFAULT_MAX_MESSAGES = 50_000
DEFAULT_MAX_LEAVES = 100_000
DEFAULT_MAX_DEPTH = 64
_MAX_CONTENT_DEPTH = 8
_DEEP_VALUE_CHARS = 400

_ROLE_ALIASES = {"human": "user"}
#: A list is a chat log when messages are at least 1/_CHAT_SHARE of its object items.
_CHAT_SHARE = 5


class _InvalidJson(Exception):
    pass


# ---------------------------------------------------------------------------
# Message / conversation recognition
# ---------------------------------------------------------------------------

def _flatten_text(value: Any, depth: int = 0) -> str:
    """Text of a message ``content``: strings, typed text parts, nested part lists."""
    if depth > _MAX_CONTENT_DEPTH or value is None or isinstance(value, bool):
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = [_flatten_text(v, depth + 1) for v in value]
        return "\n".join(p for p in parts if p.strip())
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str):
            return text
        if "parts" in value:
            return _flatten_text(value["parts"], depth + 1)
        if "content" in value:  # e.g. tool_result
            return _flatten_text(value["content"], depth + 1)
    return ""


def _role_of(obj: dict) -> Optional[str]:
    for key in ("role", "sender", "author"):
        raw = obj.get(key)
        if isinstance(raw, dict):
            raw = raw.get("role")
        if isinstance(raw, str) and raw.strip():
            role = raw.strip().lower()
            return _ROLE_ALIASES.get(role, role)
    return None


def _message(obj: Any, depth: int = 0) -> Optional[tuple[str, str]]:
    """``(role, text)`` if ``obj`` looks like a chat message (text may be empty)."""
    if not isinstance(obj, dict) or depth > 2:
        return None
    inner = obj.get("message")
    if isinstance(inner, dict):
        found = _message(inner, depth + 1)
        if found is not None:
            return found
    role = _role_of(obj)
    if role is None or not any(k in obj for k in ("content", "text", "parts")):
        return None
    for key in ("text", "content", "parts"):
        text = _flatten_text(obj.get(key))
        if text.strip():
            return role, text
    return role, ""


def _mapping_path(mapping: dict, current: Any) -> list[dict]:
    """Active branch of a ChatGPT ``mapping`` tree, root first; cycle/dangling safe."""
    nodes: list[str] = []
    seen: set[str] = set()
    if isinstance(current, str) and current in mapping:
        node_id: Any = current
        while isinstance(node_id, str) and node_id in mapping and node_id not in seen:
            seen.add(node_id)
            nodes.append(node_id)
            node = mapping[node_id]
            node_id = node.get("parent") if isinstance(node, dict) else None
        nodes.reverse()
    else:
        roots = [
            nid for nid, node in mapping.items()
            if isinstance(node, dict) and (node.get("parent") is None or node.get("parent") not in mapping)
        ]
        node_id = roots[0] if roots else None
        while isinstance(node_id, str) and node_id in mapping and node_id not in seen:
            seen.add(node_id)
            nodes.append(node_id)
            children = mapping[node_id].get("children") if isinstance(mapping[node_id], dict) else None
            node_id = children[-1] if isinstance(children, list) and children else None
    return [mapping[nid] for nid in nodes if isinstance(mapping[nid], dict)]


def _conversation_messages(obj: Any) -> Optional[list[tuple[int, str, str]]]:
    """``[(position, role, text)]`` for conversation-shaped dicts, else ``None``."""
    if not isinstance(obj, dict):
        return None
    out: list[tuple[int, str, str]] = []
    if isinstance(obj.get("mapping"), dict):
        for pos, node in enumerate(_mapping_path(obj["mapping"], obj.get("current_node")), start=1):
            msg = node.get("message")
            if not isinstance(msg, dict):
                continue
            meta = msg.get("metadata")
            if isinstance(meta, dict) and meta.get("is_visually_hidden_from_conversation"):
                continue
            found = _message(msg)
            if found and found[1].strip():
                out.append((pos, found[0], found[1]))
        return out
    for key in ("chat_messages", "messages"):
        seq = obj.get(key)
        if isinstance(seq, list):
            for pos, item in enumerate(seq, start=1):
                found = _message(item)
                if found and found[1].strip():
                    out.append((pos, found[0], found[1]))
            return out
    return None


def _title_of(obj: dict) -> str:
    for key in ("title", "name"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return collapse_ws(val)
    return ""


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class JsonAdapter(FormatAdapter):
    format = FormatKind.JSON
    parser_name = "builtin:json"

    def __init__(
        self,
        max_messages: int = DEFAULT_MAX_MESSAGES,
        max_leaves: int = DEFAULT_MAX_LEAVES,
        max_depth: int = DEFAULT_MAX_DEPTH,
        max_units: int = DEFAULT_MAX_UNITS,
    ) -> None:
        self.max_messages = max_messages
        self.max_leaves = max_leaves
        self.max_depth = max_depth
        self.max_units = max_units

    def is_available(self) -> bool:
        return True

    def supports(self, kind_hint: str) -> bool:
        return FormatKind.detect(kind_hint) == FormatKind.JSON

    def extract(self, *, source_ref: str, content: bytes, kind_hint: str) -> ExtractionResult:
        if not content:
            return self._fail(source_ref, ExtractionStatus.EMPTY_SOURCE, "empty source bytes", byte_length=0)
        text = decode_text(content, reject_binary=True)
        if text is None:
            return self._fail(
                source_ref, ExtractionStatus.CORRUPT_SOURCE,
                "binary content (NUL bytes) is not json text", byte_length=len(content),
            )
        text = text.strip()
        if not text:
            return self._fail(source_ref, ExtractionStatus.EMPTY_SOURCE, "blank source", byte_length=len(content))

        notes: list[str] = []
        try:
            value, records = self._parse(text, notes)
        except _InvalidJson as exc:
            return self._fail(source_ref, ExtractionStatus.CORRUPT_SOURCE, str(exc), byte_length=len(content))

        sink = UnitSink(source_ref, self.max_units)
        try:
            self._emit(sink, value, records, notes)
        except Exception as exc:  # defensive: never let a parser bug escape
            return self._fail(
                source_ref, ExtractionStatus.ADAPTER_FAILED,
                f"json extraction failure: {type(exc).__name__}", byte_length=len(content),
            )
        return build_result(
            self, sink, source_ref=source_ref, byte_length=len(content),
            notes=notes, empty_reason="no extractable values",
        )

    # -- parsing ---------------------------------------------------------

    @staticmethod
    def _parse(text: str, notes: list[str]) -> tuple[Any, Optional[list[tuple[int, Any]]]]:
        """Whole-document parse, else JSON Lines. Returns ``(value, None)`` or ``(None, records)``."""
        try:
            return json.loads(text), None
        except (ValueError, RecursionError):
            pass
        records: list[tuple[int, Any]] = []
        bad: list[int] = []
        for lineno, line in enumerate(text.split("\n"), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append((lineno, json.loads(line)))
            except (ValueError, RecursionError):
                bad.append(lineno)
        if not records:
            raise _InvalidJson("invalid json: neither a document nor json lines")
        if bad:
            shown = ",".join(str(n) for n in bad[:5])
            notes.append(f"{len(bad)} unparseable json line(s) skipped (lines {shown}{'...' if len(bad) > 5 else ''})")
        return None, records

    # -- emission --------------------------------------------------------

    def _emit(self, sink: UnitSink, value: Any, records: Optional[list[tuple[int, Any]]], notes: list[str]) -> None:
        if records is not None:
            items = records                                   # JSONL: position = line number
            container: Any = [v for _n, v in records]
        elif isinstance(value, list):
            items = list(enumerate(value, start=1))           # JSON array: position = index
            container = value
        else:
            items = None
            container = value

        state = {"messages": 0, "stop": False}

        if items is None:
            if isinstance(container, dict):
                conv = _conversation_messages(container)
                if conv:
                    self._emit_conversation(sink, container, conv, "", notes, state)
                    return
                single = _message(container)
                if single and single[1].strip():
                    self._emit_messages(sink, [(1, single[0], single[1])], None, "", notes, state)
                    return
            self._emit_plain(sink, container, notes)
            return

        dict_items = [(pos, v) for pos, v in items if isinstance(v, dict)]
        # Real chat logs interleave non-message records (Claude Code transcripts: attachments,
        # queue operations, summaries...), so chat only needs to be a clear minority share.
        convs = [(pos, v, c) for pos, v in dict_items if (c := _conversation_messages(v))]
        if convs and len(convs) * _CHAT_SHARE >= len(dict_items):
            for pos, conv_obj, conv in convs:
                if state["stop"]:
                    break
                self._emit_conversation(sink, conv_obj, conv, f"c{pos}", notes, state)
            return
        msgs = []
        for pos, v in dict_items:
            found = _message(v)
            if found and found[1].strip():
                msgs.append((pos, found[0], found[1]))
        if msgs and len(msgs) * _CHAT_SHARE >= len(dict_items):
            self._emit_messages(sink, msgs, None, "", notes, state)
            return
        self._emit_plain(sink, container, notes)

    def _emit_conversation(
        self, sink: UnitSink, conv_obj: dict, conv: list[tuple[int, str, str]],
        prefix: str, notes: list[str], state: dict,
    ) -> None:
        title = _title_of(conv_obj)
        head_id: Optional[str] = None
        if title:
            head_id = sink.add_heading(prefix or "title", title)
        self._emit_messages(sink, conv, head_id, prefix, notes, state)

    def _emit_messages(
        self, sink: UnitSink, msgs: list[tuple[int, str, str]], parent: Optional[str],
        prefix: str, notes: list[str], state: dict,
    ) -> None:
        for pos, role, text in msgs:
            if state["messages"] >= self.max_messages:
                if not state["stop"]:
                    notes.append(f"message cap reached ({self.max_messages}); remaining messages skipped")
                state["stop"] = True
                return
            if sink.full:
                sink.truncated = True
                state["stop"] = True
                return
            state["messages"] += 1
            sink.add_chunks(f"{prefix}m{pos}", "text", text, prefix=f"{role}: ", parent_ref=parent)

    # -- plain documents -------------------------------------------------

    def _emit_plain(self, sink: UnitSink, value: Any, notes: list[str]) -> None:
        leaves: list[str] = []
        capped = self._leaves(value, "", 0, leaves)
        if capped:
            notes.append(f"leaf cap reached ({self.max_leaves}); remaining values skipped")
        n = 0
        buf: list[str] = []
        size = 0

        def flush() -> None:
            nonlocal n, buf, size
            if buf:
                n += 1
                sink.add(f"j{n}", "text", "; ".join(buf))
            buf, size = [], 0

        for leaf in leaves:
            if len(leaf) > MAX_CHUNK_CHARS:
                flush()
                for piece in chunk_text(leaf, MAX_CHUNK_CHARS):
                    n += 1
                    sink.add(f"j{n}", "text", piece)
                continue
            if buf and size + 2 + len(leaf) > MAX_CHUNK_CHARS:
                flush()
            buf.append(leaf)
            size += len(leaf) + (2 if len(buf) > 1 else 0)
        flush()

    def _leaves(self, value: Any, path: str, depth: int, out: list[str]) -> bool:
        """Append ``"path: value"`` leaves in document order. Returns True if the leaf cap hit."""
        if len(out) >= self.max_leaves:
            return True
        if isinstance(value, (dict, list)) and depth >= self.max_depth:
            dumped = json.dumps(value, ensure_ascii=False, default=str)[:_DEEP_VALUE_CHARS]
            out.append(f"{path or '$'}: {dumped}")
            return False
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else str(key)
                if self._leaves(child, child_path, depth + 1, out):
                    return True
            return False
        if isinstance(value, list):
            for idx, child in enumerate(value):
                if self._leaves(child, f"{path}[{idx}]", depth + 1, out):
                    return True
            return False
        if value is None:
            return False
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, str):
            if not value.strip():
                return False
            rendered = value
        else:
            rendered = str(value)
        out.append(f"{path or '$'}: {rendered}")
        return False


__all__ = ["JsonAdapter"]
