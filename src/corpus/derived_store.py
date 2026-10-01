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

import dataclasses
import json
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Iterable, List, Mapping, Optional

from src.storage.migrations import migrate_10 as _migrate_10

from .contracts import CORPUS_SOURCE_RESOURCE_TYPE, CorpusSourceRecord, SourceSensitivity
from .dedup import UnitDedupIndex, unit_content_hash, unit_logical_id
from .normalize import normalize_extraction
from .redact import CorpusRedactionError, require_safe, scan_extracted_text
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
        "kind=excluded.kind, unit_order=excluded.unit_order, page=excluded.page, "
        "parent_ref=excluded.parent_ref, duplicate_of=excluded.duplicate_of, "
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


#: Closed per-source status vocabulary (DEF-060). The first nine are the M10.2
#: extraction outcomes; the rest are projection-level outcomes.
SOURCE_STATUS_COMPLETE: Final[str] = "complete"
SOURCE_STATUS_PARTIAL: Final[str] = "partial"
SOURCE_STATUS_UNSUPPORTED_FORMAT: Final[str] = "unsupported_format"
SOURCE_STATUS_CORRUPT_SOURCE: Final[str] = "corrupt_source"
SOURCE_STATUS_PARSER_UNAVAILABLE: Final[str] = "parser_unavailable"
SOURCE_STATUS_EMPTY_SOURCE: Final[str] = "empty_source"
SOURCE_STATUS_MISSING_SOURCE: Final[str] = "missing_source"
SOURCE_STATUS_PERMISSION_DENIED: Final[str] = "permission_denied"
SOURCE_STATUS_ADAPTER_FAILED: Final[str] = "adapter_failed"
#: Extraction succeeded but every unit was rejected by the secret backstop.
SOURCE_STATUS_REJECTED_SECRET: Final[str] = "rejected_secret"
#: ``sensitivity="secret"`` source: never extracted, never projected into units.
SOURCE_STATUS_WITHHELD_SENSITIVITY: Final[str] = "withheld_sensitivity"
#: No blob store / blob reference: nothing could be re-extracted.
SOURCE_STATUS_BLOB_UNAVAILABLE: Final[str] = "blob_unavailable"
#: ``source_status`` answer for a source the derived store has never seen.
SOURCE_STATUS_NOT_PROJECTED: Final[str] = "not_projected"

SOURCE_STATUSES: Final[frozenset] = frozenset({
    SOURCE_STATUS_COMPLETE, SOURCE_STATUS_PARTIAL, SOURCE_STATUS_UNSUPPORTED_FORMAT,
    SOURCE_STATUS_CORRUPT_SOURCE, SOURCE_STATUS_PARSER_UNAVAILABLE,
    SOURCE_STATUS_EMPTY_SOURCE, SOURCE_STATUS_MISSING_SOURCE,
    SOURCE_STATUS_PERMISSION_DENIED, SOURCE_STATUS_ADAPTER_FAILED,
    SOURCE_STATUS_REJECTED_SECRET, SOURCE_STATUS_WITHHELD_SENSITIVITY,
    SOURCE_STATUS_BLOB_UNAVAILABLE, SOURCE_STATUS_NOT_PROJECTED,
})

#: Key under which the per-source status is persisted in the derived
#: ``zm_corpus_sources.provenance`` JSON (no schema change; rebuild-deterministic).
_STATUS_PROVENANCE_KEY: Final[str] = "zm_projection"

_REASON_MAX_CHARS: Final[int] = 200


@dataclass
class CorpusProjectionReport:
    """Sanitized projection outcome (never carries raw text).

    ``source_statuses`` has one ``{source_id, status, reason, units,
    units_rejected_secret, contained_secret}`` entry per projected source
    (DEF-060), so a source that yields no units is never silent.
    """

    sources_projected: int = 0
    units_projected: int = 0
    units_rejected_secret: int = 0
    extractions_failed: int = 0
    source_statuses: List[dict] = field(default_factory=list)

    def as_dict(self, include_sources: bool = False) -> dict:
        out = {
            "sources_projected": self.sources_projected,
            "units_projected": self.units_projected,
            "units_rejected_secret": self.units_rejected_secret,
            "extractions_failed": self.extractions_failed,
        }
        if include_sources:
            out["source_statuses"] = [dict(entry) for entry in self.source_statuses]
        return out

    def merge(self, other: "CorpusProjectionReport") -> None:
        """Fold ``other`` (e.g. one source's report) into this aggregate."""
        self.sources_projected += other.sources_projected
        self.units_projected += other.units_projected
        self.units_rejected_secret += other.units_rejected_secret
        self.extractions_failed += other.extractions_failed
        self.source_statuses.extend(other.source_statuses)


@dataclass
class _Outcome:
    """What projecting one source's current version produced (internal)."""

    status: str
    reason: Optional[str] = None
    kept: set = field(default_factory=set)
    rejected_secret: int = 0
    contained_secret: bool = False
    #: False when nothing was attempted, so existing units must be left alone.
    touched_units: bool = True


def _flag_contained_secret(result):
    """Return ``result`` marked ``contained_secret=True`` (the dataclass is frozen)."""
    return dataclasses.replace(result, contained_secret=True)


def _clean_reason(reason: Optional[str]) -> str:
    """Bounded, secret-scanned, single-line reason string for persistence."""
    text = " ".join((reason or "unspecified").split())[:_REASON_MAX_CHARS] or "unspecified"
    if not scan_extracted_text(text).safe:
        return "redacted"
    return text


#: Max bound parameters per DELETE ... IN (...) (stay far below SQLite's limit).
_DELETE_BATCH: Final[int] = 400


def _prune_stale_units(cur: sqlite3.Cursor, source_id: str, keep_ids: set) -> None:
    """DEF-050: drop units + FTS rows of ``source_id`` that are not in ``keep_ids``.

    Runs inside the caller's transaction (never commits), so a reader sees either
    the old version's complete unit set or the new version's, never a mix.
    """
    existing = [
        row[0]
        for row in cur.execute(
            "SELECT unit_id FROM zm_corpus_units WHERE source_ref=?", (source_id,)
        ).fetchall()
    ]
    stale = [uid for uid in existing if uid not in keep_ids]
    for i in range(0, len(stale), _DELETE_BATCH):
        chunk = stale[i:i + _DELETE_BATCH]
        marks = ",".join("?" * len(chunk))
        if _migrate_10.FTS5_AVAILABLE:
            cur.execute(f"DELETE FROM zm_corpus_fts WHERE unit_id IN ({marks})", chunk)
        cur.execute(f"DELETE FROM zm_corpus_units WHERE unit_id IN ({marks})", chunk)


def _project_record(
    cur: sqlite3.Cursor,
    record: CorpusSourceRecord,
    store,
    report: "CorpusProjectionReport",
) -> None:
    """Project ONE source record (the shared core of project_source/project_corpus)."""
    _insert_source(cur, record)
    report.sources_projected += 1

    if record.sensitivity == SourceSensitivity.SECRET.value:
        # DEF-057: a secret source is withheld -- never read, extracted or
        # indexed -- and any units of an earlier version are removed.
        outcome = _Outcome(SOURCE_STATUS_WITHHELD_SENSITIVITY, "sensitivity_secret")
    elif store is None or not store.available or record.blob_ref is None:
        # No blob available to re-extract (e.g. blob store unconfigured).
        # Source projection still stands; units simply cannot be rebuilt, so
        # whatever units exist are left untouched.
        outcome = _Outcome(
            SOURCE_STATUS_BLOB_UNAVAILABLE,
            "no_blob_store" if store is None or not store.available else "no_blob_ref",
            touched_units=False,
        )
    else:
        outcome = _extract_source(cur, record, store, report)

    if outcome.touched_units:
        # DEF-050: the units of this source are exactly what the current version
        # yielded; anything else belongs to an earlier version and must go.
        _prune_stale_units(cur, record.source_id, outcome.kept)
        units = len(outcome.kept)
    else:
        units = cur.execute(
            "SELECT COUNT(*) FROM zm_corpus_units WHERE source_ref=?", (record.source_id,)
        ).fetchone()[0]
    _record_status(cur, record, outcome, units, report)


def _extract_source(cur, record, store, report) -> _Outcome:
    """Extract, normalize, dedup and insert one source's units (DEF-060 outcome)."""
    from .adapters.registry import select_adapter
    from .extract import ExtractionStatus

    try:
        content = store.get(record.blob_ref)
    except Exception as exc:
        report.extractions_failed += 1
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        return _Outcome(SOURCE_STATUS_MISSING_SOURCE, f"blob_read_failed:{_clean_reason(reason)}")

    adapter = select_adapter(record.kind)
    if adapter is None:
        report.extractions_failed += 1
        return _Outcome(
            SOURCE_STATUS_UNSUPPORTED_FORMAT,
            f"no_adapter_for_kind:{_clean_reason(record.kind)}",
        )
    if not adapter.is_available():
        report.extractions_failed += 1
        return _Outcome(
            SOURCE_STATUS_PARSER_UNAVAILABLE,
            f"parser_unavailable:{_clean_reason(getattr(adapter, 'parser_name', None))}",
        )

    try:
        result = adapter.extract(
            source_ref=record.source_id,
            content=content,
            kind_hint=record.kind,
        )
        extraction_status = ExtractionStatus.validate(result.status)
    except Exception as exc:
        report.extractions_failed += 1
        return _Outcome(SOURCE_STATUS_ADAPTER_FAILED, f"adapter_error:{type(exc).__name__}")

    if not extraction_status.is_success:
        report.extractions_failed += 1
        return _Outcome(extraction_status.value, _clean_reason(result.error_reason))

    norm = normalize_extraction(result)
    if not norm.ok:
        return _Outcome(SOURCE_STATUS_EMPTY_SOURCE, "no_normalized_units")

    kept: set = set()
    rejected = 0
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
            kept.add(_unit_id(unit, record))
            report.units_projected += 1
        except CorpusRedactionError:
            rejected += 1
            report.units_rejected_secret += 1

    contained = False
    if rejected:
        result = _flag_contained_secret(result)
        contained = result.contained_secret

    if not kept:
        status = SOURCE_STATUS_REJECTED_SECRET if rejected else SOURCE_STATUS_ADAPTER_FAILED
        reason = f"units_rejected_secret:{rejected}" if rejected else "no_unit_persisted"
        return _Outcome(status, reason, kept, rejected, contained)
    reason = f"units_rejected_secret:{rejected}" if rejected else None
    return _Outcome(extraction_status.value, reason, kept, rejected, contained)


def _record_status(cur, record, outcome: _Outcome, units: int, report) -> None:
    """Persist + report the per-source status (same transaction as the units)."""
    entry = {
        "status": outcome.status,
        "reason": outcome.reason,
        "units": units,
        "units_rejected_secret": outcome.rejected_secret,
        "contained_secret": outcome.contained_secret,
    }
    provenance = dict(record.provenance)
    provenance[_STATUS_PROVENANCE_KEY] = entry
    cur.execute(
        "UPDATE zm_corpus_sources SET provenance=? WHERE source_id=?",
        (json.dumps(provenance, sort_keys=True, ensure_ascii=False), record.source_id),
    )
    report.source_statuses.append({"source_id": record.source_id, **entry})


def source_status(conn: sqlite3.Connection, source_id: str) -> dict:
    """Per-source projection status (DEF-060), read from the derived store.

    Returns ``{source_id, status, reason, units, units_rejected_secret,
    contained_secret}`` where ``status`` is in :data:`SOURCE_STATUSES`. A source
    the derived store has never seen is ``not_projected``; a row projected before
    status tracking existed is derived from its unit count. Read-only: works on a
    ``mode=ro`` connection.
    """
    row = conn.execute(
        "SELECT provenance FROM zm_corpus_sources WHERE source_id=?", (source_id,)
    ).fetchone()
    if row is None:
        return {
            "source_id": source_id, "status": SOURCE_STATUS_NOT_PROJECTED,
            "reason": "no_such_source", "units": 0,
            "units_rejected_secret": 0, "contained_secret": False,
        }
    try:
        stored = (json.loads(row[0]) if row[0] else {}).get(_STATUS_PROVENANCE_KEY)
    except (TypeError, ValueError):
        stored = None
    if isinstance(stored, dict) and stored.get("status") in SOURCE_STATUSES:
        return {
            "source_id": source_id,
            "status": stored["status"],
            "reason": stored.get("reason"),
            "units": int(stored.get("units", 0)),
            "units_rejected_secret": int(stored.get("units_rejected_secret", 0)),
            "contained_secret": bool(stored.get("contained_secret", False)),
        }
    units = conn.execute(
        "SELECT COUNT(*) FROM zm_corpus_units WHERE source_ref=?", (source_id,)
    ).fetchone()[0]
    return {
        "source_id": source_id,
        "status": SOURCE_STATUS_COMPLETE if units else SOURCE_STATUS_EMPTY_SOURCE,
        "reason": "projected_before_status_tracking",
        "units": int(units),
        "units_rejected_secret": 0,
        "contained_secret": False,
    }


def _latest_records(registry: CorpusSourceRegistry) -> List[CorpusSourceRecord]:
    """Latest registered version per logical source, in deterministic id order.

    Older versions are superseded history (kept canonically in the registry); the
    derived projection only ever represents the current version of a source.
    """
    latest: dict = {}
    for record in registry.all_records():
        latest[record.source_id] = record
    return [latest[sid] for sid in sorted(latest)]


def _resolve_store(registry: CorpusSourceRegistry, blob_store):
    from .blob_store import CorpusBlobStore

    return blob_store or (
        CorpusBlobStore(root=registry._root) if registry._root is not None else None
    )


def project_source(
    conn: sqlite3.Connection,
    registry: CorpusSourceRegistry,
    source,
    blob_store=None,
) -> CorpusProjectionReport:
    """Project ONE logical source (DEF-058): O(that source), not O(registry).

    ``source`` is a ``source_id`` or a :class:`CorpusSourceRecord`. Semantics are
    exactly those of :func:`project_corpus` applied to that source: the *latest*
    registered version is extracted, normalized, deduplicated and persisted, and
    units of any earlier version it no longer yields are removed (DEF-050). A
    stale record handed in for a source that has since been superseded is
    resolved to the registry's latest version, so the derived state can never
    regress. Runs inside the caller's transaction and never commits.

    Raises :class:`CorpusProjectionError` for a ``source_id`` the registry does
    not know.
    """
    if isinstance(source, CorpusSourceRecord):
        record = registry.get_by_source_id(source.source_id) or source
    else:
        record = registry.get_by_source_id(source) if isinstance(source, str) else None
        if record is None:
            raise CorpusProjectionError("corpus_projection: unknown_source")
    report = CorpusProjectionReport()
    _project_record(conn.cursor(), record, _resolve_store(registry, blob_store), report)
    return report


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

    Only the latest version of each logical source is projected (via
    :func:`project_source`); units of an earlier version that the latest version
    no longer yields are removed in the same (caller-owned) transaction (DEF-050).

    Secret-bearing units are rejected (fail-closed) and counted, never stored.
    """
    store = _resolve_store(registry, blob_store)
    records = _latest_records(registry)

    report = CorpusProjectionReport()

    # Version chain (derived; traceable supersession). Not persisted as a table
    # here, but the per-source latest/version logic is re-usable by M10.5.
    _chain = build_version_chain(registry.all_records())

    for record in records:
        report.merge(project_source(conn, registry, record, blob_store=store))

    return report


# ---------------------------------------------------------------------------
# Rebuild
# ---------------------------------------------------------------------------

#: Drop order of the v10 derived corpus tables (children before parents).
_DERIVED_DROP_ORDER: Final[tuple] = (
    "zm_corpus_fts",
    "zm_corpus_units",
    "zm_corpus_entities",
    "zm_corpus_relations",
    "zm_corpus_sources",
)

#: Tables the projection populates (copied from the staged build; parents first).
_PROJECTED_TABLES: Final[tuple] = ("zm_corpus_sources", "zm_corpus_units", "zm_corpus_fts")

_COPY_BATCH: Final[int] = 1000


def _copy_table(src: sqlite3.Connection, dst: sqlite3.Connection, table: str) -> None:
    cursor = src.execute(f"SELECT * FROM {table}")
    marks = ",".join("?" * len(cursor.description))
    while True:
        rows = cursor.fetchmany(_COPY_BATCH)
        if not rows:
            return
        dst.executemany(f"INSERT INTO {table} VALUES ({marks})", rows)


def _swap_in_staged(conn: sqlite3.Connection, stage: sqlite3.Connection) -> None:
    """Replace the live derived corpus tables with the staged build, atomically.

    One write transaction does DROP + CREATE + bulk copy, so a concurrent reader
    (WAL snapshot) sees either the complete old state or the complete new state --
    never missing tables or partial rows. If the caller already has a transaction
    open the swap joins it (and is undone by the caller's rollback); otherwise the
    swap owns a transaction and commits it.
    """
    owns_txn = not conn.in_transaction
    if owns_txn:
        conn.execute("BEGIN IMMEDIATE")
    conn.execute("SAVEPOINT zm_corpus_swap")
    try:
        for tbl in _DERIVED_DROP_ORDER:  # derived corpus tables only; never memory tables
            conn.execute(f"DROP TABLE IF EXISTS {tbl}")
        # Recreate via the migration framework (idempotent; only v10 tables touch
        # corpus state). We re-run migrate_10.up directly so we do not disturb the
        # v1-v9 schema or the zm_migrations ledger ordering.
        _migrate_10.up(conn, note="m10.4_rebuild")
        for tbl in _PROJECTED_TABLES:
            if tbl == "zm_corpus_fts" and not _migrate_10.FTS5_AVAILABLE:
                continue
            _copy_table(stage, conn, tbl)
        conn.execute("RELEASE SAVEPOINT zm_corpus_swap")
    except BaseException:
        try:
            conn.execute("ROLLBACK TO SAVEPOINT zm_corpus_swap")
            conn.execute("RELEASE SAVEPOINT zm_corpus_swap")
            if owns_txn:
                conn.rollback()
        except sqlite3.Error:
            pass
        raise
    if owns_txn:
        conn.commit()


def rebuild_from_corpus(
    conn: sqlite3.Connection,
    registry: CorpusSourceRegistry,
    blob_store=None,
) -> CorpusProjectionReport:
    """Deterministic, reader-safe rebuild of the M10.4 derived corpus state.

    The projection (the slow part: blob reads, extraction, normalization) is
    built first into a private staging database, holding no lock on ``conn``.
    Only then does one short write transaction drop the v10 derived corpus
    tables, recreate them via the migration framework and bulk-copy the staged
    rows in (DEF-059), so concurrent readers never observe an empty or partial
    corpus and other writers are not blocked for the extraction time. Canonical
    JSONL and blobs are never touched. If staging or the swap fails the live
    tables are left exactly as they were and the exception propagates.

    When ``conn`` has no open transaction the swap is committed before this
    returns; when the caller already holds one it is part of that transaction.
    """
    with tempfile.TemporaryDirectory(prefix="zm-corpus-stage-") as stage_dir:
        stage = sqlite3.connect(str(Path(stage_dir) / "stage.sqlite"))
        try:
            # Disposable scratch database: durability is irrelevant.
            stage.execute("PRAGMA journal_mode=MEMORY")
            stage.execute("PRAGMA synchronous=OFF")
            _migrate_10.up(stage, note="m10.4_rebuild_stage")
            report = project_corpus(stage, registry, blob_store=blob_store)
            stage.commit()
            _swap_in_staged(conn, stage)
        finally:
            stage.close()
    return report


__all__ = [
    "CORPUS_UNIT_RESOURCE_TYPE",
    "CORPUS_PROJECTION_VERSION",
    "CORPUS_IDENTITY_VERSION",
    "CorpusProjectionError",
    "CorpusProjectionReport",
    "SOURCE_STATUSES",
    "project_corpus",
    "project_source",
    "rebuild_from_corpus",
    "source_status",
]
