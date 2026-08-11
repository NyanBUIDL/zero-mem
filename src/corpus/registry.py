"""M10.1 — append-first corpus source registry store.

The corpus source registry is its own append-only JSONL store
(``corpus_sources.jsonl``). It is a canonical corpus artifact, NOT memory
JSONL: corpus source records never enter the M1 event stream (MEMORY != CORPUS).

Discipline mirrors ``src/storage/jsonl_capture.py``:
- 0o700 parent, 0o600 file;
- fsync on append;
- duplicate-by-source_id and duplicate-by-content_hash are idempotent (return
  the existing record, never a second append);
- malformed historical lines reject closed (fail closed).

No document bytes are written here (blob store is M10.2/M10.4); ``blob_ref``
stays None in M10.1.

Portability: the registry root resolves as explicit arg -> environment variable
``ZERO_MEM_CORPUS_ROOT`` -> project-local ``config/corpus.yaml`` key
``corpus_root`` -> None (unavailable = safe, silent). No username, no
``$HOME`` guess, no repository-relative default.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, List, Mapping, Optional

from .contracts import (
    CorpusSourceRecord,
    SourceSensitivity,
    ValidationError,
)
from .identity import (
    SourceLifecycle,
    compute_source_hash,
    derive_source_id,
    source_descriptor,
)
from .blob_store import (
    CORPUS_ROOT_ENV_VAR,
    CONFIG_FILE_CORPUS_ROOT_KEY,
    CONFIG_FILE_RELATIVE_PATH,
    CorpusBlobStore,
    _resolve_root,
)

#: Default registry filename beneath the resolved corpus root.
REGISTRY_FILENAME: Final[str] = "corpus_sources.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_root(
    explicit: Optional[Path],
    env_name: str = CORPUS_ROOT_ENV_VAR,
    config_path: Optional[Path] = None,
) -> Optional[Path]:
    """Deterministic, explicit-only root resolution (mirrors projection/config).

    Order: explicit argument -> env var (absolute path) -> project-local config
    file key -> None. Never derives the root from cwd, ``$HOME``, the repository
    name, or any memory content.
    """
    if explicit is not None:
        value = str(explicit).strip()
        if value:
            return Path(value).expanduser().resolve()
    env_value = os.environ.get(env_name)
    if env_value:
        env_value = env_value.strip()
        if env_value:
            return Path(env_value).expanduser().resolve()
    if config_path is not None and config_path.exists():
        try:
            import yaml  # local import; config is optional

            data = yaml.safe_load(config_path.read_text()) or {}
            file_value = data.get(CONFIG_FILE_CORPUS_ROOT_KEY)
            if isinstance(file_value, str) and file_value.strip():
                return Path(file_value.strip()).expanduser().resolve()
        except Exception:
            # Any config failure => treat as unconfigured (fail safe, silent).
            return None
    return None


class CorpusSourceRegistry:
    """Append-first, deterministic corpus source registry."""

    def __init__(
        self,
        root: Optional[Path] = None,
        config_path: Optional[Path] = None,
    ) -> None:
        self._root = _resolve_root(root, config_path=config_path)
        self._path: Optional[Path] = None
        self._lock = threading.RLock()
        self._by_id: dict[str, CorpusSourceRecord] = {}
        self._by_hash: dict[str, CorpusSourceRecord] = {}
        if self._root is not None:
            self._root.mkdir(parents=True, exist_ok=True)
            if os.name != "nt":
                os.chmod(self._root, 0o700)
            self._path = self._root / REGISTRY_FILENAME
            self._load()

    # -- availability -------------------------------------------------------
    @property
    def available(self) -> bool:
        """Unconfigured corpus root is a NORMAL, SAFE state (silent)."""
        return self._path is not None

    @property
    def path(self) -> Optional[Path]:
        return self._path

    # -- load ---------------------------------------------------------------
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
            except Exception as exc:
                raise ValidationError(
                    f"corpus_registry: malformed_historical_line:{line_number}"
                ) from None
            self._by_id[rec.source_id] = rec
            self._by_hash[rec.content_hash] = rec

    # -- serialize ----------------------------------------------------------
    @staticmethod
    def _serialize(record: CorpusSourceRecord) -> bytes:
        return (
            json.dumps(record.as_dict(), ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n"
        ).encode("utf-8")

    # -- register -----------------------------------------------------------
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
    ) -> CorpusSourceRecord:
        """Register (or idempotently return) one corpus source version.

        Deterministic: identical (content, scope) => identical source_id and
        content_hash; re-registration returns the existing record without a
        second append. No document bytes are stored (blob_ref stays None).
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
        content_hash_value = compute_source_hash(content, descriptor)
        if content_hash_value in self._by_hash:
            return self._by_hash[content_hash_value]
        source_id = derive_source_id(content_hash_value, descriptor)
        if source_id in self._by_id:
            return self._by_id[source_id]
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
            provenance={"registered_at": _now(), "registry": "corpus_sources"},
            custom_meta=custom_meta or {},
        )
        with self._lock:
            blob = self._serialize(record)
            try:
                with self._path.open("ab") as stream:  # type: ignore[union-attr]
                    stream.write(blob)
                    stream.flush()
                    os.fsync(stream.fileno())
            except Exception as exc:
                raise ValidationError("corpus_registry: append_failed") from None
            self._by_id[record.source_id] = record
            self._by_hash[record.content_hash] = record
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
        blob_store: Optional[CorpusBlobStore] = None,
    ) -> CorpusSourceRecord:
        """Register a source AND persist its bytes in the blob store (M10.2).

        The source bytes live ONLY in the blob store (never in memory JSONL);
        the returned record carries ``blob_ref`` = the content-address so the
        canonical source artifact is recoverable and extraction is rebuildable.
        """
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
        )
        if record.blob_ref is not None:
            return record
        store = blob_store or CorpusBlobStore(root=self._root)
        if not store.available:
            # Blob store unavailable => keep registry entry but no blob bound.
            # Source bytes are NOT stored anywhere; M10.4 may add derived store.
            return record
        digest = store.put(content=content, source_ref=record.source_id)
        # Update the persisted record's blob_ref in place (append-first replay).
        updated = CorpusSourceRecord(
            **{**record.as_dict(), "blob_ref": digest}
        )
        self._update_record(updated)
        return updated

    def _update_record(self, record: CorpusSourceRecord) -> None:
        """Rewrite the single line for ``record.source_id`` (idempotent identity)."""
        if not self.available or self._path is None:
            return
        with self._lock:
            lines = self._path.read_bytes().splitlines()
            new_lines: list[bytes] = []
            replaced = False
            for line in lines:
                try:
                    rec = json.loads(line.decode("utf-8"))
                except Exception:
                    new_lines.append(line)
                    continue
                if rec.get("source_id") == record.source_id:
                    new_lines.append(self._serialize(record))
                    replaced = True
                else:
                    new_lines.append(line)
            if not replaced:
                new_lines.append(self._serialize(record))
            data = b"\n".join(new_lines) + b"\n"
            tmp = self._path.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self._path)
            self._by_id[record.source_id] = record
            self._by_hash[record.content_hash] = record

    # -- read (deterministic, authorization is the caller's responsibility) --
    def get_by_source_id(self, source_id: str) -> Optional[CorpusSourceRecord]:
        return self._by_id.get(source_id)

    def get_by_content_hash(self, content_hash: str) -> Optional[CorpusSourceRecord]:
        return self._by_hash.get(content_hash)

    def get_by_external_ref(self, external_ref: str) -> List[CorpusSourceRecord]:
        return [r for r in self._by_id.values() if r.external_ref == external_ref]

    def get_by_external_ref_first(self, external_ref: str) -> Optional[CorpusSourceRecord]:
        matches = self.get_by_external_ref(external_ref)
        return matches[0] if matches else None

    def all_records(self) -> List[CorpusSourceRecord]:
        return list(self._by_id.values())


__all__ = [
    "CorpusSourceRegistry",
    "CORPUS_ROOT_ENV_VAR",
    "CONFIG_FILE_RELATIVE_PATH",
    "CONFIG_FILE_CORPUS_ROOT_KEY",
    "REGISTRY_FILENAME",
]
