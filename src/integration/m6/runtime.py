"""M6.2 runtime — TRUE READ-ONLY store + grant-connection access.

Holds only the configured derived SQLite path (set at startup, never hard-coded
per repo/user). Opens connections strictly read-only. No writes, no migrations,
no JSONL, no grant administration.

V141 (DEF-012): optional ``corpus_store_path`` configuration. When supplied
(and valid), the runtime opens a STRICTLY READ-ONLY connection to the derived
corpus store so the DEF-004 knowledge-space resolution layer can authorize
space grants on the event path. Configuration sources, highest first:

  1. explicit ``configure(..., corpus_store_path=...)`` argument
  2. ``ZM_M6_CORPUS_STORE_PATH`` environment variable
  3. user-local config file (``zero_mem.userconfig.config_file_path()``)

When NOTHING is configured, ``open_corpus_conn()`` returns ``None`` and space
grants stay fail-closed (non-authorizing) — the v1.4.0 behavior is preserved.
A CONFIGURED but INVALID path fails LOUDLY at configure time.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import sqlite3


def open_readonly_store(store_path: Path):
    """Open the derived store as a TRUE READ-ONLY ReadonlyStore (mode=ro + query_only)."""
    from src.retrieval.db import open_readonly
    return open_readonly(store_path)


def open_grant_conn(store_path: Path) -> sqlite3.Connection:
    """Open a separate STRICTLY read-only connection for zm_access_grants reads."""
    uri = f"file:{store_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
    except sqlite3.OperationalError:
        pass  # query_only may be unsupported on some builds; mode=ro still blocks writes
    return conn


class CorpusStoreConfigError(RuntimeError):
    """Raised when a configured corpus store path is invalid (fail LOUD)."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


def _validate_corpus_store_path(path: Path) -> None:
    """Fail-loud validation of a corpus store path (DEF-012 method A)."""
    if not path.is_absolute():
        raise CorpusStoreConfigError(
            "relative_corpus_store_path", f"must be absolute: {path}")
    if not path.exists():
        raise CorpusStoreConfigError("missing_corpus_store", str(path))
    # Probe open read-only + confirm it looks like a corpus projection.
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('zm_corpus_units','zm_corpus_sources')"
            ).fetchall()
            names = {r[0] for r in row}
            if "zm_corpus_units" not in names:
                raise CorpusStoreConfigError(
                    "not_a_corpus_store",
                    f"{path} lacks zm_corpus_units — is it a corpus-derived.sqlite?")
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise CorpusStoreConfigError("unreadable_corpus_store", str(exc)) from None


def _resolve_corpus_store_path(explicit: Optional[Path]) -> Optional[Path]:
    """Precedence: explicit arg > env var > user config file > None."""
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get("ZM_M6_CORPUS_STORE_PATH")
    if env:
        return Path(env)
    try:
        from zero_mem.userconfig import get_corpus_store_path

        file_val = get_corpus_store_path()
        if file_val:
            return Path(file_val)
    except Exception:
        pass  # config layer unavailable => treat as unconfigured (fail-closed)
    return None


class M6Runtime:
    def __init__(self, store_path: Path,
                 corpus_store_path: Optional[Path] = None) -> None:
        self._store_path = Path(store_path)
        resolved = _resolve_corpus_store_path(corpus_store_path)
        if resolved is not None:
            # Fail LOUD on a bad configured path (DEF-012 method A).
            _validate_corpus_store_path(resolved)
        self._corpus_store_path = resolved

    @property
    def store_path(self) -> Path:
        return self._store_path

    @property
    def corpus_store_path(self) -> Optional[Path]:
        return self._corpus_store_path

    def open_store(self):
        return open_readonly_store(self._store_path)

    def open_grants(self) -> sqlite3.Connection:
        return open_grant_conn(self._store_path)

    def open_corpus_conn(self) -> Optional[sqlite3.Connection]:
        """STRICTLY read-only connection to the derived corpus store, or None
        when unconfigured (=> space grants stay fail-closed / non-authorizing)."""
        if self._corpus_store_path is None:
            return None
        uri = f"file:{self._corpus_store_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA query_only=ON")
        except sqlite3.OperationalError:
            pass
        return conn


# Module-level default runtime (configured at startup via m6.configure).
_default_runtime: Optional[M6Runtime] = None


def configure(store_path: Path,
              corpus_store_path: Optional[Path] = None) -> M6Runtime:
    global _default_runtime
    _default_runtime = M6Runtime(store_path, corpus_store_path=corpus_store_path)
    return _default_runtime


def get_runtime() -> M6Runtime:
    if _default_runtime is None:
        raise RuntimeError("M6 runtime not configured; call m6.configure(store_path)")
    return _default_runtime


def close_default() -> None:
    """Drop the module-level default runtime (test/CLI convenience)."""
    global _default_runtime
    _default_runtime = None
