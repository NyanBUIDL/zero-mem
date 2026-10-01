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
import tempfile
import threading
from pathlib import Path
from typing import Final, Optional

from . import _fsretry
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
                try:
                    if self._sha256(self._read(target)) != digest:
                        raise BlobStoreError("blob_store: content_hash_mismatch")
                except BlobStoreError:
                    raise
                except OSError:
                    raise BlobStoreError("blob_store: read_failed") from None
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                self._write_atomic(target, content, digest)
        return digest

    def _write_atomic(self, target: Path, content: bytes, digest: str) -> None:
        """Write ``content`` to ``target`` via a per-writer unique temp file.

        DEF-053: the temp file is created with ``mkstemp`` in the target's own
        directory (same filesystem => atomic ``os.replace``), so concurrent
        writers of identical bytes -- threads or processes -- never share a
        temp path. Identical content makes the last replace a harmless no-op.
        """
        fd, tmp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=f".{digest[:16]}.", suffix=".part")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
            if os.name != "nt":
                os.chmod(tmp, 0o600)
            def replace() -> None:
                try:
                    os.replace(tmp, target)  # atomic
                except OSError as exc:
                    # Windows can refuse to replace a file another process has
                    # open; identical content-addressed bytes already in place
                    # are success (DEF-090).
                    if _fsretry.is_transient(exc) and self._target_matches(target, digest):
                        return
                    raise

            try:
                _fsretry.retry_transient(replace)
            except OSError as exc:
                if _fsretry.is_transient(exc):
                    raise BlobStoreError("blob_store: replace_failed") from None
                raise
            tmp.unlink(missing_ok=True)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        if os.name != "nt":
            os.chmod(target, 0o600)

    @staticmethod
    def _read(target: Path) -> bytes:
        """Read a blob, retrying transient Windows sharing violations."""
        return _fsretry.retry_transient(target.read_bytes)

    def _target_matches(self, target: Path, digest: str) -> bool:
        try:
            return (
                target.is_file()
                and not target.is_symlink()
                and self._sha256(self._read(target)) == digest
            )
        except OSError:
            return False

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
            content = self._read(target)
        except FileNotFoundError:
            raise BlobStoreError("blob_store: missing_blob") from None
        except IsADirectoryError:
            raise BlobStoreError("blob_store: invalid_blob_target") from None
        except OSError:
            raise BlobStoreError("blob_store: read_failed") from None
        if self._sha256(content) != digest:
            raise BlobStoreError("blob_store: content_hash_mismatch")
        return content

    def exists(self, digest: str) -> bool:
        self._validate_digest(digest)
        if not self.available:
            return False
        target = self._path_for(digest)
        self._assert_within_root(target)
        if not target.exists() or target.is_symlink() or not target.is_file():
            return False
        try:
            return self._sha256(self._read(target)) == digest
        except OSError:
            return False

    def _assert_within_root(self, path: Path) -> None:
        """Containment check on the PARENT directory plus a hex-digest filename.

        DEF-090: the file itself is never resolved -- on Windows another process
        replacing it makes ``resolve()`` of the file transiently unreliable. The
        parent directory is stable; resolving it still rejects ``..`` traversal
        and symlinked parents. The filename must be a valid digest.
        """
        assert self._blob_dir is not None
        try:
            self._validate_digest(path.name)
            parent = path.parent.resolve()
            parent.relative_to(self._blob_dir.resolve())
        except (ValueError, BlobStoreError):
            raise BlobStoreError("blob_store: path_escape_attempt") from None
        except OSError:
            raise BlobStoreError("blob_store: path_escape_attempt") from None
        if parent.name != path.name[:2] or parent.parent != self._blob_dir.resolve():
            raise BlobStoreError("blob_store: path_escape_attempt")


__all__ = [
    "CorpusBlobStore",
    "BlobStoreError",
    "CorpusConfigError",
    "CORPUS_ROOT_ENV_VAR",
    "CONFIG_FILE_RELATIVE_PATH",
    "CONFIG_FILE_CORPUS_ROOT_KEY",
]
