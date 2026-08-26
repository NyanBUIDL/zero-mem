"""V1.6.0 C9 gates: corpus scope intentionally remains singular."""
from __future__ import annotations

import pytest

from src.corpus.contracts import CorpusSourceRecord, ValidationError
from tests.unit.test_m8_2_rebuild import db


def _record(**extra):
    values = dict(
        source_id="S1",
        content_hash="hash",
        external_ref="ref",
        kind="text",
        created_at="2026-08-27T00:00:00Z",
    )
    values.update(extra)
    return CorpusSourceRecord(**values)


def test_corpus_source_rejects_multi_ks_list():
    with pytest.raises(ValidationError):
        _record(knowledge_space_id=["A", "B"])


def test_corpus_source_accepts_one_space_or_unscoped():
    assert _record(knowledge_space_id="A").knowledge_space_id == "A"
    assert _record().knowledge_space_id is None


def test_corpus_units_schema_stays_singular_without_junction(db):
    columns = {
        row["name"]: row["type"]
        for row in db._conn.execute("PRAGMA table_info(zm_corpus_units)").fetchall()
    }
    assert columns["knowledge_space_id"] == "TEXT"
    assert "knowledge_space_ids" not in columns
    assert db._conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='zm_corpus_unit_spaces'"
    ).fetchone() is None
