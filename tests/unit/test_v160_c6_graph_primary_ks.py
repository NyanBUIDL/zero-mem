"""V1.6.0 C6 RED-first tests for PRIMARY-KS graph projection.

Canonical events may belong to multiple Knowledge Spaces, but the frozen M8
graph/temporal contracts carry one scope coordinate.  Event-derived graph rows
therefore copy ``zm_meta.knowledge_space_id`` (PRIMARY-KS) and never expand the
junction into duplicate graph rows.
"""
from __future__ import annotations

from src.m8.graph_sources import read_m2_artifact_edges, read_m2_relation_edges
from src.m8.projection_store import project_graph_from_sources
from tests.unit.test_m8_2_rebuild import _event, _relation, db


def _seed_multi_ks(conn) -> None:
    _event(conn, "E1", profile_id="prof-a", project_id="P1")
    _event(conn, "E2", profile_id="prof-a", project_id="P1", sequence=2)
    conn.execute(
        "UPDATE zm_meta SET knowledge_space_id=? WHERE event_id=?", ("A", "E2")
    )
    conn.executemany(
        "INSERT INTO zm_event_spaces (event_id, knowledge_space_id) VALUES (?,?)",
        (("E2", "A"), ("E2", "B")),
    )
    _relation(conn, "E2", "E1", "derived_from")
    conn.execute(
        "INSERT INTO zm_artifacts (artifact_id, content_hash, kind, retention, "
        "origin_event_id, stored_path, created_at) VALUES (?,?,?,?,?,?,?)",
        ("ART-1", "hash", "text", "persistent", "E2", None,
         "2026-01-02T03:04:05+00:00"),
    )
    conn.commit()


def test_event_derived_sources_copy_primary_ks_only(db):
    _seed_multi_ks(db._conn)

    relation = read_m2_relation_edges(db._conn).edges[0]
    artifact = read_m2_artifact_edges(db._conn).edges[0]

    assert relation.knowledge_space_id == "A"
    assert artifact.knowledge_space_id == "A"


def test_graph_projection_does_not_expand_one_event_per_space(db):
    _seed_multi_ks(db._conn)

    report = project_graph_from_sources(db._conn)
    rows = db._conn.execute(
        "SELECT source_event_id, knowledge_space_id FROM zm_graph_edges "
        "WHERE source_event_id=? ORDER BY edge_id", ("E2",)
    ).fetchall()

    assert report.edges_projected == 2
    assert len(rows) == 2
    assert {row["knowledge_space_id"] for row in rows} == {"A"}


def test_missing_primary_ks_is_not_inferred_from_junction(db):
    _event(db._conn, "E1", profile_id="prof-a", project_id="P1")
    _event(db._conn, "E2", profile_id="prof-a", project_id="P1", sequence=2)
    db._conn.execute(
        "INSERT INTO zm_event_spaces (event_id, knowledge_space_id) VALUES (?,?)",
        ("E2", "B"),
    )
    _relation(db._conn, "E2", "E1", "derived_from")
    db._conn.commit()

    edge = read_m2_relation_edges(db._conn).edges[0]
    assert edge.knowledge_space_id is None
