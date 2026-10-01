"""Append-first corpus source registry.

The registry is a canonical corpus artifact, separate from memory JSONL.  Its
records deliberately keep five identity axes separate: bytes-only content
identity, stable logical source identity, location provenance, explicit
authorization scope, and immutable source-version identity.  Registry reads do
not authorize access; M5 remains the sole authorization authority.
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Iterator, List, Mapping, Optional

from .blob_store import (
    CONFIG_FILE_CORPUS_ROOT_KEY,
    CONFIG_FILE_RELATIVE_PATH,
    CORPUS_ROOT_ENV_VAR,
    CorpusBlobStore,
    _resolve_root,
)
from .config import CorpusConfigError
from .contracts import CorpusSourceRecord, SourceSensitivity, ValidationError
from .identity import (
    SourceLifecycle,
    compute_content_identity,
    derive_source_id,
    source_descriptor,
)
from src.storage.coordination import locked
from src.storage.platform import PlatformErrorCode, PlatformStorageError

REGISTRY_FILENAME: Final[str] = "corpus_sources.jsonl"

#: Cross-process advisory lock guarding every canonical registry mutation (DEF-053).
WRITE_LOCK_FILENAME: Final[str] = ".write.lock"

#: Seconds a writer waits for the cross-process lock before failing closed.
WRITE_LOCK_TIMEOUT: Final[float] = 30.0

#: Per-thread record of the corpus write locks already held (re-entrancy), so a
#: caller can wrap "register + project" in one critical section.
_HELD = threading.local()


def _lock_path(root: Path) -> Path:
    return Path(root).resolve() / WRITE_LOCK_FILENAME


@contextlib.contextmanager
def _held_lock(root: Path, mode: str) -> Iterator[None]:
    key = str(_lock_path(root))
    held = getattr(_HELD, "depth", None)
    if held is None:
        held = _HELD.depth = {}
    if held.get(key, 0) > 0:
        # This thread already holds the (exclusive) lock; flock on a second
        # descriptor in the same process would otherwise self-deadlock.
        held[key] += 1
        try:
            yield
        finally:
            held[key] -= 1
        return
    with locked(Path(key), mode=mode, timeout=WRITE_LOCK_TIMEOUT):  # type: ignore[arg-type]
        if mode == "exclusive":
            held[key] = 1
        try:
            yield
        finally:
            if mode == "exclusive":
                held.pop(key, None)


def corpus_write_lock(root: Path):
    """Exclusive, cross-process, thread-reentrant lock for a corpus root.

    Wrap ``register_*`` + projection in this when they must be one critical
    section. ``CorpusSourceRegistry.register_*`` takes the same lock itself.
    Do not wrap them in a raw ``src.storage.coordination.locked`` on the same
    file: that lock is not re-entrant and would block the registry's own
    acquisition until it times out.
    """
    return _held_lock(Path(root), "exclusive")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CorpusSourceRegistry:
    """Append-first, deterministic registry of logical source versions."""

    def __init__(self, root: Optional[Path] = None, config_path: Optional[Path] = None) -> None:
        self._root = _resolve_root(root, config_path=config_path)
        self._path: Optional[Path] = None
        self._lock = threading.RLock()
        self._by_id: dict[str, CorpusSourceRecord] = {}
        self._by_hash: dict[str, list[CorpusSourceRecord]] = {}
        self._records: list[CorpusSourceRecord] = []
        # What has been read from the canonical JSONL so far (DEF-053): the
        # file identity, the byte offset already indexed and the line count, so
        # a writer can pick up other processes' appends incrementally.
        self._file_id: Optional[tuple[int, int]] = None
        self._loaded_size = 0
        self._loaded_lines = 0
        if self._root is not None:
            self._root.mkdir(parents=True, exist_ok=True)
            if os.name != "nt":
                os.chmod(self._root, 0o700)
            self._path = self._root / REGISTRY_FILENAME
            self._load()

    @property
    def available(self) -> bool:
        return self._path is not None

    @property
    def path(self) -> Optional[Path]:
        return self._path

    def _load(self) -> None:
        assert self._path is not None and self._root is not None
        if not self._path.exists():
            self._path.touch(mode=0o600)
            if os.name != "nt":
                os.chmod(self._path, 0o600)
        self.refresh()

    def refresh(self) -> None:
        """Re-read the canonical JSONL so this instance sees other writers.

        Takes a shared lock (a writer mid-append is never observed) unless this
        thread already holds the write lock. When the lock file cannot be
        created (e.g. read-only media) the read proceeds unlocked, as it always
        did.
        """
        assert self._root is not None
        with self._lock:
            try:
                with _held_lock(self._root, "shared"):
                    self._refresh_from_disk()
            except PlatformStorageError as exc:
                if exc.code is PlatformErrorCode.LOCK_TIMEOUT:
                    raise ValidationError("corpus_registry: read_lock_timeout") from None
                self._refresh_from_disk()

    def _reset_index(self) -> None:
        self._records = []
        self._by_id = {}
        self._by_hash = {}
        self._file_id = None
        self._loaded_size = 0
        self._loaded_lines = 0

    def _refresh_from_disk(self) -> None:
        """Index every JSONL line not yet seen. Caller holds a registry lock."""
        assert self._path is not None
        try:
            info = os.stat(self._path)
        except FileNotFoundError:
            self._reset_index()
            self._path.touch(mode=0o600)
            info = os.stat(self._path)
        identity = (info.st_dev, info.st_ino)
        if identity != self._file_id or info.st_size < self._loaded_size:
            # First read, or the file was replaced/truncated: start over.
            self._reset_index()
        if info.st_size == self._loaded_size and self._file_id == identity:
            return
        with open(self._path, "rb") as stream:
            stream.seek(self._loaded_size)
            data = stream.read()
            file_identity = os.fstat(stream.fileno())
        if data and not data.endswith(b"\n"):
            raise ValidationError("corpus_registry: partial_final_line")
        line_number = self._loaded_lines
        for line in data.splitlines():
            line_number += 1
            try:
                record = json.loads(line.decode("utf-8"))
                if not isinstance(record, dict):
                    raise ValueError
                rec = CorpusSourceRecord.from_dict(record)
            except Exception:
                self._reset_index()  # never keep a half-indexed view
                raise ValidationError(
                    f"corpus_registry: malformed_historical_line:{line_number}"
                ) from None
            self._index_record(rec)
        self._loaded_lines = line_number
        self._loaded_size += len(data)
        self._file_id = (file_identity.st_dev, file_identity.st_ino)

    @contextlib.contextmanager
    def _exclusive(self) -> Iterator[None]:
        """Cross-process write lock + fresh view of the canonical JSONL."""
        assert self._root is not None
        with contextlib.ExitStack() as stack:
            try:
                stack.enter_context(corpus_write_lock(self._root))
            except PlatformStorageError as exc:
                reason = "timeout" if exc.code is PlatformErrorCode.LOCK_TIMEOUT else "unavailable"
                raise ValidationError(f"corpus_registry: write_lock_{reason}") from None
            self._refresh_from_disk()
            yield

    def _index_record(self, record: CorpusSourceRecord) -> None:
        self._records.append(record)
        self._by_id[record.source_id] = record
        self._by_hash.setdefault(record.content_hash, []).append(record)

    @staticmethod
    def _serialize(record: CorpusSourceRecord) -> bytes:
        return (
            json.dumps(record.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")

    def _next_version_fields(
        self,
        *,
        source_id: str,
        content_hash_value: str,
        profile_id: Optional[str],
        project_id: Optional[str],
        knowledge_space_id: Optional[str],
    ) -> tuple[str, Optional[str], Optional[str]]:
        from .normalize import NORMALIZATION_VERSION
        from .versioning import ScopeKey, compute_source_version_id

        scope = ScopeKey(profile_id, project_id, knowledge_space_id)
        version_id = compute_source_version_id(
            source_id=source_id,
            content_hash_value=content_hash_value,
            scope=scope,
            normalization_version=NORMALIZATION_VERSION,
        )
        latest = self._by_id.get(source_id)
        if latest is None:
            return version_id, None, None
        predecessor_id = latest.source_version_id or compute_source_version_id(
            source_id=latest.source_id,
            content_hash_value=latest.content_hash,
            scope=ScopeKey(latest.profile_id, latest.project_id, latest.knowledge_space_id),
            normalization_version=latest.normalization_version or NORMALIZATION_VERSION,
        )
        return version_id, predecessor_id, latest.content_hash

    def register_source(
        self,
        *,
        content: bytes,
        external_ref: str,
        kind: str,
        profile_id: Optional[str] = None,
        project_id: Optional[str] = None,
        knowledge_space_id: Optional[str] = None,
        sensitivity: str = SourceSensitivity.INTERNAL.value,
        lifecycle_status: str = SourceLifecycle.OBSERVED.value,
        custom_meta: Optional[Mapping[str, Any]] = None,
        provenance: Optional[Mapping[str, Any]] = None,
        _blob_ref: Optional[str] = None,
    ) -> CorpusSourceRecord:
        """Register a logical source or append its changed immutable version.

        The descriptor determines ``source_id`` and bytes determine
        ``content_hash``.  The dedup check and the append run under the
        in-process lock AND the cross-process ``<root>/.write.lock`` (DEF-053),
        after re-reading the JSONL inside the lock, so concurrent writers --
        threads or processes -- register one logical source version exactly once.
        """
        if not self.available:
            raise ValidationError("corpus_registry: root_not_configured")
        descriptor = source_descriptor(
            external_ref=external_ref,
            kind=kind,
            profile_id=profile_id,
            project_id=project_id,
            knowledge_space_id=knowledge_space_id,
            custom_meta=custom_meta,
        )
        content_hash_value = compute_content_identity(content)
        source_id = derive_source_id(content_hash_value, descriptor)
        with self._lock, self._exclusive():
            existing = self._by_id.get(source_id)
            if existing is not None and existing.content_hash == content_hash_value:
                return existing
            source_version_id, supersedes, predecessor_hash = self._next_version_fields(
                source_id=source_id,
                content_hash_value=content_hash_value,
                profile_id=profile_id,
                project_id=project_id,
                knowledge_space_id=knowledge_space_id,
            )
            record = CorpusSourceRecord(
                source_id=source_id,
                content_hash=content_hash_value,
                external_ref=external_ref,
                kind=kind,
                created_at=_now(),
                profile_id=profile_id,
                project_id=project_id,
                knowledge_space_id=knowledge_space_id,
                sensitivity=sensitivity,
                lifecycle_status=lifecycle_status,
                blob_ref=_blob_ref,
                provenance={"registered_at": _now(), "registry": "corpus_sources", **dict(provenance or {})},
                custom_meta=custom_meta or {},
                source_version_id=source_version_id,
                supersedes=supersedes,
                predecessor_content_hash=predecessor_hash,
                normalization_version="m10.3",
            )
            line = self._serialize(record)
            try:
                with self._path.open("ab") as stream:  # type: ignore[union-attr]
                    stream.write(line)
                    stream.flush()
                    os.fsync(stream.fileno())
            except Exception:
                raise ValidationError("corpus_registry: append_failed") from None
            self._index_record(record)
            self._loaded_size += len(line)
            self._loaded_lines += 1
            return record

    def register_source_with_blob(
        self,
        *,
        content: bytes,
        external_ref: str,
        kind: str,
        profile_id: Optional[str] = None,
        project_id: Optional[str] = None,
        knowledge_space_id: Optional[str] = None,
        sensitivity: str = SourceSensitivity.INTERNAL.value,
        lifecycle_status: str = SourceLifecycle.OBSERVED.value,
        custom_meta: Optional[Mapping[str, Any]] = None,
        provenance: Optional[Mapping[str, Any]] = None,
        blob_store: Optional[CorpusBlobStore] = None,
    ) -> CorpusSourceRecord:
        store = blob_store or CorpusBlobStore(root=self._root)
        if not store.available:
            return self.register_source(
                content=content, external_ref=external_ref, kind=kind,
                profile_id=profile_id, project_id=project_id,
                knowledge_space_id=knowledge_space_id, sensitivity=sensitivity,
                lifecycle_status=lifecycle_status, custom_meta=custom_meta,
                provenance=provenance)
        descriptor = source_descriptor(
            external_ref=external_ref, kind=kind, profile_id=profile_id,
            project_id=project_id, knowledge_space_id=knowledge_space_id,
            custom_meta=custom_meta)
        source_id = derive_source_id(compute_content_identity(content), descriptor)
        # Blob-first permits only an unreachable content-addressed orphan if the
        # registry append fails; it can never create a dangling blob reference.
        digest = store.put(content=content, source_ref=source_id)
        return self.register_source(
            content=content, external_ref=external_ref, kind=kind,
            profile_id=profile_id, project_id=project_id,
            knowledge_space_id=knowledge_space_id, sensitivity=sensitivity,
            lifecycle_status=lifecycle_status, custom_meta=custom_meta,
            provenance=provenance, _blob_ref=digest)

    def _update_record(self, record: CorpusSourceRecord) -> None:
        """Rebind one version without overwriting prior source history.

        V150-WP1 (DEF-009a): the rewritten file content is derived from the
        in-memory index (``self._records``) instead of re-reading and re-parsing
        the whole JSONL on every update — O(n) read + O(n) parse per update
        becomes a single streaming rewrite over already-parsed records.
        Behavioral contract is unchanged: same-source/same-version line replaced
        exactly once, legacy single-version lines matched, unrelated lines
        preserved byte-for-byte, append when no matching line exists.
        """
        if not self.available or self._path is None:
            return
        with self._lock, self._exclusive():
            new_lines: list[bytes] = []
            replaced = False
            for r in self._records:
                same_source = r.source_id == record.source_id
                same_version = r.source_version_id == record.source_version_id
                # Legacy single-version rows carry no source_version_id; the
                # in-memory records normalize them to None, so match that too.
                if same_source and same_version and not replaced:
                    new_lines.append(self._serialize(record))
                    replaced = True
                else:
                    new_lines.append(self._serialize(r))
            if not replaced:
                new_lines.append(self._serialize(record))
            data = b"".join(line.rstrip(b"\n") + b"\n" for line in new_lines)
            fd, tmp_name = tempfile.mkstemp(
                dir=str(self._path.parent), prefix=".corpus_sources.", suffix=".tmp")
            tmp = Path(tmp_name)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(tmp, 0o600)
                os.replace(tmp, self._path)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
            replaced_info = os.stat(self._path)
            self._file_id = (replaced_info.st_dev, replaced_info.st_ino)
            self._loaded_size = len(data)
            self._loaded_lines = len(new_lines)
            self._records = [
                record if r.source_id == record.source_id and r.source_version_id == record.source_version_id else r
                for r in self._records
            ]
            self._by_id[record.source_id] = record
            matches = self._by_hash.setdefault(record.content_hash, [])
            for index, existing in enumerate(matches):
                if existing.source_id == record.source_id and existing.source_version_id == record.source_version_id:
                    matches[index] = record
                    break
            else:
                matches.append(record)

    def get_by_source_id(self, source_id: str) -> Optional[CorpusSourceRecord]:
        return self._by_id.get(source_id)

    def get_by_content_hash(self, content_hash: str) -> Optional[CorpusSourceRecord]:
        matches = self._by_hash.get(content_hash, [])
        return matches[-1] if matches else None

    def get_all_by_content_hash(self, content_hash: str) -> List[CorpusSourceRecord]:
        return list(self._by_hash.get(content_hash, []))

    def get_by_external_ref(self, external_ref: str) -> List[CorpusSourceRecord]:
        return [r for r in self._records if r.external_ref == external_ref]

    def get_by_external_ref_first(self, external_ref: str) -> Optional[CorpusSourceRecord]:
        matches = self.get_by_external_ref(external_ref)
        return matches[0] if matches else None

    def all_records(self) -> List[CorpusSourceRecord]:
        return list(self._records)


__all__ = [
    "CorpusSourceRegistry",
    "CorpusConfigError",
    "CORPUS_ROOT_ENV_VAR",
    "CONFIG_FILE_RELATIVE_PATH",
    "CONFIG_FILE_CORPUS_ROOT_KEY",
    "REGISTRY_FILENAME",
    "WRITE_LOCK_FILENAME",
    "corpus_write_lock",
]
