"""DEF-076: the corpus discovery / neighbor SQL must keep index-driven plans (latency at scale)."""
from __future__ import annotations

import sqlite3

import pytest

from src.corpus import retrieval as R


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    try:
        c.execute("CREATE VIRTUAL TABLE f USING fts5(x)")
    except sqlite3.OperationalError:
        pytest.skip("FTS5 unavailable")
    c.execute("DROP TABLE f")
    c.executescript(
        """
        CREATE TABLE zm_corpus_sources (source_id TEXT PRIMARY KEY, external_ref TEXT, custom_meta TEXT);
        CREATE TABLE zm_corpus_units (
          unit_id TEXT PRIMARY KEY, source_ref TEXT, source_location_id TEXT, content_hash TEXT,
          normalized_text TEXT, kind TEXT, unit_order INTEGER, page INTEGER, profile_id TEXT, project_id TEXT,
          knowledge_space_id TEXT, duplicate_of TEXT, lifecycle_status TEXT, sensitivity TEXT);
        CREATE INDEX idx_u_source ON zm_corpus_units(source_ref);
        CREATE INDEX idx_u_dup ON zm_corpus_units(duplicate_of);
        CREATE INDEX idx_u_scope ON zm_corpus_units(profile_id, project_id, knowledge_space_id);
        CREATE VIRTUAL TABLE zm_corpus_fts USING fts5(unit_id UNINDEXED, content);
        """
    )
    for i in range(500):
        c.execute("INSERT INTO zm_corpus_sources VALUES (?,?,?)", (f"s{i // 10}", "r", "{}")) if i % 10 == 0 else None
        c.execute("INSERT INTO zm_corpus_units VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (f"u{i}", f"s{i // 10}", "l", "h", "alpha beta", "text", i % 10, None, "p", None, None, None, "active", "internal"))
        c.execute("INSERT INTO zm_corpus_fts (unit_id, content) VALUES (?,?)", (f"u{i}", "alpha beta"))
    c.execute("ANALYZE")
    yield c
    c.close()


def _plan(con, sql, params):
    return " | ".join(r[3] for r in con.execute("EXPLAIN QUERY PLAN " + sql, params))


def test_discovery_join_is_driven_by_matches_without_automatic_index(con):
    sql = R._fts_discovery_sql(2, "(u.profile_id = ?)", "1")
    plan = _plan(con, sql, ['"alpha"*', '"beta"*', "p", 500])
    assert "AUTOMATIC" not in plan
    assert "sqlite_autoindex_zm_corpus_units_1" in plan
    assert len(con.execute(sql, ['"alpha"*', '"beta"*', "p", 5]).fetchall()) == 5


def test_neighbor_lookup_uses_source_index_not_duplicate_scan(con):
    plan = _plan(con, R._neighbor_sql(2), ["s1", 3, "s2", 4])
    assert "idx_u_dup" not in plan
    assert "idx_u_source" in plan
