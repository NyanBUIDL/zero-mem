"""T4 — map a file (name + bytes) to the registry ``kind`` hint, and walk directories safely.

Pure and stdlib only; no registration, no parsing beyond cheap sniffing. The ingest layer
(CLI / MCP write tools) uses :func:`detect_kind` to pick the ``kind`` it registers a source
with (``select_adapter(kind)`` then resolves the adapter), because adapters only receive
bytes + the kind hint, never the filename.

Returned kinds: ``pdf png jpg gif bmp webp tiff docx xlsx pptx md csv tsv json jsonl txt``
or ``binary`` (no adapter: unsupported). Bytes win over the extension, so a renamed file
cannot masquerade as another format; the extension only refines *text* (``.md``, ``.csv``,
``.json``...) and names a corrupt office container whose zip cannot be read.

:func:`iter_ingestable` walks a directory for ingestion with the safety rules an arbitrary
"ingest this path" tool needs: dotfiles/dot-dirs, ``node_modules`` and ``__pycache__`` are
skipped, symlinks are not followed by default (and when followed must stay inside the allowed
roots), only regular files are opened (FIFOs and devices are never read), oversized, empty and
unsupported-binary files are skipped, and every skip is reported with a reason.
"""
from __future__ import annotations

import codecs
import io
import json
import os
import posixpath
import stat
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional, Sequence, Union

from .adapters._common import decode_text
from .adapters._ooxml import declared_entry_count

#: Default per-file size cap for :func:`iter_ingestable` (16 MiB).
DEFAULT_MAX_BYTES = 16 * 1024 * 1024
#: Default cap on yielded files for one walk.
DEFAULT_MAX_FILES = 100_000
MAX_WALK_DEPTH = 64
EXCLUDED_DIRS = frozenset({"node_modules", "__pycache__"})

_SNIFF_BYTES = 64 * 1024
_MAX_ZIP_ENTRIES_SNIFFED = 100_000
_JSON_SNIFF_MAX = 8 * 1024 * 1024

_TEXT_EXT = {
    "md": "md", "markdown": "md", "mdown": "md", "mkd": "md",
    "csv": "csv", "tsv": "tsv", "tab": "tsv",
    "json": "json", "jsonl": "jsonl", "ndjson": "jsonl",
}
_OFFICE_EXT = frozenset({"docx", "xlsx", "pptx"})
_ZIP_MEMBER_KIND = (
    ("word/document.xml", "docx"),
    ("xl/workbook.xml", "xlsx"),
    ("ppt/presentation.xml", "pptx"),
)
_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_BINARY_MAGICS = (
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",   # OLE2: legacy doc/xls/ppt
    b"\x1f\x8b",                            # gzip
    b"\xfd7zXZ\x00",                        # xz
    b"7z\xbc\xaf\x27\x1c",                  # 7z
    b"Rar!\x1a\x07",                        # rar
    b"\x28\xb5\x2f\xfd",                    # zstd
    b"SQLite format 3\x00",
    b"\x7fELF",
)
_IMAGE_KIND = {"png": "png", "jpeg": "jpg", "gif": "gif", "bmp": "bmp", "webp": "webp", "tiff": "tiff"}


def _extension(filename: Optional[str]) -> str:
    if not filename:
        return ""
    base = posixpath.basename(filename.replace("\\", "/"))
    if "." not in base.lstrip("."):
        return ""
    return base.rpartition(".")[2].lower()


def _zip_kind(content: bytes, ext: str) -> str:
    declared = declared_entry_count(content)
    if declared is not None and declared > _MAX_ZIP_ENTRIES_SNIFFED:
        return "binary"  # never even list a hostile archive
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = set(zf.namelist())
    except Exception:
        # unreadable container: name it by extension so the adapter reports corrupt_source
        return ext if ext in _OFFICE_EXT else "binary"
    for member, kind in _ZIP_MEMBER_KIND:
        if member in names:
            return kind
    return "binary"


def _looks_like_text(content: bytes) -> bool:
    if content.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        return True
    sample = content[:_SNIFF_BYTES]
    if b"\x00" in sample:
        return False
    try:
        codecs.getincrementaldecoder("utf-8")().decode(sample, final=False)
        return True
    except UnicodeDecodeError:
        pass
    # not UTF-8: accept legacy 8-bit text only when control characters are rare
    control = sum(1 for b in sample if b < 0x20 and b not in (9, 10, 12, 13, 27))
    return control <= max(1, len(sample) // 50)


def _sniff_json(content: bytes) -> Optional[str]:
    if len(content) > _JSON_SNIFF_MAX:
        return None
    text = decode_text(content)
    if text is None:
        return None
    stripped = text.strip()
    if not stripped or stripped[0] not in "{[":
        return None
    try:
        json.loads(stripped)
        return "json"
    except (ValueError, RecursionError):
        pass
    lines = [ln.strip() for ln in stripped.split("\n") if ln.strip()]
    if len(lines) >= 2 and all(ln.startswith("{") for ln in lines[:5]):
        try:
            for ln in lines[:5]:
                json.loads(ln)
            return "jsonl"
        except (ValueError, RecursionError):
            return None
    return None


def detect_kind(filename: Optional[str], content: bytes) -> str:
    """Registry ``kind`` hint for ``content`` (see module docstring); ``"binary"`` = unsupported."""
    ext = _extension(filename)
    head = content[:32]

    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(_ZIP_MAGICS):
        return _zip_kind(content, ext)
    if any(head.startswith(m) for m in _BINARY_MAGICS):
        return "binary"
    from .adapters.image import parse_image_header  # local: keeps import graph shallow

    info = parse_image_header(content[:_SNIFF_BYTES])
    if info is not None:
        return _IMAGE_KIND[info.format]

    if not content:
        return _TEXT_EXT.get(ext, "txt")
    if not _looks_like_text(content):
        return "binary"
    if ext in _TEXT_EXT:
        return _TEXT_EXT[ext]
    return _sniff_json(content) or "txt"


# ---------------------------------------------------------------------------
# Directory walk
# ---------------------------------------------------------------------------

class IngestPathError(ValueError):
    """The requested root is missing or outside the allowed roots."""


class _ReadRefused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _read_regular(path: Union[str, Path], *, max_bytes: int, follow_symlinks: bool) -> bytes:
    """Read a regular file without ever blocking on FIFOs or following a swapped-in symlink."""
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    if not follow_symlinks:
        flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise _ReadRefused("not_regular_file")
        if st.st_size > max_bytes:
            raise _ReadRefused("oversized")
    except BaseException:
        os.close(fd)
        raise
    with os.fdopen(fd, "rb") as fh:
        data = fh.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise _ReadRefused("oversized")
    return data


@dataclass(frozen=True)
class SkipRecord:
    relative_name: str
    reason: str
    detail: str = ""


@dataclass(frozen=True)
class Ingestable:
    """One ingestable file. Unpacks as ``(relative_name, path, kind)``."""

    relative_name: str
    path: Path
    kind: str
    _max_bytes: int = field(default=DEFAULT_MAX_BYTES, repr=False, compare=False)
    _follow: bool = field(default=False, repr=False, compare=False)

    def __iter__(self) -> Iterator:
        yield self.relative_name
        yield self.path
        yield self.kind

    def read_bytes(self) -> bytes:
        return _read_regular(self.path, max_bytes=self._max_bytes, follow_symlinks=self._follow)


class IngestWalk:
    """Lazy, deterministic (name-sorted) walk. ``skipped`` fills in as iteration proceeds."""

    def __init__(
        self,
        path: Union[str, Path],
        *,
        allow_roots: Optional[Sequence[Union[str, Path]]] = None,
        max_bytes: int = DEFAULT_MAX_BYTES,
        follow_symlinks: bool = False,
        include_unsupported: bool = False,
        max_files: int = DEFAULT_MAX_FILES,
    ) -> None:
        self.skipped: list[SkipRecord] = []
        self._root = Path(path)
        self._max_bytes = max_bytes
        self._follow = follow_symlinks
        self._include_unsupported = include_unsupported
        self._max_files = max_files
        self._yielded = 0
        self._stopped = False

        if not os.path.lexists(self._root):
            raise IngestPathError("path_not_found")
        real_root = self._root.resolve()
        if allow_roots is not None:
            self._roots = [Path(r).resolve() for r in allow_roots]
            if not self._within(real_root):
                raise IngestPathError("path_outside_allow_roots")
        else:
            self._roots = [real_root if self._root.is_dir() else real_root.parent]

    # -- helpers ---------------------------------------------------------

    def _within(self, target: Path) -> bool:
        return any(target == r or r in target.parents for r in self._roots)

    def _skip(self, name: str, reason: str, detail: str = "") -> None:
        self.skipped.append(SkipRecord(name, reason, detail))

    def skip_report(self) -> dict:
        counts = Counter(s.reason for s in self.skipped)
        return {
            "total": len(self.skipped),
            "by_reason": dict(sorted(counts.items())),
            "skipped": [
                {"name": s.relative_name, "reason": s.reason, "detail": s.detail} for s in self.skipped
            ],
        }

    # -- iteration -------------------------------------------------------

    def __iter__(self) -> Iterator[Ingestable]:
        root = self._root
        try:
            lst = os.lstat(root)
        except OSError:
            self._skip(root.name, "unreadable")
            return
        if stat.S_ISLNK(lst.st_mode):
            if not self._follow:
                self._skip(root.name, "symlink")
                return
            real = root.resolve()
            if not self._within(real):
                self._skip(root.name, "outside_allowed_roots")
                return
            st = os.stat(root)
        else:
            st = lst
        if stat.S_ISDIR(st.st_mode):
            yield from self._walk(root, "", {(st.st_dev, st.st_ino)}, 0)
        elif stat.S_ISREG(st.st_mode):
            yield from self._file(root.name, root, st)
        else:
            self._skip(root.name, "not_regular_file")

    def _walk(self, directory: Path, prefix: str, ancestors: set, depth: int) -> Iterator[Ingestable]:
        if depth > MAX_WALK_DEPTH:
            self._skip(prefix.rstrip("/") or ".", "max_depth")
            return
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError:
            self._skip(prefix.rstrip("/") or ".", "unreadable")
            return
        for entry in entries:
            if self._stopped:
                return
            name = entry.name
            rel = f"{prefix}{name}"
            if name.startswith("."):
                self._skip(rel, "hidden")
                continue
            try:
                lst = entry.stat(follow_symlinks=False)
            except OSError:
                self._skip(rel, "unreadable")
                continue
            target = Path(entry.path)
            st = lst
            if stat.S_ISLNK(lst.st_mode):
                if not self._follow:
                    self._skip(rel, "symlink")
                    continue
                try:
                    real = target.resolve(strict=True)
                    st = os.stat(target)
                except (OSError, RuntimeError):
                    self._skip(rel, "broken_symlink")
                    continue
                if not self._within(real):
                    self._skip(rel, "outside_allowed_roots")
                    continue
            if stat.S_ISDIR(st.st_mode):
                if name in EXCLUDED_DIRS:
                    self._skip(rel, "excluded_dir")
                    continue
                key = (st.st_dev, st.st_ino)
                if key in ancestors:
                    self._skip(rel, "symlink_loop")
                    continue
                yield from self._walk(target, rel + "/", ancestors | {key}, depth + 1)
            elif stat.S_ISREG(st.st_mode):
                yield from self._file(rel, target, st)
            else:
                self._skip(rel, "not_regular_file")

    def _file(self, rel: str, path: Path, st: os.stat_result) -> Iterator[Ingestable]:
        if st.st_size == 0:
            self._skip(rel, "empty")
            return
        if st.st_size > self._max_bytes:
            self._skip(rel, "oversized", f"{st.st_size} bytes > {self._max_bytes}")
            return
        if self._yielded >= self._max_files:
            self._skip(rel, "max_files_reached", f"cap {self._max_files}")
            self._stopped = True
            return
        try:
            data = _read_regular(path, max_bytes=self._max_bytes, follow_symlinks=self._follow)
        except _ReadRefused as exc:
            self._skip(rel, exc.reason)
            return
        except OSError:
            self._skip(rel, "unreadable")
            return
        kind = detect_kind(rel, data)
        if kind == "binary" and not self._include_unsupported:
            self._skip(rel, "unsupported_binary")
            return
        self._yielded += 1
        yield Ingestable(rel, path, kind, self._max_bytes, self._follow)


def iter_ingestable(
    path: Union[str, Path],
    allow_roots: Optional[Sequence[Union[str, Path]]] = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    follow_symlinks: bool = False,
    *,
    include_unsupported: bool = False,
    max_files: int = DEFAULT_MAX_FILES,
) -> IngestWalk:
    """Walk ``path`` (a directory or one file) yielding :class:`Ingestable` items.

    Each item unpacks as ``(relative_name, path, kind)`` and offers ``read_bytes()``.
    Iterate the returned walk, then read ``.skipped`` / :meth:`IngestWalk.skip_report`.
    Raises :class:`IngestPathError` immediately for a missing root or one outside
    ``allow_roots``. With ``follow_symlinks`` every followed target must stay inside
    ``allow_roots`` (or, when not given, inside the walk root).
    """
    return IngestWalk(
        path,
        allow_roots=allow_roots,
        max_bytes=max_bytes,
        follow_symlinks=follow_symlinks,
        include_unsupported=include_unsupported,
        max_files=max_files,
    )


__all__ = [
    "DEFAULT_MAX_BYTES", "DEFAULT_MAX_FILES", "EXCLUDED_DIRS", "IngestPathError", "IngestWalk",
    "Ingestable", "SkipRecord", "detect_kind", "iter_ingestable",
]
