"""RED-first — DEF-031 (DEF-C2, P2): corpus FTS AND-only misses multi-token
queries when a single token is absent; add precision-guarded OR fallback
(parity with the M3 event FTS path, src/retrieval/search.py V130-01).

Scenario: query "quantum thermodynamics" — AUTH_DOC contains "quantum" but not
"thermodynamics". AND-only discovery returns zero candidates -> absolute miss
(no ranking can save it). OR fallback (>=2 terms, AND returns 0) surfaces the
unit containing "quantum".

Expected post-fix: the OR fallback runs ONLY when the AND pass returned zero
rows AND the query has >= 2 terms; filters/authorization/pagination identical;
the FTS MATCH expression stays a bound parameter (no caller SQL injection).
"""
from __future__ import annotations

import pytest

from src.access.authorized_read import AuthorizedReadService
from src.access.contracts import AccessRequest
from tests.unit.test_m10_5_retrieval import AUTH_DOC, _project, _svc


class TestDef031CorpusOrFallback:
    def test_or_fallback_recovers_partial_token_match(self, tmp_path):
        ro = _project(tmp_path, [
            (AUTH_DOC, {"profile_id": "p1", "project_id": "P"}),
        ], tag="d31")
        svc = _svc(ro, profile="p1")
        try:
            req = AccessRequest(operation="READ", requesting_profile_id="p1",
                                target_profile_ids=["p1"],
                                project_ids=["P"], include_global=True,
                                resource_type="corpus_unit")
            res = svc.corpus_unit_search(req, "quantum thermodynamics")
            assert res.allowed
            assert len(res.items) >= 1, (
                "AND-only discovery misses a unit that matches the query's "
                "other tokens; OR fallback must recover it")
        finally:
            ro.close()

    def test_and_still_prefers_exact_all_token_match(self, tmp_path):
        """Units matching ALL tokens must still rank above OR-only matches."""
        import src.corpus.retrieval as cr
        ro = _project(tmp_path, [
            (AUTH_DOC, {"profile_id": "p1", "project_id": "P"}),  # quantum only
            (b"quantum thermodynamics theory of engines.\n",
             {"profile_id": "p1", "project_id": "P"}),            # both
        ], tag="d31b")
        svc = _svc(ro, profile="p1")
        try:
            req = AccessRequest(operation="READ", requesting_profile_id="p1",
                                target_profile_ids=["p1"],
                                project_ids=["P"], include_global=True,
                                resource_type="corpus_unit")
            res = svc.corpus_unit_search(req, "quantum thermodynamics")
            assert res.allowed
            assert len(res.items) >= 1
            # The exact AND match must be the top hit.
            top = res.items[0]
            assert "thermodynamics" in (top.normalized_text or "").lower(), (
                "exact all-token match must rank above OR-only partial match")
        finally:
            ro.close()

    def test_single_term_no_or_fallback(self, tmp_path):
        """Single-term query must not trigger OR (nothing to fall back to)."""
        from src.corpus.retrieval import _fts_safe_query
        expr = _fts_safe_query("quantum")
        assert " OR " not in expr, "single-term query must stay AND/plain"
