"""R3 isolated legacy compatibility and persistence regressions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.corpus.compatibility import convert_legacy_registry
from src.corpus.contracts import CorpusSourceRecord
from src.corpus.derived_store import project_corpus, rebuild_from_corpus
from src.corpus.identity import source_descriptor
from src.corpus.registry import CorpusSourceRegistry
from src.corpus.versioning import build_version_chain
from src.m8.identity import content_hash
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.corpus.blob_store import CorpusBlobStore


def _legacy_record(content: bytes, *, external_ref: str, profile_id: str, project_id: str) -> CorpusSourceRecord:
    descriptor = source_descriptor(
        external_ref=external_ref,
        kind="txt",
        profile_id=profile_id,
        project_id=project_id,
    )
    legacy_content_hash = content_hash({
        "domain": "corpus_source",
        "descriptor": descriptor,
        "content_bytes_sha256": hashlib.sha256(content).hexdigest(),
    })
    legacy_source_id = content_hash({
        "domain": "corpus_source",
        "content_hash": legacy_content_hash,
        "scope": f"{profile_id}|{project_id}|",
    })
    return CorpusSourceRecord(
        source_id=legacy_source_id,
        content_hash=legacy_content_hash,
        external_ref=external_ref,
        kind="txt",
        created_at="2026-01-01T00:00:00+00:00",
        profile_id=profile_id,
        project_id=project_id,
        blob_ref="legacy-placeholder",
        provenance={"legacy_fixture": True},
    )


def _write_legacy_fixture(root: Path, records: list[tuple[CorpusSourceRecord, bytes]]) -> bytes:
    root.mkdir()
    blobs = CorpusBlobStore(root=root)
    lines = []
    for record, content in records:
        digest = blobs.put(content=content, source_ref=record.source_id)
        record = CorpusSourceRecord(**{**record.as_dict(), "blob_ref": digest})
        lines.append(json.dumps(record.as_dict(), sort_keys=True, separators=(",", ":")))
    path = root / "corpus_sources.jsonl"
    path.write_text("\n".join(lines) + "\n")
    return hashlib.sha256(path.read_bytes()).digest()


def _logical_state(store: SQLiteStore) -> tuple:
    sources = tuple(store._conn.execute(
        "SELECT source_id, content_hash, external_ref, profile_id, project_id "
        "FROM zm_corpus_sources ORDER BY source_id"
    ).fetchall())
    units = tuple(store._conn.execute(
        "SELECT unit_id, source_ref, content_hash, profile_id, project_id "
        "FROM zm_corpus_units ORDER BY unit_id"
    ).fetchall())
    return (
        tuple(tuple(row) for row in sources),
        tuple(tuple(row) for row in units),
    )


def _tree_digest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_isolated_legacy_conversion_preserves_ids_and_rebuilds(tmp_path):
    original = tmp_path / "legacy"
    output = tmp_path / "converted"
    old1 = _legacy_record(b"legacy v1\n", external_ref="docs/a.txt", profile_id="p1", project_id="P")
    old1_v2 = _legacy_record(b"legacy v2\n", external_ref="docs/a.txt", profile_id="p1", project_id="P")
    old2 = _legacy_record(b"same bytes\n", external_ref="docs/renamed.txt", profile_id="p1", project_id="P")
    before = _write_legacy_fixture(
        original,
        [(old1, b"legacy v1\n"), (old1_v2, b"legacy v2\n"), (old2, b"same bytes\n")],
    )
    before_tree = _tree_digest(original)

    report = convert_legacy_registry(input_root=original, output_root=output)
    assert report.input_records == 3
    assert report.output_records == 3
    assert set(report.legacy_source_ids) == {old1.source_id, old1_v2.source_id, old2.source_id}

    converted = CorpusSourceRegistry(root=output)
    records = converted.all_records()
    assert len(records) == 3
    assert all(r.source_id != legacy.source_id for r, legacy in zip(records, (old1, old1_v2, old2)))
    for record, legacy in zip(records, (old1, old1_v2, old2)):
        assert record.provenance["legacy_source_id"] == legacy.source_id
        assert record.provenance["legacy_content_hash"] == legacy.content_hash
        assert record.external_ref == legacy.external_ref
        assert (record.profile_id, record.project_id) == (legacy.profile_id, legacy.project_id)

    chain = build_version_chain(records)
    assert chain.version_count(records[0].source_id) == 2
    assert chain.get_versions(records[1].source_id)[1].supersedes == chain.get_versions(records[1].source_id)[0].source_version_id
    assert chain.version_count(records[2].source_id) == 1

    first_store = SQLiteStore(SQLiteStoreConfig(path=tmp_path / "first.sqlite"))
    first_store.ensure_schema()
    blob_store = CorpusBlobStore(root=output)
    project_corpus(first_store._conn, converted, blob_store=blob_store)
    first_store._conn.commit()
    first_state = _logical_state(first_store)
    first_store.close()

    reopened_registry = CorpusSourceRegistry(root=output)
    second_store = SQLiteStore(SQLiteStoreConfig(path=tmp_path / "second.sqlite"))
    second_store.ensure_schema()
    project_corpus(second_store._conn, reopened_registry, blob_store=CorpusBlobStore(root=output))
    second_store._conn.commit()
    rebuild_from_corpus(second_store._conn, reopened_registry, blob_store=CorpusBlobStore(root=output))
    second_store._conn.commit()
    assert _logical_state(second_store) == first_state
    second_store.close()

    third_store = SQLiteStore(SQLiteStoreConfig(path=tmp_path / "first.sqlite"))
    assert _logical_state(third_store) == first_state
    third_store.close()

    assert hashlib.sha256((original / "corpus_sources.jsonl").read_bytes()).digest() == before
    assert _tree_digest(original) == before_tree


def test_compatibility_requires_explicit_distinct_roots(tmp_path):
    try:
        convert_legacy_registry(input_root=tmp_path, output_root=tmp_path)
    except ValueError as exc:
        assert "input_output_roots_must_differ" in str(exc)
    else:
        raise AssertionError("same-root compatibility conversion must fail closed")


def test_corpus_provenance_does_not_alias_memory_source_event_id():
    record = _legacy_record(b"x", external_ref="docs/a.txt", profile_id="p", project_id="P")
    assert "source_event_id" not in record.as_dict()
    assert "source_id" in record.as_dict()
