"""M10.3 — deterministic source versioning + supersession.

Builds a deterministic version chain over corpus sources WITHOUT mutating
historical provenance. A changed source produces:

    source_id
        -> version N  (content_hash_1, supersedes=None)
        -> version N+1 (content_hash_2, supersedes=version N)

The version chain is DERIVED and rebuildable from the source registry (canonical)
plus extraction/normalization. It is NOT a corpus system of record and introduces
no SQLite schema change; the current derived store remains schema v10.

Identity rules (mirror M10.1/M8 determinism discipline):
- ``source_id``      : stable logical-source identity from the descriptor
  (external reference, kind, stable metadata, and explicit scope); it is not a
  content hash and remains stable across source-byte changes.
- ``source_version_id`` : hash over (source_id, content_hash, scope,
  normalization_version). Identical content re-ingested => identical version id
  => NO new version (idempotent re-ingest). A changed source => new version id.
- ``supersedes``     : the immediately preceding version id for the same
  source_id (predecessor), when the new version's content differs. Provenance of
  the old version is preserved verbatim; nothing is overwritten in place.
- scope (profile/project/knowledge_space) participates in the version id so a
  source re-ingested under a different authorization scope is a DISTINCT version
  (no cross-scope authorization collapse). Scope is taken from the source record,
  never inferred from path/content.

Lifecycle handling (deleted/archived): a pure lifecycle-only change (same content
hash, same scope) is idempotent at the version level — it does NOT create a new
content version, because the content did not change. Lifecycle state of a source
is the registry's concern (M10.1/M10.4); the version chain records the
content-version history and carries the supplied lifecycle_status for traceability.

No LLM, no network, no fuzzy/semantic comparison.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Iterable, Mapping, Optional

from src.m8.identity import content_hash

from .contracts import CorpusSourceRecord
from .normalize import NORMALIZATION_VERSION

#: Domain separators.
_DOMAIN_SOURCE_VERSION = "zm10.source_version"
_ID_DIGEST_CHARS = 32


@dataclass(frozen=True)
class ScopeKey:
    """Authorization scope of a source/version. Explicit NULLs are distinct.

    Two otherwise-identical sources under different scopes are DIFFERENT
    logical versions (no grant bleed). This preserves M5/M6.6 isolation.
    """

    profile_id: Optional[str] = None
    project_id: Optional[str] = None
    knowledge_space_id: Optional[str] = None

    def as_tuple(self) -> tuple:
        return (self.profile_id, self.project_id, self.knowledge_space_id)


def scope_from_record(record: CorpusSourceRecord) -> ScopeKey:
    return ScopeKey(
        profile_id=record.profile_id,
        project_id=record.project_id,
        knowledge_space_id=record.knowledge_space_id,
    )


def compute_source_version_id(
    *,
    source_id: str,
    content_hash_value: str,
    scope: ScopeKey,
    normalization_version: str = NORMALIZATION_VERSION,
) -> str:
    """Deterministic source version identity.

    Version id depends on (source_id, content_hash, scope, normalization_version).
    Re-ingesting unchanged content => same version id => no new version. Changing
    content/scope/normalization logic => a new version id.
    """
    payload = {
        "source_id": source_id,
        "content_hash": content_hash_value,
        "scope": list(scope.as_tuple()),
        "normalization_version": normalization_version,
    }
    return "sv_" + content_hash(payload)[:_ID_DIGEST_CHARS]


@dataclass(frozen=True)
class CorpusSourceVersion:
    """One deterministic version of a corpus source."""

    source_id: str
    source_version_id: str
    content_hash: str
    scope: ScopeKey
    lifecycle_status: str
    supersedes: Optional[str] = None
    predecessor_content_hash: Optional[str] = None
    normalization_version: str = NORMALIZATION_VERSION
    created_at: str = ""
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "source_version_id": self.source_version_id,
            "content_hash": self.content_hash,
            "scope": {
                "profile_id": self.scope.profile_id,
                "project_id": self.scope.project_id,
                "knowledge_space_id": self.scope.knowledge_space_id,
            },
            "lifecycle_status": self.lifecycle_status,
            "supersedes": self.supersedes,
            "predecessor_content_hash": self.predecessor_content_hash,
            "normalization_version": self.normalization_version,
            "created_at": self.created_at,
            "provenance": dict(self.provenance),
        }


class CorpusVersionChain:
    """In-memory, deterministic source version chain (DERIVED; rebuildable).

    Tracks immutable versions per logical source_id in registration order. Registration is
    idempotent by content version id, so unchanged re-ingest produces no new
    version. A changed content under the same source_id links the new version to
    its predecessor via ``supersedes`` (history preserved, never overwritten).
    """

    def __init__(self) -> None:
        self._by_source: dict[str, list[CorpusSourceVersion]] = {}
        self._seen_version_ids: set[str] = set()

    def register(
        self,
        *,
        source_id: str,
        content_hash_value: str,
        scope: ScopeKey,
        lifecycle_status: str = "observed",
        created_at: str = "",
        normalization_version: str = NORMALIZATION_VERSION,
        provenance: Optional[Mapping[str, Any]] = None,
    ) -> CorpusSourceVersion:
        version_id = compute_source_version_id(
            source_id=source_id,
            content_hash_value=content_hash_value,
            scope=scope,
            normalization_version=normalization_version,
        )
        # Idempotent: unchanged content (and unchanged scope/logic) re-registered
        # => same version id => return existing; no new version created.
        for existing in self._by_source.get(source_id, []):
            if existing.source_version_id == version_id:
                return existing

        versions = self._by_source.setdefault(source_id, [])
        predecessor = versions[-1] if versions else None
        supersedes = predecessor.source_version_id if predecessor else None
        predecessor_content_hash = (
            predecessor.content_hash if predecessor and predecessor.content_hash != content_hash_value
            else None
        )
        version = CorpusSourceVersion(
            source_id=source_id,
            source_version_id=version_id,
            content_hash=content_hash_value,
            scope=scope,
            lifecycle_status=lifecycle_status,
            supersedes=supersedes,
            predecessor_content_hash=predecessor_content_hash,
            normalization_version=normalization_version,
            created_at=created_at,
            provenance=dict(provenance or {}),
        )
        versions.append(version)
        self._seen_version_ids.add(version_id)
        return version

    def register_from_record(
        self,
        record: CorpusSourceRecord,
        *,
        created_at: str = "",
        normalization_version: str = NORMALIZATION_VERSION,
    ) -> CorpusSourceVersion:
        return self.register(
            source_id=record.source_id,
            content_hash_value=record.content_hash,
            scope=scope_from_record(record),
            lifecycle_status=record.lifecycle_status,
            created_at=created_at or record.created_at,
            normalization_version=normalization_version,
            provenance=record.provenance,
        )

    def get_versions(self, source_id: str) -> tuple[CorpusSourceVersion, ...]:
        return tuple(self._by_source.get(source_id, []))

    def get_latest(self, source_id: str) -> Optional[CorpusSourceVersion]:
        versions = self._by_source.get(source_id)
        return versions[-1] if versions else None

    def is_unchanged(self, source_id: str, content_hash_value: str) -> bool:
        """True if latest recorded version for ``source_id`` has the same content."""
        latest = self.get_latest(source_id)
        return latest is not None and latest.content_hash == content_hash_value

    def version_count(self, source_id: str) -> int:
        return len(self._by_source.get(source_id, []))

    def all_versions(self) -> list[CorpusSourceVersion]:
        out: list[CorpusSourceVersion] = []
        for versions in self._by_source.values():
            out.extend(versions)
        return out


def build_version_chain(records: Iterable[CorpusSourceRecord]) -> CorpusVersionChain:
    """Rebuild a version chain deterministically from canonical source records."""
    chain = CorpusVersionChain()
    for rec in records:
        chain.register_from_record(rec)
    return chain


__all__ = [
    "ScopeKey",
    "scope_from_record",
    "compute_source_version_id",
    "CorpusSourceVersion",
    "CorpusVersionChain",
    "build_version_chain",
]
