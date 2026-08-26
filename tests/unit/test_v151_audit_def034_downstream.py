"""DEF-034 downstream surface probes — list_knowledge_space / M8 graph / projection.

These assert CURRENT behavior (evidence for the review finding that KS loss is
NOT the only gap — several downstream surfaces never carry KS by design):
  - list_knowledge_space returns empty even when zm_meta has ks rows;
  - M8 graph event-derived sources assign knowledge_space_id=None;
  - Obsidian projection renders knowledge_spaces: [] (hardcoded).

NOT fixes: they pin the current state so V1.6.0 parity gates can assert change.
"""
from __future__ import annotations

import sqlite3

import pytest

from src.retrieval.relations import list_knowledge_space
from src.retrieval.db import open_readonly
from src.storage.ingest import ingest_file
from tests.unit.test_m3_query import (
    _checkpoint_and_close,
    _make_env,
    _open_store,
    _write_jsonl,
)


class TestDef034DownstreamSurfaces:
    def test_list_knowledge_space_empty_despite_ks_rows(self, tmp_path):
        jl = tmp_path / "k.jsonl"
        _write_jsonl(jl, [
            _make_env("ev-ks", profile_id="p1", project_id="P",
                      knowledge_space_id="quant-theory"),
        ])
        store = _open_store(tmp_path, "m.sqlite")
        ingest_file(store, jl)
        _checkpoint_and_close(store)
        ro = open_readonly(tmp_path / "m.sqlite")
        try:
            res = list_knowledge_space(ro, "quant-theory")
            # Schema-truthful: no event-level linkage column in the relations
            # layer -> the API returns [] by design (evidence, not fix).
            assert len(res.items) == 0
            assert res.total == 0
        finally:
            ro.close()

    def test_m8_graph_event_sources_assign_ks_none(self):
        import inspect
        from src.m8 import graph_sources as gs
        src = inspect.getsource(gs)
        assert src.count("knowledge_space_id=None") >= 4, (
            "M8 event-derived node constructors drop ks (evidence, not fix)")

    def test_projection_renders_knowledge_spaces_empty(self):
        import inspect
        from src.projection import render as pr
        rsrc = inspect.getsource(pr)
        assert '"knowledge_spaces": []' in rsrc, (
            "Obsidian projection hardcodes empty knowledge_spaces (evidence)")
