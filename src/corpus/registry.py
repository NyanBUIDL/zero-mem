"""Append-first corpus source registry.

The registry is a canonical corpus artifact, separate from memory JSONL.  Its
records deliberately keep five identity axes separate: bytes-only content
identity, stable logical source identity, location provenance, explicit
authorization scope, and immutable source-version identity.  Registry reads do
not authorize access; M5 remains the sole authorization authority.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, List, Mapping, Optional

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

REGISTRY_FILENAME: Final[str] = "corpus_sources.jsonl"


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
        assert self._path is not None
        if not self._path.exists():
            self._path.touch(mode=0o600)
            if os.name != "nt":
                os.chmod(self._path, 0o600)
            return
        data = self._path.read_bytes()
        if data and not data.endswith(b"\n"):
            raise ValidationError("corpus_registry: partial_final_line")
        for line_number, line in enumerate(data.splitlines(), start=1):
            try:
                record = json.loads(line.decode("utf-8"))
                if not isinstance(record, dict):
                    raise ValueError
                rec = CorpusSourceRecord.from_dict(record)
            except Exception:
                raise ValidationError(
                    f"corpus_registry: malformed_historical_line:{line_number}"
                ) from None
            self._index_record(rec)

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
    ) -> CorpusSourceRecord:
        """Register a logical source or append its changed immutable version.

        The descriptor determines ``source_id`` and bytes determine
        ``content_hash``.  The check and append are intentionally kept under the
        instance lock; distributed/process concurrency remains R5 scope.
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
        with self._lock:
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
                blob_ref=None,
                provenance={"registered_at": _now(), "registry": "corpus_sources", **dict(provenance or {})},
                custom_meta=custom_meta or {},
                source_version_id=source_version_id,
                supersedes=supersedes,
                predecessor_content_hash=predecessor_hash,
                normalization_version="m10.3",
            )
            try:
                with self._path.open("ab") as stream:  # type: ignore[union-attr]
                    stream.write(self._serialize(record))
                    stream.flush()
                    os.fsync(stream.fileno())
            except Exception:
                raise ValidationError("corpus_registry: append_failed") from None
            self._index_record(record)
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
        record = self.register_source(
            content=content,
            external_ref=external_ref,
            kind=kind,
            profile_id=profile_id,
            project_id=project_id,
            knowledge_space_id=knowledge_space_id,
            sensitivity=sensitivity,
            lifecycle_status=lifecycle_status,
            custom_meta=custom_meta,
            provenance=provenance,
        )
        if record.blob_ref is not None:
            return record
        store = blob_store or CorpusBlobStore(root=self._root)
        if not store.available:
            return record
        digest = store.put(content=content, source_ref=record.source_id)
        updated = CorpusSourceRecord(**{**record.as_dict(), "blob_ref": digest})
        self._update_record(updated)
        return updated

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
        with self._lock:
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
            tmp = self._path.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self._path)
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
]
