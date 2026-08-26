"""M10.4 — derived corpus storage projection + deterministic rebuild.

This module is the WRITE/projection path for the M10.4 derived corpus SQLite
store. It is deliberately separate from any READ/retrieval path (M10.5+): it
builds derived tables from canonical corpus state and never serves queries.

Authoritative boundary (load-bearing):

- CANONICAL corpus truth = the blob store (source bytes) + ``corpus_sources.jsonl``
  (the M10.1 registry). This module reads those read-only and never mutates them.
- DERIVED corpus state = ``zm_corpus_sources`` / ``zm_corpus_units`` /
  ``zm_corpus_fts`` / ``zm_corpus_relations`` / ``zm_corpus_entities``. Fully
  rebuildable from canonical state via :func:`rebuild_from_corpus`.

Rebuild invariant (docs/plans/plan-m10.md §11): destroy the derived corpus SQLite state,
read the canonical registry + blobs, re-run the frozen M10.2 extractor and
M10.3 normalizer/dedup, and recreate the M10.4 derived state. The rebuilt state
must be equivalent to the originally projected state given identical canonical
input and identical extractor/normalizer logic.

Security:

- Every unit's ``normalized_text`` is scanned by the fail-closed M10.2 redactor
  (``require_safe``) BEFORE any derived row is written. A secret-shaped unit is
  rejected at the projection boundary — never stored, never indexed. This
  preserves the M1/M9 non-disableable secret backstop at the corpus boundary.
- ``resource_type`` is fixed per table (``corpus_source`` / ``corpus_unit``), so
  the two authorization resource types stay distinct (permanent M6.6 invariant).
- Authorization (M5) is NOT performed here; this is a storage projection. The
  read path (M10.5) must route corpus reads through ``AuthorizedReadService``.
- V1.6 event Multi-KS does not widen corpus scope: every source and derived unit
  still carries zero or one ``knowledge_space_id``.  No event-space junction is
  consulted or copied here; widening corpus scope needs a separate increment.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Iterable, List, Mapping, Optional

from src.storage.migrations import migrate_10 as _migrate_10

from .contracts import CORPUS_SOURCE_RESOURCE_TYPE, CorpusSourceRecord
from .dedup import UnitDedupIndex, unit_content_hash, unit_logical_id
from .normalize import normalize_extraction
from .redact import CorpusRedactionError, require_safe
from .registry import CORPUS_ROOT_ENV_VAR, REGISTRY_FILENAME, CorpusSourceRegistry
from .versioning import build_version_chain

#: Closed resource type for units (distinct from corpus_source; M6.6 invariant).
CORPUS_UNIT_RESOURCE_TYPE: Final[str] = "corpus_unit"

#: Projection version (distinct from normalization_version / extractor_version).
CORPUS_PROJECTION_VERSION: Final[str] = "m10.4"

#: Identity version for rebuild determinism.
CORPUS_IDENTITY_VERSION: Final[str] = "m10.4"


class CorpusProjectionError(RuntimeError):
    """Sanitized failure during derived corpus projection (never leaks text)."""


# ---------------------------------------------------------------------------
# Unit identity helpers (reuse M10.3 dedup identity for derived persistence).
# ---------------------------------------------------------------------------

def _unit_id(unit, source_record: CorpusSourceRecord) -> str:
    """Stable derived unit primary key = the M10.3 logical unit id.

    The logical id is (source_ref, source_location_id), so identical content
    under different sources/scopes yields distinct unit ids — cross-scope
    authorization identity is never collapsed (plan §7).
    """
    return unit_logical_id(unit)


def _provenance_hash(unit, source_record: CorpusSourceRecord) -> str:
    """Deterministic provenance fingerprint (content + scope + source)."""
    payload = {
        "source_id": source_record.source_id,
        "source_ref": unit.source_ref,
        "source_location_id": unit.source_location_id,
        "content_hash": unit_content_hash(unit),
        "scope": [
            source_record.profile_id,
            source_record.project_id,
            source_record.knowledge_space_id,
        ],
    }
    import hashlib

    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

def _insert_source(cur: sqlite3.Cursor, record: CorpusSourceRecord) -> None:
    cur.execute(
        "INSERT INTO zm_corpus_sources "
        "(source_id, content_hash, external_ref, kind, resource_type, "
        " profile_id, project_id, knowledge_space_id, sensitivity, "
        " lifecycle_status, blob_ref, created_at, provenance, custom_meta) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(source_id) DO UPDATE SET "
        "content_hash=excluded.content_hash, external_ref=excluded.external_ref, "
        "kind=excluded.kind, sensitivity=excluded.sensitivity, "
        "lifecycle_status=excluded.lifecycle_status, blob_ref=excluded.blob_ref, "
        "provenance=excluded.provenance, custom_meta=excluded.custom_meta",
        (
            record.source_id,
            record.content_hash,
            record.external_ref,
            record.kind,
            CORPUS_SOURCE_RESOURCE_TYPE,
            record.profile_id,
            record.project_id,
            record.knowledge_space_id,
            record.sensitivity,
            record.lifecycle_status,
            record.blob_ref,
            record.created_at,
            json.dumps(record.provenance, sort_keys=True, ensure_ascii=False),
            json.dumps(record.custom_meta, sort_keys=True, ensure_ascii=False),
        ),
    )


def _insert_unit(
    cur: sqlite3.Cursor,
    unit,
    source_record: CorpusSourceRecord,
    duplicate_of: Optional[str],
) -> None:
    uid = _unit_id(unit, source_record)
    # Fail-closed: reject any unit whose normalized text carries a secret.
    require_safe(unit.normalized_text)
    cur.execute(
        "INSERT INTO zm_corpus_units "
        "(unit_id, source_ref, source_location_id, content_hash, normalized_text, "
        " kind, resource_type, unit_order, page, parent_ref, "
        " profile_id, project_id, knowledge_space_id, duplicate_of, "
        " lifecycle_status, sensitivity, created_at, provenance_hash) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(unit_id) DO UPDATE SET "
        "content_hash=excluded.content_hash, normalized_text=excluded.normalized_text, "
        "kind=excluded.kind, duplicate_of=excluded.duplicate_of, "
        "lifecycle_status=excluded.lifecycle_status, sensitivity=excluded.sensitivity, "
        "provenance_hash=excluded.provenance_hash",
        (
            uid,
            unit.source_ref,
            unit.source_location_id,
            unit_content_hash(unit),
            unit.normalized_text,
            unit.kind,
            CORPUS_UNIT_RESOURCE_TYPE,
            unit.order,
            unit.page,
            unit.parent_ref,
            source_record.profile_id,
            source_record.project_id,
            source_record.knowledge_space_id,
            duplicate_of,
            source_record.lifecycle_status,
            source_record.sensitivity,
            source_record.created_at,
            _provenance_hash(unit, source_record),
        ),
    )
    if _migrate_10.FTS5_AVAILABLE:
        # Sanitized content only is indexed. require_safe already guaranteed the
        # text is secret-free; index the same normalized_text. Mirror the
        # zm_fts delete-then-insert pattern (FTS5 rowid upsert is not reliable).
        cur.execute("DELETE FROM zm_corpus_fts WHERE unit_id=?", (uid,))
        cur.execute(
            "INSERT INTO zm_corpus_fts (unit_id, content) VALUES (?, ?)",
            (uid, unit.normalized_text),
        )


@dataclass
class CorpusProjectionReport:
    """Sanitized projection outcome (never carries raw text)."""

    sources_projected: int = 0
    units_projected: int = 0
    units_rejected_secret: int = 0
    extractions_failed: int = 0

    def as_dict(self) -> dict:
        return {
            "sources_projected": self.sources_projected,
            "units_projected": self.units_projected,
            "units_rejected_secret": self.units_rejected_secret,
            "extractions_failed": self.extractions_failed,
        }


def project_corpus(
    conn: sqlite3.Connection,
    registry: CorpusSourceRegistry,
    blob_store=None,
) -> CorpusProjectionReport:
    """Project the canonical corpus registry + blobs into derived SQLite tables.

    Pure WRITE/projection: no read/ranking/retrieval. Reads the registry
    (canonical) and the blob store (canonical bytes) read-only, applies the
    frozen M10.2 extractor + M10.3 normalizer/dedup deterministically, and
    persists the derived projection. Idempotent: re-projection over the same
    canonical state produces the same derived rows (ON CONFLICT upserts).

    Secret-bearing units are rejected (fail-closed) and counted, never stored.
    """
    from .adapters.registry import select_adapter
    from .blob_store import CorpusBlobStore
    from .extract import ExtractionStatus

    store = blob_store or (
        CorpusBlobStore(root=registry._root) if registry._root is not None else None
    )
    records = registry.all_records()
    # Deterministic source order (by source_id) for reproducible projection.
    records = sorted(records, key=lambda r: r.source_id)

    report = CorpusProjectionReport()
    cur = conn.cursor()

    # Version chain (derived; traceable supersession). Not persisted as a table
    # here, but the per-source latest/version logic is re-usable by M10.5.
    _chain = build_version_chain(records)

    for record in records:
        _insert_source(cur, record)
        report.sources_projected += 1

        if store is None or not store.available or record.blob_ref is None:
            # No blob available to re-extract (e.g. blob store unconfigured).
            # Source projection still stands; units simply cannot be rebuilt.
            continue

        try:
            content = store.get(record.blob_ref)
        except Exception:
            report.extractions_failed += 1
            continue

        adapter = select_adapter(record.kind)
        if adapter is None or not adapter.is_available():
            report.extractions_failed += 1
            continue

        try:
            result = adapter.extract(
                source_ref=record.source_id,
                content=content,
                kind_hint=record.kind,
            )
        except Exception:
            report.extractions_failed += 1
            continue

        if not ExtractionStatus.validate(result.status).is_success:
            report.extractions_failed += 1
            continue

        norm = normalize_extraction(result)
        if not norm.ok:
            continue

        # Class C dedup within this source scope only (never across sources).
        dedup = UnitDedupIndex()
        for unit in norm.units:
            try:
                outcome = dedup.process(unit)
            except Exception:
                report.extractions_failed += 1
                continue
            try:
                _insert_unit(
                    cur,
                    unit,
                    record,
                    duplicate_of=outcome.duplicate_of,
                )
                report.units_projected += 1
            except CorpusRedactionError:
                report.units_rejected_secret += 1

    return report


# ---------------------------------------------------------------------------
# Rebuild
# ---------------------------------------------------------------------------

def rebuild_from_corpus(
    conn: sqlite3.Connection,
    registry: CorpusSourceRegistry,
    blob_store=None,
) -> CorpusProjectionReport:
    """Deterministic rebuild of the M10.4 derived corpus state.

    Drops only the v10 derived corpus tables, recreates them via the migration
    framework, then re-projects from canonical registry + blobs. Canonical JSONL
    and blobs are never touched. On failure the derived tables are left as the
    partially-recreated (still rebuildable) state but the exception propagates
    so callers can decide; the canonical corpus is unaffected.
    """
    cur = conn.cursor()
    # Drop derived corpus tables (NOT memory tables, NOT canonical data).
    for tbl in (
        "zm_corpus_fts",
        "zm_corpus_units",
        "zm_corpus_entities",
        "zm_corpus_relations",
        "zm_corpus_sources",
    ):
        cur.execute(f"DROP TABLE IF EXISTS {tbl}")
    conn.commit()
    # Recreate via the migration framework (idempotent; only v10 tables touch
    # corpus state). We re-run migrate_10.up directly so we do not disturb the
    # v1-v9 schema or the zm_migrations ledger ordering.
    _migrate_10.up(conn, note="m10.4_rebuild")
    return project_corpus(conn, registry, blob_store=blob_store)


__all__ = [
    "CORPUS_UNIT_RESOURCE_TYPE",
    "CORPUS_PROJECTION_VERSION",
    "CORPUS_IDENTITY_VERSION",
    "CorpusProjectionError",
    "CorpusProjectionReport",
    "project_corpus",
    "rebuild_from_corpus",
]
