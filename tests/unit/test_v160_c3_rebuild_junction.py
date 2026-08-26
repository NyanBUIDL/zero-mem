"""V1.6.0 C3 RED-first — junction rebuild from canonical (ADR-V160-01 sec4).

rebuild_from_jsonl must re-derive the zm_event_spaces junction from canonical
JSONL exactly like a fresh ingest: stale junction rows from a previous derived
state must NOT survive a rebuild (the junction is derived, not canonical).

RED on current tree: DERIVED_TABLES does not include zm_event_spaces, so the
junction table survives the rebuild drop and stale rows persist
(ON CONFLICT DO NOTHING silently keeps them).
"""
from __future__ import annotations

import inspect

import pytest

from src.storage import ingest as ingest_mod
from src.storage.ingest import ingest_file, rebuild_from_jsonl
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from tests.unit.test_m3_query import (
    _checkpoint_and_close,
    _make_env,
    _open_store,
    _write_jsonl,
)


def _junction(store):
    cur = store._conn.execute(
        "SELECT event_id, knowledge_space_id FROM zm_event_spaces "
        "ORDER BY event_id, knowledge_space_id")
    return [dict(r) for r in cur.fetchall()]


def _meta_ks(store, event_id):
    cur = store._conn.execute(
        "SELECT knowledge_space_id FROM zm_meta WHERE event_id=?", (event_id,))
    row = cur.fetchone()
    return row["knowledge_space_id"] if row else None


class TestC3RebuildJunction:
    def test_rebuild_replaces_stale_junction_from_canonical(self, tmp_path):
        """Behavioral: rebuild must re-derive the junction from canonical.

        Ingest ev1 in [A]; then rebuild from a canonical where ev1 is in [B].
        The junction after rebuild must be exactly {ev1: B} — the stale ev1/A
        row from the previous derived state must not survive (current RED:
        zm_event_spaces is not in DERIVED_TABLES, so it survives the drop).
        """
        jl1 = tmp_path / "v1.jsonl"
        _write_jsonl(jl1, [
            _make_env("ev1", profile_id="p1", project_id="P",
                      knowledge_space_ids=["A"]),
        ])
        store = _open_store(tmp_path, "r.sqlite")
        ingest_file(store, jl1)
        assert _junction(store) == [
            {"event_id": "ev1", "knowledge_space_id": "A"}]
        jl2 = tmp_path / "v2.jsonl"
        _write_jsonl(jl2, [
            _make_env("ev1", profile_id="p1", project_id="P",
                      knowledge_space_ids=["B"]),
        ])
        rebuild_from_jsonl(store, [jl2])
        assert _junction(store) == [
            {"event_id": "ev1", "knowledge_space_id": "B"},
        ], "rebuild must drop stale junction rows and re-derive from canonical"
        assert _meta_ks(store, "ev1") == "B", "PRIMARY-KS must follow canonical"
        _checkpoint_and_close(store)

    def test_rebuild_junction_matches_fresh_ingest(self, tmp_path):
        """Behavioral parity: rebuild from the SAME canonical reproduces the
        junction exactly (multi-KS, legacy singular, and unscoped shapes)."""
        items = [
            _make_env("ev1", profile_id="p1", project_id="P",
                      knowledge_space_ids=["B", "A"]),
            _make_env("ev2", profile_id="p1", project_id="P",
                      knowledge_space_id="legacy-ks"),
            _make_env("ev3", profile_id="p1", project_id="P"),
        ]
        jl = tmp_path / "c.jsonl"
        _write_jsonl(jl, items)
        store = _open_store(tmp_path, "f.sqlite")
        ingest_file(store, jl)
        before = _junction(store)
        rebuild_from_jsonl(store, [jl])
        after = _junction(store)
        assert before == after == [
            {"event_id": "ev1", "knowledge_space_id": "A"},
            {"event_id": "ev1", "knowledge_space_id": "B"},
            {"event_id": "ev2", "knowledge_space_id": "legacy-ks"},
        ]
        assert _meta_ks(store, "ev1") == "B", "PRIMARY-KS = first of canonical list"
        assert _meta_ks(store, "ev2") == "legacy-ks"
        assert _meta_ks(store, "ev3") is None
        _checkpoint_and_close(store)

    def test_rebuild_drops_junction_via_derived_tables(self):
        """Static guard (repo convention): the junction MUST be in
        DERIVED_TABLES so rebuild_from_jsonl drops it and re-derives from
        canonical (never backfills from the stale derived column)."""
        assert "zm_event_spaces" in ingest_mod.DERIVED_TABLES, (
            "zm_event_spaces must be a derived, rebuildable table "
            "(plan C3; ADR-V160-01 sec4)")
        src = inspect.getsource(ingest_mod.rebuild_from_jsonl)
        assert "DERIVED_TABLES" in src
