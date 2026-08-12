"""M10.2 — content-addressed corpus blob store (canonical source artifact).

Source document bytes live ONLY here, never in memory JSONL (MEMORY != CORPUS).
The blob store is the authoritative copy of source bytes at ingest; structural
extraction is a derived/rebuildable representation computed from (blob + parser
config). Path safety: blobs are confined to the resolved corpus root; traversal,
symlink-escape, and out-of-root writes are rejected fail-closed.

Portability: root resolves explicit -> ZERO_MEM_CORPUS_ROOT -> config/corpus.yaml
key ``corpus_root`` -> None only when the optional config is absent. No username /
$HOME / repo path.
"""
from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from typing import Final, Optional

from .config import (
    CONFIG_FILE_CORPUS_ROOT_KEY,
    CONFIG_FILE_RELATIVE_PATH,
    CORPUS_ROOT_ENV_VAR,
    CorpusConfigError,
    resolve_root,
)


def _resolve_root(
    explicit: Optional[Path],
    env_name: str = CORPUS_ROOT_ENV_VAR,
    config_path: Optional[Path] = None,
) -> Optional[Path]:
    """Resolve the shared, dependency-free corpus-root contract."""
    return resolve_root(explicit, env_name=env_name, config_path=config_path)


class BlobStoreError(ValueError):
    """Fail-closed blob-store error (never leaks blob content)."""


class CorpusBlobStore:
    """Content-addressed store under ``<root>/blobs/<sha256[:2]>/<sha256>``."""

    def __init__(self, root: Optional[Path] = None, config_path: Optional[Path] = None) -> None:
        self._root = _resolve_root(root, config_path=config_path)
        self._lock = threading.RLock()
        if self._root is not None:
            self._blob_dir = self._root / "blobs"
            self._blob_dir.mkdir(parents=True, exist_ok=True)
            if os.name != "nt":
                os.chmod(self._root, 0o700)
                os.chmod(self._blob_dir, 0o700)
        else:
            self._blob_dir = None

    @property
    def available(self) -> bool:
        return self._blob_dir is not None

    @staticmethod
    def _sha256(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def _validate_digest(digest: str) -> str:
        """Validate the closed, lowercase SHA-256 blob-reference contract."""
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise BlobStoreError("blob_store: invalid_digest")
        return digest

    def _path_for(self, digest: str) -> Path:
        assert self._blob_dir is not None
        digest = self._validate_digest(digest)
        return self._blob_dir / digest[:2] / digest

    def put(self, *, content: bytes, source_ref: str) -> str:
        """Store ``content``, return its content-address (sha256). Idempotent."""
        if not self.available:
            raise BlobStoreError("blob_store: root_not_configured")
        digest = self._sha256(content)
        target = self._path_for(digest)
        self._assert_within_root(target)
        with self._lock:
            if target.exists() or target.is_symlink():
                if target.is_symlink() or not target.is_file():
                    raise BlobStoreError("blob_store: invalid_blob_target")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_suffix(".part")
                tmp.write_bytes(content)
                os.chmod(tmp, 0o600)
                os.replace(tmp, target)  # atomic
                if os.name != "nt":
                    os.chmod(target, 0o600)
        return digest

    def get(self, digest: str) -> bytes:
        self._validate_digest(digest)
        if not self.available:
            raise BlobStoreError("blob_store: root_not_configured")
        target = self._path_for(digest)
        self._assert_within_root(target)
        if not target.exists():
            raise BlobStoreError("blob_store: missing_blob")
        if target.is_symlink() or not target.is_file():
            raise BlobStoreError("blob_store: invalid_blob_target")
        try:
            return target.read_bytes()
        except FileNotFoundError:
            raise BlobStoreError("blob_store: missing_blob") from None
        except IsADirectoryError:
            raise BlobStoreError("blob_store: invalid_blob_target") from None
        except OSError:
            raise BlobStoreError("blob_store: read_failed") from None

    def exists(self, digest: str) -> bool:
        self._validate_digest(digest)
        if not self.available:
            return False
        target = self._path_for(digest)
        self._assert_within_root(target)
        return target.exists() and not target.is_symlink() and target.is_file()

    def _assert_within_root(self, path: Path) -> None:
        assert self._blob_dir is not None
        resolved = path.resolve()
        root_resolved = self._blob_dir.resolve()
        try:
            resolved.relative_to(root_resolved)
        except ValueError:
            raise BlobStoreError("blob_store: path_escape_attempt")


__all__ = [
    "CorpusBlobStore",
    "BlobStoreError",
    "CorpusConfigError",
    "CORPUS_ROOT_ENV_VAR",
    "CONFIG_FILE_RELATIVE_PATH",
    "CONFIG_FILE_CORPUS_ROOT_KEY",
]
