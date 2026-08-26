"""DEF-034 downstream surface probes — list_knowledge_space / M8 graph / projection.

These began as evidence probes for the review finding that KS loss reached
multiple downstream surfaces.  V1.6 turns each probe into a regression gate:
  - C7 list_knowledge_space reads explicit junction membership;
  - C6 M8 event-derived graph sources copy PRIMARY-KS;
  - C8 still owns Obsidian projection knowledge_spaces.

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
    def test_list_knowledge_space_reads_explicit_membership(self, tmp_path):
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
            assert [item.event_id for item in res.items] == ["ev-ks"]
            assert res.total == 1
        finally:
            ro.close()

    def test_m8_graph_event_sources_read_primary_ks(self):
        import inspect
        from src.m8 import graph_sources as gs
        src = inspect.getsource(gs)
        assert "m.knowledge_space_id AS knowledge_space_id" in src
        assert '"knowledge_space_id": _get(row, "knowledge_space_id")' in src

    def test_projection_renders_explicit_knowledge_spaces(self):
        import inspect
        from src.projection import render as pr
        rsrc = inspect.getsource(pr)
        assert '"knowledge_spaces": list(knowledge_spaces)' in rsrc
        assert "_knowledge_spaces" in rsrc
