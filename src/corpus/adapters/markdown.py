"""T4 — Markdown adapter (stdlib line scanner; CommonMark/GFM subset).

Units (ids are line anchored: ``<source_ref>#<k><start_line>``):

- ``fm``           YAML front matter -> one ``metadata`` unit (skill name/description live here)
- ``h<L>``         ATX / setext headings -> ``heading``; ``parent_ref`` = enclosing heading id
- ``p<L>``         paragraphs / lists / quotes -> ``text`` chunked to ~800 chars (``.k`` suffix)
- ``c<L>``         fenced code blocks -> ``code`` (language kept in ``meta``, which is not persisted)
- ``t<L>r<k>``     GFM pipe-table rows -> ``table`` with ``"col=value; ..."`` text

Every non-heading unit's ``parent_ref`` is the most recent heading (its section).
Text is passed through verbatim: secret rejection is the pipeline's job.
"""
from __future__ import annotations

import re
from typing import Optional

from .base import FormatAdapter, FormatKind
from ._common import (
    DEFAULT_MAX_UNITS,
    HeadingTracker,
    UnitSink,
    build_result,
    decode_text,
    normalize_newlines,
)
from ..extract import ExtractionResult, ExtractionStatus

_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+|$)(.*)$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_THEMATIC = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_DELIM_CELL = re.compile(r"^:?-+:?$")
_FRONT_KEY = re.compile(r"^[\w.\-]+[ \t]*:")


# NOTE: fences and ATX closing sequences are scanned by hand, not with regexes: the
# regex forms backtrack quadratically on adversarial lines (a heading with 200k inner
# spaces took 140 s), and Markdown here is untrusted input.

def _fence_open(line: str) -> Optional[tuple[str, int, str]]:
    """``(fence char, fence length, language)`` if ``line`` opens a fenced code block."""
    body = line.lstrip(" ")
    if len(line) - len(body) > 3 or not body or body[0] not in "`~":
        return None
    ch = body[0]
    run = 0
    while run < len(body) and body[run] == ch:
        run += 1
    if run < 3:
        return None
    info = body[run:].strip()
    if ch == "`" and "`" in info:
        return None
    return ch, run, (info.split()[0] if info else "")


def _is_fence_close(line: str, ch: str, length: int) -> bool:
    body = line.lstrip(" ")
    if len(line) - len(body) > 3:
        return False
    run = 0
    while run < len(body) and body[run] == ch:
        run += 1
    return run >= length and body[run:].strip() == ""


def _strip_atx_closing(text: str) -> str:
    """Drop an optional closing ``###`` sequence (must be preceded by whitespace)."""
    s = text.rstrip()
    j = len(s)
    while j > 0 and s[j - 1] == "#":
        j -= 1
    if j == len(s):
        return s
    if j == 0:
        return ""
    return s[:j].rstrip() if s[j - 1] in " \t" else s


def _split_row(line: str) -> list[str]:
    """Split a GFM table row on unescaped pipes (outer pipes optional)."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells: list[str] = []
    cur: list[str] = []
    k = 0
    while k < len(s):
        ch = s[k]
        if ch == "\\" and k + 1 < len(s) and s[k + 1] == "|":
            cur.append("|")
            k += 2
            continue
        if ch == "|":
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        k += 1
    cells.append("".join(cur).strip())
    return cells


def _is_delimiter_row(line: str) -> bool:
    if "|" not in line:
        return False
    cells = _split_row(line)
    return bool(cells) and all(_DELIM_CELL.match(c) for c in cells)


class MarkdownAdapter(FormatAdapter):
    format = FormatKind.MD
    parser_name = "builtin:markdown"

    def __init__(self, max_units: int = DEFAULT_MAX_UNITS) -> None:
        self.max_units = max_units

    def is_available(self) -> bool:
        return True

    def supports(self, kind_hint: str) -> bool:
        return FormatKind.detect(kind_hint) == FormatKind.MD

    def extract(self, *, source_ref: str, content: bytes, kind_hint: str) -> ExtractionResult:
        if not content:
            return self._fail(source_ref, ExtractionStatus.EMPTY_SOURCE, "empty source bytes", byte_length=0)
        text = decode_text(content, reject_binary=True)
        if text is None:
            return self._fail(
                source_ref, ExtractionStatus.CORRUPT_SOURCE,
                "binary content (NUL bytes) is not markdown text", byte_length=len(content),
            )
        lines = normalize_newlines(text).split("\n")
        sink = UnitSink(source_ref, self.max_units)
        try:
            self._scan(lines, sink)
        except Exception as exc:  # defensive: never let a parser bug escape
            return self._fail(
                source_ref, ExtractionStatus.ADAPTER_FAILED,
                f"markdown scan failure: {type(exc).__name__}", byte_length=len(content),
            )
        return build_result(
            self, sink, source_ref=source_ref, byte_length=len(content),
            empty_reason="no extractable markdown content",
        )

    # -- scanner ---------------------------------------------------------

    def _scan(self, lines: list[str], sink: UnitSink) -> None:
        n = len(lines)
        tracker = HeadingTracker()
        para: list[str] = []
        para_start = 0

        def flush_para() -> None:
            nonlocal para, para_start
            if para:
                sink.add_chunks(f"p{para_start}", "text", "\n".join(para), parent_ref=tracker.current)
            para = []

        def add_heading(level: int, heading_text: str, line_no: int) -> None:
            if not heading_text.strip():
                return
            parent = tracker.parent_for(level)
            uid = sink.add_heading(f"h{line_no}", heading_text, parent_ref=parent)
            if uid is not None:
                tracker.enter(level, uid)

        i = self._front_matter(lines, sink)
        while i < n:
            if sink.full and lines[i].strip():
                sink.truncated = True
                break
            line = lines[i]
            line_no = i + 1

            if line.strip() == "":
                flush_para()
                i += 1
                continue

            fence = _fence_open(line)
            if fence is not None:
                flush_para()
                fence_ch, fence_len, lang = fence
                body: list[str] = []
                i += 1
                while i < n and not _is_fence_close(lines[i], fence_ch, fence_len):
                    body.append(lines[i])
                    i += 1
                i += 1  # closing fence (or EOF)
                code = "\n".join(body)
                if code.strip():
                    sink.add_chunks(f"c{line_no}", "code", code, parent_ref=tracker.current,
                                    meta={"lang": lang} if lang else None)
                continue

            m = _ATX.match(line)
            if m:
                flush_para()
                rest = _strip_atx_closing(m.group(2).strip())
                add_heading(len(m.group(1)), rest, line_no)
                i += 1
                continue

            if para:
                m = _SETEXT.match(line)
                if m:
                    # "Text\n====" / "Text\n----" is a setext heading (CommonMark)
                    level = 1 if m.group(1)[0] == "=" else 2
                    add_heading(level, " ".join(p.strip() for p in para), para_start)
                    para = []
                    i += 1
                    continue
                if _THEMATIC.match(line):
                    flush_para()
                    i += 1
                    continue
            elif _THEMATIC.match(line):
                i += 1
                continue

            if "|" in line and i + 1 < n and _is_delimiter_row(lines[i + 1]):
                headers = _split_row(line)
                if len(headers) == len(_split_row(lines[i + 1])):
                    flush_para()
                    i = self._table(lines, i, headers, sink, tracker)
                    continue

            if not para:
                para_start = line_no
            para.append(line.rstrip())
            i += 1

        flush_para()

    @staticmethod
    def _front_matter(lines: list[str], sink: UnitSink) -> int:
        """Emit a ``metadata`` unit for ``---``-fenced YAML front matter; return next line index."""
        if not lines or lines[0].strip() != "---":
            return 0
        for j in range(1, min(len(lines), 200)):
            if lines[j].strip() in ("---", "..."):
                block = lines[1:j]
                if any(_FRONT_KEY.match(b) for b in block):
                    body = "\n".join(block).strip()
                    if body:
                        sink.add_chunks("fm", "metadata", body)
                    return j + 1
                return 0
        return 0

    @staticmethod
    def _table(lines: list[str], i: int, headers: list[str], sink: UnitSink, tracker: HeadingTracker) -> int:
        header_line = i + 1
        names = [h if h else f"col{k}" for k, h in enumerate(headers, start=1)]
        j = i + 2
        row_idx = 0
        emitted = False
        while j < len(lines) and lines[j].strip() != "" and "|" in lines[j]:
            row_idx += 1
            cells = _split_row(lines[j])
            pairs = [f"{names[k]}={cells[k]}" for k in range(min(len(names), len(cells))) if cells[k]]
            if pairs:
                sink.add_chunks(f"t{header_line}r{row_idx}", "table", "; ".join(pairs), parent_ref=tracker.current)
                emitted = True
            j += 1
        if not emitted:
            summary = " | ".join(h for h in headers if h)
            if summary:
                sink.add_chunks(f"t{header_line}", "table", summary, parent_ref=tracker.current)
        return j


__all__ = ["MarkdownAdapter"]
