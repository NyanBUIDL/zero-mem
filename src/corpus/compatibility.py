"""Explicit, isolated compatibility conversion for legacy corpus registries.

This module is deliberately not part of normal registry startup or reads.  It
converts a legacy canonical registry copy into a new, append-first registry
under an explicitly supplied output root.  It never mutates the input root,
consults environment variables, or guesses a corpus location.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .blob_store import CorpusBlobStore
from .contracts import CorpusSourceRecord
from .identity import compute_content_identity, source_descriptor, compute_logical_source_id
from .normalize import NORMALIZATION_VERSION
from .registry import CorpusSourceRegistry, REGISTRY_FILENAME
from .versioning import ScopeKey, compute_source_version_id


class CompatibilityError(ValueError):
    """Fail-closed compatibility input/output error."""


@dataclass(frozen=True)
class CompatibilityReport:
    input_records: int
    output_records: int
    corrected_source_ids: tuple[str, ...]
    legacy_source_ids: tuple[str, ...]
    content_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_records": self.input_records,
            "output_records": self.output_records,
            "corrected_source_ids": list(self.corrected_source_ids),
            "legacy_source_ids": list(self.legacy_source_ids),
            "content_ids": list(self.content_ids),
        }


def convert_legacy_registry(*, input_root: Path, output_root: Path) -> CompatibilityReport:
    """Convert one legacy registry/blob fixture into a new isolated root.

    Both roots are mandatory.  The output registry must not already exist, and
    the resolved roots must differ.  Legacy IDs/hashes and the original record
    are retained in each corrected record's provenance.  The input registry and
    blobs are read only; no normal application path calls this function.
    """
    if input_root is None or output_root is None:
        raise CompatibilityError("corpus_compatibility: explicit_roots_required")
    source_root = Path(input_root).expanduser().resolve()
    target_root = Path(output_root).expanduser().resolve()
    if source_root == target_root:
        raise CompatibilityError("corpus_compatibility: input_output_roots_must_differ")
    source_path = source_root / REGISTRY_FILENAME
    target_path = target_root / REGISTRY_FILENAME
    if not source_path.is_file():
        raise CompatibilityError("corpus_compatibility: input_registry_missing")
    if target_path.exists():
        raise CompatibilityError("corpus_compatibility: output_registry_exists")

    legacy_records: list[CorpusSourceRecord] = []
    for line_number, line in enumerate(source_path.read_bytes().splitlines(), start=1):
        try:
            raw = json.loads(line.decode("utf-8"))
            if not isinstance(raw, dict):
                raise ValueError
            legacy_records.append(CorpusSourceRecord.from_dict(raw))
        except Exception:
            raise CompatibilityError(
                f"corpus_compatibility: malformed_input_line:{line_number}"
            ) from None

    input_blobs = CorpusBlobStore(root=source_root)
    output_blobs = CorpusBlobStore(root=target_root)
    target_root.mkdir(parents=True, exist_ok=True)
    target_registry = CorpusSourceRegistry(root=target_root)
    previous_by_source: dict[str, CorpusSourceRecord] = {}
    corrected: list[CorpusSourceRecord] = []

    for legacy in legacy_records:
        if not legacy.blob_ref:
            raise CompatibilityError("corpus_compatibility: legacy_blob_ref_required")
        try:
            content = input_blobs.get(legacy.blob_ref)
        except Exception:
            raise CompatibilityError("corpus_compatibility: legacy_blob_unreadable") from None
        content_id = compute_content_identity(content)
        descriptor = source_descriptor(
            external_ref=legacy.external_ref,
            kind=legacy.kind,
            profile_id=legacy.profile_id,
            project_id=legacy.project_id,
            knowledge_space_id=legacy.knowledge_space_id,
            custom_meta=legacy.custom_meta,
        )
        source_id = compute_logical_source_id(descriptor)
        scope = ScopeKey(legacy.profile_id, legacy.project_id, legacy.knowledge_space_id)
        version_id = compute_source_version_id(
            source_id=source_id,
            content_hash_value=content_id,
            scope=scope,
            normalization_version=NORMALIZATION_VERSION,
        )
        predecessor = previous_by_source.get(source_id)
        blob_ref = output_blobs.put(content=content, source_ref=source_id)
        record = CorpusSourceRecord(
            source_id=source_id,
            source_version_id=version_id,
            content_hash=content_id,
            external_ref=legacy.external_ref,
            kind=legacy.kind,
            created_at=legacy.created_at,
            profile_id=legacy.profile_id,
            project_id=legacy.project_id,
            knowledge_space_id=legacy.knowledge_space_id,
            sensitivity=legacy.sensitivity,
            lifecycle_status=legacy.lifecycle_status,
            blob_ref=blob_ref,
            provenance={
                **dict(legacy.provenance),
                "compatibility": "r3_legacy_conversion",
                "legacy_source_id": legacy.source_id,
                "legacy_content_hash": legacy.content_hash,
                "legacy_external_ref": legacy.external_ref,
                "legacy_scope": {
                    "profile_id": legacy.profile_id,
                    "project_id": legacy.project_id,
                    "knowledge_space_id": legacy.knowledge_space_id,
                },
                "legacy_record": legacy.as_dict(),
            },
            custom_meta=legacy.custom_meta,
            supersedes=predecessor.source_version_id if predecessor else None,
            predecessor_content_hash=predecessor.content_hash if predecessor else None,
            normalization_version=NORMALIZATION_VERSION,
        )
        with target_path.open("ab") as stream:
            stream.write(target_registry._serialize(record))
            stream.flush()
        previous_by_source[source_id] = record
        corrected.append(record)

    # Re-open the output through the real registry reader.  This is part of the
    # conversion contract and catches malformed output before reporting success.
    reopened = CorpusSourceRegistry(root=target_root)
    if len(reopened.all_records()) != len(corrected):
        raise CompatibilityError("corpus_compatibility: output_reopen_count_mismatch")
    return CompatibilityReport(
        input_records=len(legacy_records),
        output_records=len(corrected),
        corrected_source_ids=tuple(r.source_id for r in corrected),
        legacy_source_ids=tuple(r.source_id for r in legacy_records),
        content_ids=tuple(r.content_hash for r in corrected),
    )


__all__ = ["CompatibilityError", "CompatibilityReport", "convert_legacy_registry"]
