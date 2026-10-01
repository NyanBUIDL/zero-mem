"""Shared helpers for the stdlib FormatAdapters (T4): decoding, chunking, unit sink.

Everything here is pure, deterministic and dependency free. It deliberately does
NOT sanitize text: the only secret boundary is ``require_safe`` in the corpus
projection (design section 2), so adapters must pass text through verbatim.
"""
from __future__ import annotations

from typing import Iterable, Optional

from ..extract import ExtractionResult, ExtractionStatus, ExtractionUnit

#: Target size of one prose/row/message unit. Smaller units rank and recall better
#: than whole documents (design section 2: "chunk long prose ~800 chars").
MAX_CHUNK_CHARS = 800

#: Hard ceiling on units emitted per source by any adapter (partial beyond it).
DEFAULT_MAX_UNITS = 50_000

#: Defensive per-unit ceiling in :meth:`UnitSink.add` (adapters chunk to MAX_CHUNK_CHARS
#: first; this only bounds a unit an adapter forgot to chunk).
MAX_UNIT_CHARS = 4_000

_SENTENCE_END = ".!?"
_CJK_END = "。！？；"


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------

def decode_text(content: bytes, *, reject_binary: bool = False) -> Optional[str]:
    """Decode text bytes deterministically.

    Order: UTF-8 BOM, UTF-16 BOM (Windows ``>`` redirects / "Unicode text" exports),
    UTF-8, then Latin-1 (lossless fallback, so the result is never ``None`` unless
    ``reject_binary`` is set and the payload looks binary: NUL bytes without a
    UTF-16 BOM). A leading BOM character is always removed.
    """
    if content.startswith(b"\xef\xbb\xbf"):
        text = content[3:].decode("utf-8", errors="replace")
    elif content.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            text = content.decode("utf-16")
        except UnicodeDecodeError:
            text = content.decode("utf-16", errors="replace")
    else:
        if reject_binary and b"\x00" in content[:8192]:
            return None
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
    return text.lstrip("﻿") if text.startswith("﻿") else text


def collapse_ws(text: str) -> str:
    return " ".join(text.split())


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _find_cut(text: str, pos: int, max_chars: int) -> int:
    """Absolute index in ``(pos, pos + max_chars]`` at which to cut (more than ``max_chars`` remain)."""
    window = text[pos:pos + max_chars]
    floor_line = max_chars // 2
    nl = window.rfind("\n")
    if nl >= floor_line:
        return pos + nl + 1
    for p in range(len(window) - 1, floor_line - 1, -1):
        ch = window[p]
        if ch in _CJK_END or (ch in _SENTENCE_END and text[pos + p + 1].isspace()):
            return pos + p + 1
    # last whitespace of any kind
    ws = max(window.rfind(" "), window.rfind("\t"), window.rfind("\n"))
    if ws >= max_chars // 4:
        return pos + ws + 1
    return pos + max_chars  # unbroken token (base64, minified blob, CJK without spaces)


def chunk_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split ``text`` into chunks of at most ``max_chars`` characters.

    Prefers line breaks, then sentence ends, then whitespace, then a hard cut, so
    chunks stay readable. Lossless apart from whitespace at chunk boundaries;
    deterministic and linear in the input size. Returns ``[]`` for empty /
    whitespace-only input.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be >= 1")
    s = text.strip()
    n = len(s)
    out: list[str] = []
    pos = 0
    while pos < n:
        while pos < n and s[pos].isspace():
            pos += 1
        if pos >= n:
            break
        if n - pos <= max_chars:
            out.append(s[pos:].rstrip())
            break
        cut = _find_cut(s, pos, max_chars)
        piece = s[pos:cut].rstrip()
        if piece:
            out.append(piece)
        pos = cut
    return out


def split_paragraphs(text: str) -> list[tuple[int, str]]:
    """Blank-line separated paragraphs as ``(start_line_1based, text)``.

    ``text`` must already use ``\\n`` newlines. Lines holding only whitespace are
    separators; line breaks inside a paragraph are preserved in the text.
    """
    paragraphs: list[tuple[int, str]] = []
    buf: list[str] = []
    start = 0
    for lineno, line in enumerate(text.split("\n"), start=1):
        if line.strip() == "":
            if buf:
                paragraphs.append((start, "\n".join(buf)))
                buf = []
            continue
        if not buf:
            start = lineno
        buf.append(line)
    if buf:
        paragraphs.append((start, "\n".join(buf)))
    return paragraphs


# ---------------------------------------------------------------------------
# Heading hierarchy
# ---------------------------------------------------------------------------

class HeadingTracker:
    """Tracks the enclosing heading chain so units can set ``parent_ref``.

    A heading's parent is the nearest preceding heading of a strictly lower
    level; any other unit's parent is the most recent heading (the section it
    sits in). Levels: 0 (document title) .. 6+.
    """

    def __init__(self) -> None:
        self._stack: list[tuple[int, str]] = []

    def parent_for(self, level: int) -> Optional[str]:
        while self._stack and self._stack[-1][0] >= level:
            self._stack.pop()
        return self._stack[-1][1] if self._stack else None

    def enter(self, level: int, unit_id: str) -> None:
        self._stack.append((level, unit_id))

    @property
    def current(self) -> Optional[str]:
        return self._stack[-1][1] if self._stack else None


# ---------------------------------------------------------------------------
# Unit sink
# ---------------------------------------------------------------------------

class UnitSink:
    """Collects ``ExtractionUnit``s with sequential ``order`` and a hard unit cap."""

    def __init__(self, source_ref: str, max_units: int = DEFAULT_MAX_UNITS) -> None:
        self.source_ref = source_ref
        self.max_units = max_units
        self.units: list[ExtractionUnit] = []
        self.truncated = False
        self.clipped = 0
        self._ids: set[str] = set()

    @property
    def full(self) -> bool:
        return len(self.units) >= self.max_units

    def add(
        self,
        suffix: str,
        kind: str,
        text: str,
        *,
        page: Optional[int] = None,
        parent_ref: Optional[str] = None,
        meta: Optional[dict] = None,
    ) -> Optional[str]:
        """Append one unit; returns its id, or ``None`` when the cap was hit."""
        if self.full:
            self.truncated = True
            return None
        if len(text) > MAX_UNIT_CHARS:
            text = text[:MAX_UNIT_CHARS]
            self.clipped += 1
        unit_id = f"{self.source_ref}#{suffix}"
        if unit_id in self._ids:  # malformed sources can repeat ids (e.g. footnote ids); keep ids unique
            k = 2
            while f"{unit_id}~{k}" in self._ids:
                k += 1
            unit_id = f"{unit_id}~{k}"
        self._ids.add(unit_id)
        self.units.append(ExtractionUnit(
            unit_id=unit_id,
            kind=kind,
            text=text,
            source_ref=self.source_ref,
            order=len(self.units) + 1,
            page=page,
            parent_ref=parent_ref,
            meta=meta or {},
        ))
        return unit_id

    def add_heading(
        self,
        suffix: str,
        text: str,
        *,
        page: Optional[int] = None,
        parent_ref: Optional[str] = None,
    ) -> Optional[str]:
        """Add a ``heading`` bounded to ~800 chars; any overflow follows as ``text`` units
        (ids ``suffix.1``...) parented to the heading, so nothing is lost or unbounded."""
        pieces = chunk_text(collapse_ws(text), MAX_CHUNK_CHARS)
        if not pieces:
            return None
        uid = self.add(suffix, "heading", pieces[0], page=page, parent_ref=parent_ref)
        if uid is not None:
            for k, extra in enumerate(pieces[1:], start=1):
                if self.add(f"{suffix}.{k}", "text", extra, page=page, parent_ref=uid) is None:
                    break
        return uid

    def add_chunks(
        self,
        suffix: str,
        kind: str,
        text: str,
        *,
        prefix: str = "",
        page: Optional[int] = None,
        parent_ref: Optional[str] = None,
        meta: Optional[dict] = None,
        max_chars: int = MAX_CHUNK_CHARS,
    ) -> Optional[str]:
        """Chunk ``text`` to the cap; ids are ``suffix``, ``suffix.1``, ``suffix.2``...

        ``prefix`` (e.g. ``"user: "``) is repeated on every chunk and counted
        against the cap. Returns the id of the first chunk (``None`` if nothing
        was added).
        """
        budget = max(max_chars - len(prefix), 80)
        first: Optional[str] = None
        for k, piece in enumerate(chunk_text(text, budget)):
            uid = self.add(suffix if k == 0 else f"{suffix}.{k}", kind, prefix + piece,
                           page=page, parent_ref=parent_ref, meta=meta)
            if uid is None:
                break
            if first is None:
                first = uid
        return first


def build_result(
    adapter,
    sink: UnitSink,
    *,
    source_ref: str,
    byte_length: int,
    notes: Iterable[str] = (),
    empty_reason: str = "no extractable content",
    parser_name: Optional[str] = None,
) -> ExtractionResult:
    """Finish an extraction: empty -> ``empty_source``; capped/noted -> ``partial``."""
    note_list = [n for n in notes if n]
    if sink.clipped:
        note_list.append(f"{sink.clipped} oversized unit(s) clipped to {MAX_UNIT_CHARS} chars")
    if sink.truncated:
        note_list.append(f"unit cap reached ({sink.max_units}); remaining content skipped")
    if not sink.units:
        return adapter._fail(source_ref, ExtractionStatus.EMPTY_SOURCE, empty_reason, byte_length)
    status = ExtractionStatus.PARTIAL if note_list else ExtractionStatus.COMPLETE
    return ExtractionResult(
        source_ref=source_ref,
        status=status.value,
        units=tuple(sink.units),
        parser_name=parser_name or adapter.parser_name,
        error_reason="; ".join(note_list) if note_list else None,
        byte_length=byte_length,
    )


__all__ = [
    "MAX_CHUNK_CHARS", "MAX_UNIT_CHARS", "DEFAULT_MAX_UNITS", "decode_text", "normalize_newlines",
    "chunk_text", "split_paragraphs", "HeadingTracker", "UnitSink", "build_result", "collapse_ws",
]
