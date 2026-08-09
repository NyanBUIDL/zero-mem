"""M8.2 focused tests — persistence, idempotence, and deterministic rebuild.

Exercises the real v9 derived tables through an actual SQLite store: source
scanning, projection, duplicate safety, clear/rebuild equivalence, index-version
bookkeeping, and canonical preservation.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.m8.derived_index import (
    BUILD_STATUS_PUBLISHED,
    derived_state_snapshot,
    get_index_version,
    m8_derived_state_is_empty,
)
from src.m8.graph_projection import EntitySourceRecord, MentionSourceRecord
from src.m8.graph_sources import (
    compute_source_descriptor,
    read_all_edge_sources,
    read_m2_relation_edges,
    read_m4_project_link_edges,
    read_m4_supersession_edges,
    read_m4_verification_edges,
)
from src.m8.projection_store import (
    GRAPH_INDEX_NAME,
    GraphPersistenceError,
    graph_edge_count,
    project_graph_from_sources,
    rebuild_graph,
)
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig

TS = "2026-01-02T03:04:05+00:00"
TS2 = "2026-01-03T03:04:05+00:00"


def _event(conn: sqlite3.Connection, event_id: str, **kw) -> None:
    conn.execute(
        "INSERT INTO zm_meta (event_id, trace_id, event_type, source, schema_version, "
        "created_at, observed_at, sequence, profile_id, project_id, lifecycle_status, "
        "verification_status, confidence, sensitivity, retention, content_hash, "
        "redaction_applied, ingested_at, origin_jsonl) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            event_id,
            kw.get("trace_id", f"T-{event_id}"),
            kw.get("event_type", "note"),
            "test",
            1,
            kw.get("created_at", TS),
            TS,
            kw.get("sequence", 1),
            kw.get("profile_id"),
            kw.get("project_id"),
            kw.get("lifecycle_status", "candidate"),
            kw.get("verification_status", "none"),
            "medium",
            "normal",
            "standard",
            f"h-{event_id}",
            0,
            TS,
            "raw.jsonl",
        ),
    )


def _relation(conn: sqlite3.Connection, frm: str, to: str, relation: str) -> None:
    conn.execute(
        "INSERT INTO zm_relations (from_event_id, to_event_id, relation, verifier, "
        "evidence_ref, created_at) VALUES (?,?,?,?,?,?)",
        (frm, to, relation, "deterministic_check", None, TS),
    )


@pytest.fixture()
def db(tmp_path: Path):
    store = SQLiteStore(SQLiteStoreConfig(path=tmp_path / "meta.sqlite"))
    store.ensure_schema()
    try:
        yield store
    finally:
        store.close()


@pytest.fixture()
def seeded(db):
    conn = db._conn
    _event(conn, "E1", profile_id="prof-a", project_id="P1")
    _event(conn, "E2", profile_id="prof-a", project_id="P1", sequence=2)
    _event(conn, "E3", profile_id="prof-b", project_id="P2", sequence=3)
    _relation(conn, "E2", "E1", "derived_from")
    _relation(conn, "E2", "E1", "child_of")  # unmapped: must be reported, not projected
    _relation(conn, "E3", "E1", "supersedes")
    conn.execute(
        "INSERT INTO zm_artifacts (artifact_id, content_hash, kind, retention, "
        "origin_event_id, stored_path, created_at) VALUES (?,?,?,?,?,?,?)",
        ("A1", "ch", "text", "persistent", "E1", None, TS),
    )
    conn.execute(
        "INSERT INTO zm_decisions (decision_id, project_id, lifecycle_status) "
        "VALUES (?,?,?)",
        ("D1", "P1", "superseded"),
    )
    conn.execute(
        "INSERT INTO zm_requirements (requirement_id, project_id, created_at, "
        "lifecycle_status) VALUES (?,?,?,?)",
        ("R1", "P1", TS, "superseded"),
    )
    conn.execute(
        "INSERT INTO zm_decisions (decision_id, project_id, lifecycle_status, "
        "linked_requirement_ids, supersedes_id, profile_id, trace_id) "
        "VALUES (?,?,?,?,?,?,?)",
        ("D2", "P1", "candidate", "R1,R2", "D1", "prof-a", "T-D2"),
    )
    conn.execute(
        "INSERT INTO zm_requirements (requirement_id, project_id, created_at, "
        "lifecycle_status, supersedes, profile_id) VALUES (?,?,?,?,?,?)",
        ("R2", "P1", TS, "candidate", "R1", "prof-a"),
    )
    conn.execute(
        "INSERT INTO zm_verifications (verification_id, subject_type, subject_id, "
        "project_id, verification_status) VALUES (?,?,?,?,?)",
        ("V1", "decision", "D2", "P1", "deterministic_verification"),
    )
    conn.execute(
        "INSERT INTO zm_verifications (verification_id, subject_type, subject_id, "
        "project_id, verification_status) VALUES (?,?,?,?,?)",
        ("V2", "session", "S9", "P1", "deterministic_verification"),  # unmapped subject type
    )
    conn.execute(
        "INSERT INTO zm_project_artifacts (artifact_id, project_id, created_at, "
        "linked_decision_ids) VALUES (?,?,?,?)",
        ("A1", "P1", TS, "D2"),
    )
    conn.commit()
    return db


class TestSourceReaders:
    def test_mapped_m2_relations_projected(self, seeded):
        scan = read_m2_relation_edges(seeded._conn)
        pairs = {(e.from_resource_id, e.relation_type, e.to_resource_id) for e in scan.edges}
        assert ("E2", "derived_from", "E1") in pairs
        assert ("E3", "supersedes", "E1") in pairs

    def test_unmapped_relation_reported_not_projected(self, seeded):
        scan = read_m2_relation_edges(seeded._conn)
        assert all(e.relation_type != "child_of" for e in scan.edges)
        reasons = {s.reason_code for s in scan.skipped}
        assert "unmapped_source_relation_type" in reasons

    def test_m4_supersession_projected_as_recorded(self, seeded):
        scan = read_m4_supersession_edges(seeded._conn)
        pairs = {(e.from_resource_type, e.from_resource_id, e.to_resource_id) for e in scan.edges}
        assert ("decision", "D2", "D1") in pairs
        assert ("requirement", "R2", "R1") in pairs

    def test_m4_link_list_expands_deterministically(self, seeded):
        scan = read_m4_project_link_edges(seeded._conn)
        targets = [
            e.to_resource_id
            for e in scan.edges
            if e.from_resource_id == "D2" and e.relation_type == "decision_for"
        ]
        assert targets == ["R1", "R2"]

    def test_project_artifact_keeps_own_resource_type(self, seeded):
        scan = read_m4_project_link_edges(seeded._conn)
        pa = [e for e in scan.edges if e.from_resource_id == "A1" and e.from_resource_type == "project_artifact"]
        assert pa and all(e.from_resource_type == "project_artifact" for e in pa)

    def test_verification_edge_projected(self, seeded):
        scan = read_m4_verification_edges(seeded._conn)
        edges = [e for e in scan.edges if e.from_resource_id == "V1"]
        assert edges and edges[0].to_resource_type == "decision"

    def test_unmapped_verification_subject_skipped(self, seeded):
        scan = read_m4_verification_edges(seeded._conn)
        assert all(e.from_resource_id != "V2" for e in scan.edges)
        assert any(
            s.reason_code == "unmapped_verification_subject_type" for s in scan.skipped
        )

    def test_scan_order_is_stable(self, seeded):
        first = [e.source_ref for e in read_all_edge_sources(seeded._conn).edges]
        second = [e.source_ref for e in read_all_edge_sources(seeded._conn).edges]
        assert first == second


class TestProjectionPersistence:
    def test_projection_writes_edges(self, seeded):
        report = project_graph_from_sources(seeded._conn)
        assert report.edges_written == report.edges_projected > 0
        assert graph_edge_count(seeded._conn) == report.edges_written

    def test_projecting_twice_creates_no_duplicates(self, seeded):
        first = project_graph_from_sources(seeded._conn)
        count_after_first = graph_edge_count(seeded._conn)
        second = project_graph_from_sources(seeded._conn)
        assert second.edges_projected == first.edges_projected
        assert second.edges_written == 0
        assert graph_edge_count(seeded._conn) == count_after_first

    def test_derived_rows_carry_provenance(self, seeded):
        project_graph_from_sources(seeded._conn)
        row = seeded._conn.execute(
            "SELECT relation_source, source_ref, projection_version, identity_version, "
            "provenance_hash, content_hash FROM zm_graph_edges LIMIT 1"
        ).fetchone()
        assert all(row[i] for i in range(6))
        assert row["projection_version"] == "m8.2"

    def test_no_time_invented_for_absent_validity(self, seeded):
        project_graph_from_sources(seeded._conn)
        rows = seeded._conn.execute(
            "SELECT valid_from, valid_until FROM zm_graph_edges"
        ).fetchall()
        assert all(r["valid_from"] is None and r["valid_until"] is None for r in rows)


class TestUnscopedDuplicateRegression:
    """The M8.1 NULL-safe uniqueness fix must remain protected."""

    def test_identical_unscoped_edges_do_not_duplicate(self, db):
        conn = db._conn
        _event(conn, "E1")  # no profile_id / project_id -> fully unscoped
        _event(conn, "E2", sequence=2)
        _relation(conn, "E2", "E1", "derived_from")
        conn.commit()
        project_graph_from_sources(conn)
        project_graph_from_sources(conn)
        rows = conn.execute(
            "SELECT profile_id, project_id, knowledge_space_id FROM zm_graph_edges"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["profile_id"] is None and rows[0]["project_id"] is None

    def test_empty_string_scope_is_not_stored_as_forgeable_sentinel(self, db):
        conn = db._conn
        _event(conn, "E1", project_id="")
        _event(conn, "E2", project_id="", sequence=2)
        _relation(conn, "E2", "E1", "derived_from")
        conn.commit()
        project_graph_from_sources(conn)
        row = conn.execute("SELECT project_id FROM zm_graph_edges").fetchone()
        # An empty source value is absence, normalized to NULL — never a
        # literal '' that could collide with the uniqueness encoding.
        assert row["project_id"] is None


class TestRebuild:
    def test_rebuild_publishes_index_version(self, seeded):
        report = rebuild_graph(seeded._conn)
        assert report.published is True
        rec = get_index_version(seeded._conn, GRAPH_INDEX_NAME)
        assert rec is not None and rec.build_status == BUILD_STATUS_PUBLISHED
        assert rec.canonical_fingerprint == report.canonical_fingerprint

    def test_clear_then_rebuild_reproduces_state(self, seeded):
        rebuild_graph(seeded._conn)
        before = derived_state_snapshot(seeded._conn)
        rebuild_graph(seeded._conn)
        assert derived_state_snapshot(seeded._conn) == before

    def test_rebuild_twice_is_idempotent_in_row_count(self, seeded):
        first = rebuild_graph(seeded._conn)
        second = rebuild_graph(seeded._conn)
        assert first.edges_written == second.edges_written
        assert graph_edge_count(seeded._conn) == first.edges_written

    def test_rebuild_from_empty_derived_state(self, seeded):
        rebuild_graph(seeded._conn)
        populated = derived_state_snapshot(seeded._conn)
        from src.m8.derived_index import clear_m8_derived_state

        clear_m8_derived_state(seeded._conn)
        assert m8_derived_state_is_empty(seeded._conn) is True
        rebuild_graph(seeded._conn)
        assert derived_state_snapshot(seeded._conn) == populated

    def test_two_independent_databases_agree(self, seeded, tmp_path):
        rebuild_graph(seeded._conn)
        snapshot_a = derived_state_snapshot(seeded._conn)

        other = SQLiteStore(SQLiteStoreConfig(path=tmp_path / "b.sqlite"))
        other.ensure_schema()
        try:
            conn = other._conn
            # Same logical sources, inserted in a DIFFERENT order.
            _event(conn, "E3", profile_id="prof-b", project_id="P2", sequence=3)
            _event(conn, "E1", profile_id="prof-a", project_id="P1")
            _event(conn, "E2", profile_id="prof-a", project_id="P1", sequence=2)
            _relation(conn, "E3", "E1", "supersedes")
            _relation(conn, "E2", "E1", "child_of")
            _relation(conn, "E2", "E1", "derived_from")
            conn.execute(
                "INSERT INTO zm_artifacts (artifact_id, content_hash, kind, retention, "
                "origin_event_id, stored_path, created_at) VALUES (?,?,?,?,?,?,?)",
                ("A1", "ch", "text", "persistent", "E1", None, TS),
            )
            conn.execute(
                "INSERT INTO zm_requirements (requirement_id, project_id, created_at, "
                "lifecycle_status) VALUES (?,?,?,?)",
                ("R1", "P1", TS, "superseded"),
            )
            conn.execute(
                "INSERT INTO zm_requirements (requirement_id, project_id, created_at, "
                "lifecycle_status, supersedes, profile_id) VALUES (?,?,?,?,?,?)",
                ("R2", "P1", TS, "candidate", "R1", "prof-a"),
            )
            conn.execute(
                "INSERT INTO zm_decisions (decision_id, project_id, lifecycle_status) "
                "VALUES (?,?,?)",
                ("D1", "P1", "superseded"),
            )
            conn.execute(
                "INSERT INTO zm_decisions (decision_id, project_id, lifecycle_status, "
                "linked_requirement_ids, supersedes_id, profile_id, trace_id) "
                "VALUES (?,?,?,?,?,?,?)",
                ("D2", "P1", "candidate", "R1,R2", "D1", "prof-a", "T-D2"),
            )
            conn.execute(
                "INSERT INTO zm_verifications (verification_id, subject_type, subject_id, "
                "project_id, verification_status) VALUES (?,?,?,?,?)",
                ("V2", "session", "S9", "P1", "deterministic_verification"),
            )
            conn.execute(
                "INSERT INTO zm_verifications (verification_id, subject_type, subject_id, "
                "project_id, verification_status) VALUES (?,?,?,?,?)",
                ("V1", "decision", "D2", "P1", "deterministic_verification"),
            )
            conn.execute(
                "INSERT INTO zm_project_artifacts (artifact_id, project_id, created_at, "
                "linked_decision_ids) VALUES (?,?,?,?)",
                ("A1", "P1", TS, "D2"),
            )
            conn.commit()
            rebuild_graph(conn)
            assert derived_state_snapshot(conn) == snapshot_a
        finally:
            other.close()

    def test_rebuild_does_not_modify_canonical_projections(self, seeded):
        conn = seeded._conn
        before = (
            conn.execute("SELECT COUNT(*) FROM zm_meta").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM zm_relations").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM zm_decisions").fetchone()[0],
        )
        rebuild_graph(conn)
        after = (
            conn.execute("SELECT COUNT(*) FROM zm_meta").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM zm_relations").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM zm_decisions").fetchone()[0],
        )
        assert before == after

    def test_rebuild_does_not_touch_canonical_jsonl(self, seeded, tmp_path):
        jsonl = tmp_path / "raw.jsonl"
        jsonl.write_text('{"event_id":"E1"}\n', encoding="utf-8")
        digest = jsonl.read_bytes()
        rebuild_graph(seeded._conn)
        assert jsonl.read_bytes() == digest

    def test_missing_timestamps_fail_closed(self, db):
        # No zm_meta rows -> no real source timestamp; the projector must NOT
        # substitute the wall clock.
        with pytest.raises(GraphPersistenceError):
            rebuild_graph(db._conn)

    def test_explicit_timestamps_accepted_when_no_source_time(self, db):
        report = rebuild_graph(db._conn, built_at=TS, source_cutoff=TS)
        assert report.published is True

    def test_fingerprint_tracks_source_state(self, seeded):
        first = rebuild_graph(seeded._conn).canonical_fingerprint
        _event(seeded._conn, "E9", sequence=9)
        seeded._conn.commit()
        second = rebuild_graph(seeded._conn).canonical_fingerprint
        assert first != second

    def test_source_descriptor_is_deterministic(self, seeded):
        assert compute_source_descriptor(seeded._conn) == compute_source_descriptor(
            seeded._conn
        )


class TestExplicitEntitiesAndMentions:
    def test_entities_and_mentions_persisted(self, seeded):
        entity = EntitySourceRecord(
            entity_type="person", canonical_name="Ada", relation_source="m4_project_link",
            source_ref="zm_decisions:D2", project_id="P1",
        )
        mention = MentionSourceRecord(
            entity=entity, source_event_id="E1", span_start=0, span_end=3,
            mention_text="Ada",
        )
        report = rebuild_graph(
            seeded._conn, entity_records=[entity], mention_records=[mention]
        )
        assert report.entities_written == 1
        assert report.mentions_written == 1

    def test_repeated_entity_is_not_duplicated(self, seeded):
        entity = EntitySourceRecord(
            entity_type="person", canonical_name="Ada", relation_source="m4_project_link",
            source_ref="zm_decisions:D2", project_id="P1",
        )
        rebuild_graph(seeded._conn, entity_records=[entity, entity])
        count = seeded._conn.execute("SELECT COUNT(*) FROM zm_entities").fetchone()[0]
        assert count == 1

    def test_mention_rows_store_no_raw_text(self, seeded):
        entity = EntitySourceRecord(
            entity_type="person", canonical_name="Ada", relation_source="m4_project_link",
            source_ref="zm_decisions:D2", project_id="P1",
        )
        mention = MentionSourceRecord(
            entity=entity, source_event_id="E1", mention_text="secret-span"
        )
        rebuild_graph(seeded._conn, entity_records=[entity], mention_records=[mention])
        rows = seeded._conn.execute("SELECT * FROM zm_entity_mentions").fetchall()
        assert rows and "secret-span" not in str(tuple(rows[0]))
