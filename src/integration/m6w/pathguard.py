"""T6b - the path policy of ``memory_ingest``: an allowlist of operator-chosen roots, no symlinks, no memory store.

Without this an "ingest this path" tool is an arbitrary-file-read primitive for a prompt-injected agent. The rules,
checked in this order and answered with a fixed reason code that never echoes a path:

1. the path is a bounded string without control characters and is ABSOLUTE (no ``~``, no relative path);
2. after ``normpath`` (``..`` collapsed) it lies inside one allowed root, else ``DENY_PATH_OUTSIDE_ALLOWLIST``
   (checked before existence, so a path outside the roots reveals nothing about the file system);
3. no component below the root is a symlink (``lstat``), else ``DENY_SYMLINK``; the root itself is the operator's
   choice and may be a symlink;
4. the fully resolved path is still inside the resolved root (belt and braces);
5. it neither is, contains nor lies inside the memory's own data/corpus directories, else ``DENY_PATH_RESERVED``;
6. it exists and is a regular file or a directory, else ``PATH_NOT_FOUND`` / ``UNSUPPORTED_PATH_TYPE``.

The library re-checks the same boundary when it walks a folder (``Memory.ingest(allow_roots=...)``) and opens files
with ``O_NOFOLLOW``; a symlink met while walking a folder is skipped, never followed.
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence, Tuple

from . import contracts as c


class RootsConfigError(ValueError):
    """An ``--allow-root`` value is unusable (the message never contains the value)."""


@dataclass(frozen=True)
class PathVerdict:
    ok: bool
    status: str = ""
    code: str = ""
    path: Optional[Path] = None  # the resolved target when ok

    @staticmethod
    def refuse(status: str, code: str) -> "PathVerdict":
        return PathVerdict(False, status, code)


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def normalize_roots(values: Iterable[Any]) -> List[Tuple[str, str]]:
    """``[(lexical, resolved)]`` for each root; raises :class:`RootsConfigError` for anything but an existing,
    absolute directory that is not the file system root."""
    roots: List[Tuple[str, str]] = []
    for value in values:
        if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
            raise RootsConfigError("--allow-root must be an absolute path to an existing directory")
        raw = os.fspath(value)
        if not os.path.isabs(raw):
            raise RootsConfigError("--allow-root must be an absolute path to an existing directory")
        lexical = os.path.normpath(raw)
        try:
            resolved = os.path.realpath(lexical)
            is_dir = os.path.isdir(resolved)
        except (OSError, ValueError):
            is_dir = False
        if not is_dir:
            raise RootsConfigError("--allow-root must be an absolute path to an existing directory")
        if resolved == os.path.abspath(os.sep) or lexical == os.path.abspath(os.sep):
            raise RootsConfigError("--allow-root may not be the file system root")
        pair = (lexical, resolved)
        if pair not in roots:
            roots.append(pair)
    return roots


class PathGuard:
    """Decides whether a caller-supplied path may be ingested."""

    def __init__(self, roots: Sequence[Tuple[str, str]], reserved: Iterable[Path]) -> None:
        self._roots = list(roots)
        self._reserved = [Path(p) for p in reserved]

    @property
    def has_roots(self) -> bool:
        return bool(self._roots)

    @property
    def real_roots(self) -> List[str]:
        return [resolved for _lex, resolved in self._roots]

    # ------------------------------------------------------------------------------------------------------
    def check(self, raw: Any) -> PathVerdict:
        if not self._roots:
            return PathVerdict.refuse(c.DENIED, c.DENY_NO_ALLOWED_ROOTS)
        if not isinstance(raw, str) or not raw or len(raw) > c.MAX_PATH_CHARS \
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
            return PathVerdict.refuse(c.INVALID, c.INVALID_ARGUMENTS)
        if not os.path.isabs(raw):
            return PathVerdict.refuse(c.INVALID, c.PATH_MUST_BE_ABSOLUTE)
        lexical = os.path.normpath(raw)

        base = self._containing_root(lexical)
        if base is None:
            return PathVerdict.refuse(c.DENIED, c.DENY_PATH_OUTSIDE_ALLOWLIST)
        lex_root, real_root, form = base

        walked = self._first_symlink_or_missing(lexical, form)
        if walked == "symlink":
            return PathVerdict.refuse(c.DENIED, c.DENY_SYMLINK)

        try:
            resolved = os.path.realpath(lexical)
        except (OSError, ValueError):
            return PathVerdict.refuse(c.INVALID, c.PATH_NOT_FOUND)
        if not _under(resolved, real_root):
            return PathVerdict.refuse(c.DENIED, c.DENY_PATH_OUTSIDE_ALLOWLIST)
        if self._touches_reserved(Path(resolved)):
            return PathVerdict.refuse(c.DENIED, c.DENY_PATH_RESERVED)

        if walked == "missing":
            return PathVerdict.refuse(c.INVALID, c.PATH_NOT_FOUND)
        try:
            mode = os.lstat(resolved).st_mode
        except OSError:
            return PathVerdict.refuse(c.INVALID, c.PATH_NOT_FOUND)
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            return PathVerdict.refuse(c.INVALID, c.UNSUPPORTED_PATH_TYPE)
        return PathVerdict(True, path=Path(resolved))

    # ------------------------------------------------------------------------------------------------------
    def _containing_root(self, lexical: str) -> Optional[Tuple[str, str, str]]:
        """``(lexical root, resolved root, the form of the root ``lexical`` lies under)``."""
        for lex_root, real_root in self._roots:
            for form in (lex_root, real_root):
                if _under(lexical, form):
                    return lex_root, real_root, form
        return None

    @staticmethod
    def _first_symlink_or_missing(lexical: str, root_form: str) -> str:
        """``"symlink"`` when a component below the root is a symlink, ``"missing"`` when one does not exist."""
        if lexical == root_form:
            return ""
        rest = lexical[len(root_form.rstrip(os.sep)):].lstrip(os.sep)
        current = root_form
        for part in rest.split(os.sep):
            current = os.path.join(current, part)
            try:
                if stat.S_ISLNK(os.lstat(current).st_mode):
                    return "symlink"
            except FileNotFoundError:
                return "missing"
            except OSError:
                return "missing"
        return ""

    def _touches_reserved(self, resolved: Path) -> bool:
        for reserved in self._reserved:
            try:
                target = Path(os.path.realpath(reserved))
            except (OSError, ValueError):
                continue
            if resolved == target or target in resolved.parents or resolved in target.parents:
                return True
        return False


__all__ = ["PathGuard", "PathVerdict", "RootsConfigError", "normalize_roots"]
