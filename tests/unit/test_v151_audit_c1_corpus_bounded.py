"""RED-first — DEF-030 (DEF-C1, P2): corpus FTS discovery unbounded +
metadata-only full-table scan.

Static evidence (src/corpus/retrieval.py):
  - FTS discovery: `SELECT ... FROM zm_corpus_fts JOIN zm_corpus_units ... WHERE MATCH ?`
    has NO LIMIT — every matching row materializes into Python before the
    authorization filter and ranking.
  - `_read_all_units`: `SELECT ... FROM zm_corpus_units` (no WHERE/LIMIT).
Auth stays fail-safe (filter before ranking) but broad queries can spike memory.

Post-fix contract: discovery SQL is bounded (LIMIT plan.limit x factor or
equivalent); metadata-only path bounded; single-page memory stays small.
"""
from __future__ import annotations

import tracemalloc

import pytest

from src.access.authorized_read import AuthorizedReadService
from src.access.contracts import AccessRequest
from src.corpus.query_planner import build_query_plan
from src.corpus.retrieval import AuthorizedCorpusScope, retrieve_corpus
from tests.unit.test_m10_5_retrieval import AUTH_DOC, _project


class _SpyCursor:
    def __init__(self, real, log):
        self._real = real
        self._log = log

    def execute(self, sql, params=None):
        self._log.append(str(sql))
        return self._real.execute(sql, params if params is not None else ())

    def __getattr__(self, name):
        return getattr(self._real, name)


class _SpyConn:
    """sqlite3.Connection.execute is read-only; wrap at cursor level."""

    def __init__(self, real):
        self._real = real
        self.log: list = []

    def cursor(self):
        return _SpyCursor(self._real.cursor(), self.log)


def _corpus_of_n(tmp_path, n: int):
    docs = [(AUTH_DOC, {"profile_id": "p1", "project_id": "P"}) for _ in range(n)]
    return _project(tmp_path, docs, tag="c1")


class TestDef030BoundedCorpusDiscovery:
    def test_fts_discovery_sql_has_limit(self, tmp_path):
        ro = _corpus_of_n(tmp_path, 20)
        spy = _SpyConn(ro.conn)
        plan = build_query_plan("quantum superposition", limit=5)
        scope = AuthorizedCorpusScope(allowed_scopes=(("p1", "P", None),))
        hits = retrieve_corpus(spy, scope, plan)
        assert len(hits) <= 5
        fts_sqls = [s for s in spy.log if "zm_corpus_fts" in s and "MATCH" in s]
        assert fts_sqls, "expected an FTS discovery query in the trace"
        for sql in fts_sqls:
            assert "LIMIT" in sql.upper(), (
                "FTS discovery must be bounded: " + sql)

    def test_metadata_only_path_bounded(self, tmp_path):
        ro = _corpus_of_n(tmp_path, 20)
        spy = _SpyConn(ro.conn)
        plan = build_query_plan("", limit=5)  # metadata-only
        scope = AuthorizedCorpusScope(allowed_scopes=(("p1", "P", None),))
        hits = retrieve_corpus(spy, scope, plan)
        assert len(hits) <= 5
        scan_sqls = [s for s in spy.log if "FROM zm_corpus_units" in s]
        assert scan_sqls, "expected a zm_corpus_units scan in the trace"
        for sql in scan_sqls:
            assert "LIMIT" in sql.upper(), (
                "metadata-only discovery must be bounded: " + sql)

    def test_memory_bounded_with_many_units(self, tmp_path):
        ro = _corpus_of_n(tmp_path, 100)
        svc = AuthorizedReadService(ro, "p1", grant_conn=ro.conn)
        try:
            tracemalloc.start()
            try:
                res = svc.corpus_unit_search(
                    AccessRequest(operation="READ", requesting_profile_id="p1",
                                  target_profile_ids=["p1"],
                                  project_ids=["P"], include_global=True,
                                  resource_type="corpus_unit"),
                    "quantum superposition", limit=5)
                assert res.allowed
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            assert peak < 8 * 1024 * 1024, f"peak={peak} bytes"
        finally:
            ro.close()
