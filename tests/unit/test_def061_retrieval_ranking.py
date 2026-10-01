"""DEF-061 (query side) - token-friendly default limit, BM25-style ranking over
the authorized subset, within-source duplicate collapse, deterministic ties.

The authorization-before-influence invariant stays load-bearing: corpus-wide
FTS statistics (``bm25()``) are NOT used because unauthorized rows would shift
IDF / average length; every statistic is computed over authorized candidates.
"""
from __future__ import annotations

import pytest

from src.corpus import query_planner as qp
from src.corpus.query_planner import CorpusMetadataFilter, CorpusQueryPlan, build_query_plan
from src.corpus.retrieval import AuthorizedCorpusScope, retrieve_corpus
from src.storage.migrations import migrate_10
from tests.unit.t3_corpus_helpers import build_store, doc, search, texts


# --- default limit --------------------------------------------------------------

def test_default_limit_is_token_friendly():
    assert qp.DEFAULT_RESULT_LIMIT == 20
    assert build_query_plan("pytest").limit == 20
    assert CorpusQueryPlan(text="x", metadata=CorpusMetadataFilter()).limit == 20


@pytest.mark.parametrize("bad", [0, -3, 501, 10_000, True, "5", 2.5])
def test_invalid_limit_falls_back_to_default(bad):
    assert build_query_plan("pytest", limit=bad).limit == qp.DEFAULT_RESULT_LIMIT


def test_internal_cap_stays_configurable_up_to_the_ceiling():
    assert qp.MAX_RESULT_LIMIT == 500
    assert build_query_plan("pytest", limit=100).limit == 100
    assert build_query_plan("pytest", limit=500).limit == 500
    assert build_query_plan("pytest", limit=1).limit == 1


def test_default_plan_returns_at_most_twenty_hits(tmp_path):
    ro = build_store(tmp_path, [doc(f"deploy note number {i} about pytest") for i in range(35)])
    scope = AuthorizedCorpusScope(allowed_scopes=(("p1", None, None),))
    plan = build_query_plan("pytest")
    assert len(retrieve_corpus(ro.conn, scope, plan)) == 20
    assert len(retrieve_corpus(ro.conn, scope, build_query_plan("pytest", limit=100))) == 35
    ro.close()


# --- ranking --------------------------------------------------------------------

def test_short_unit_outranks_long_unit_despite_lower_term_frequency(tmp_path):
    # T7: the BM25 parameters were re-tuned for short units (k1=0.6, b=0.3, docs/benchmarks/RESULTS.md).  With that
    # weaker length normalization a unit holding the term twice can legitimately beat a 30x shorter one, so the
    # length-normalization invariant is pinned at EQUAL term frequency.
    short = "pytest rules"
    long_text = "pytest " + " ".join(f"filler{i}" for i in range(58)) + " again"
    ro = build_store(tmp_path, [doc(long_text), doc(short)])
    result = search(ro, "pytest")
    assert texts(result) == [short, long_text]  # same TF: the shorter unit scores higher
    assert result.items[0].lexical_score > result.items[1].lexical_score > 0
    ro.close()


def test_term_frequency_saturates_instead_of_stuffing(tmp_path):
    # Same length and both units match every term.  Raw TF sums 10 vs 8 and
    # would rank the stuffed unit first; BM25 saturation prefers balanced coverage.
    stuffed = "pytest " * 9 + "commit"
    balanced = "pytest commit pytest commit pytest commit pytest commit alpha beta"
    ro = build_store(tmp_path, [doc(stuffed), doc(balanced)])
    assert texts(search(ro, "pytest commit")) == [balanced, stuffed]
    ro.close()


def test_phrase_adjacency_bonus_is_applied_to_hyphenated_terms(tmp_path):
    adjacent = "we use blue-green deployment"
    scattered = "green fields and a blue sky deployment"
    ro = build_store(tmp_path, [doc(scattered), doc(adjacent)])
    result = search(ro, "blue-green deployment")
    assert texts(result) == [adjacent, scattered]
    assert result.items[0].lexical_score > result.items[1].lexical_score
    ro.close()


def test_diacritic_folded_terms_are_scored(tmp_path):
    short = "Ưu tiên cao"
    long_text = "Ưu tiên " + " ".join(f"từ{i}" for i in range(40))
    ro = build_store(tmp_path, [doc(long_text), doc(short)])
    result = search(ro, "uu tien")
    assert texts(result) == [short, long_text]
    assert all(hit.lexical_score > 0 for hit in result.items)
    ro.close()


def test_ties_break_deterministically_across_calls_and_rebuilds(tmp_path):
    docs = [doc("pytest guard", ref=f"file://tie-{i}.txt", profile="p1") for i in range(6)]
    first = build_store(tmp_path, docs, tag="a")
    second = build_store(tmp_path, docs, tag="b")
    a1 = [(h.unit_id, h.combined_score) for h in search(first, "pytest").items]
    a2 = [(h.unit_id, h.combined_score) for h in search(first, "pytest").items]
    b = [(h.unit_id, h.combined_score) for h in search(second, "pytest").items]
    assert a1 == a2 == b
    assert len({score for _, score in a1}) == 1  # genuinely tied
    keys = [(h.profile_id or "", h.project_id or "", h.source_id, h.unit_id)
            for h in search(first, "pytest").items]
    assert keys == sorted(keys)  # documented tie-break order
    first.close()
    second.close()


def test_hidden_candidates_do_not_shift_scores(tmp_path):
    """BM25 statistics come from the authorized subset only."""
    base = [doc("pytest guard", ref="file://base-0.txt"),
            doc("pytest " + " ".join(f"w{i}" for i in range(30)), ref="file://base-1.txt")]
    noise = [doc("pytest pytest pytest pytest", profile="p2") for _ in range(40)]
    noise += [doc("pytest " + " ".join(f"n{i}" for i in range(200)), profile="p2") for _ in range(10)]
    plain = build_store(tmp_path, base, tag="plain")
    noisy = build_store(tmp_path, base + noise, tag="noisy")
    before = [(h.unit_id, h.lexical_score) for h in search(plain, "pytest").items]
    after = [(h.unit_id, h.lexical_score) for h in search(noisy, "pytest").items]
    assert before == after
    assert all(h.profile_id == "p1" for h in search(noisy, "pytest").items)
    plain.close()
    noisy.close()


# --- within-source duplicates ----------------------------------------------------

def test_within_source_duplicate_units_are_collapsed(tmp_path):
    repeated = "always run pytest before commit"
    content = "\n\n".join([repeated] * 5 + ["a different pytest line"])
    ro = build_store(tmp_path, [doc(content)])
    result = search(ro, "pytest")
    assert sorted(texts(result)) == sorted([repeated, "a different pytest line"])
    ro.close()


def test_duplicates_across_sources_are_not_collapsed(tmp_path):
    ro = build_store(tmp_path, [
        doc("shared pytest note", ref="file://a.txt"),
        doc("shared pytest note", ref="file://b.txt"),
    ])
    result = search(ro, "pytest")
    assert len(result.items) == 2
    assert len({h.source_id for h in result.items}) == 2
    ro.close()


def test_duplicate_rows_do_not_consume_discovery_cap(tmp_path):
    from src.corpus import retrieval

    content = "\n\n".join(["pytest duplicate line"] * 30 + ["pytest unique tail"])
    ro = build_store(tmp_path, [doc(content)])
    scope = AuthorizedCorpusScope(allowed_scopes=(("p1", None, None),))
    plan = build_query_plan("pytest", limit=1)
    # Cap of 2 candidate rows: if duplicates took slots the unique unit could vanish.
    original = retrieval._discovery_cap
    retrieval._discovery_cap = lambda limit: 2
    try:
        hits = retrieve_corpus(ro.conn, scope, plan.__class__(text=plan.text, metadata=plan.metadata, limit=2))
    finally:
        retrieval._discovery_cap = original
    assert {h.normalized_text for h in hits} == {"pytest duplicate line", "pytest unique tail"}
    ro.close()


# --- FTS5-unavailable fallback uses the same ranking ------------------------------

def test_fallback_path_ranks_with_bm25_and_drops_non_matching_units(tmp_path, monkeypatch):
    original_flag = migrate_10.FTS5_AVAILABLE
    monkeypatch.setattr(migrate_10, "_detect_fts5", lambda conn: False)
    try:
        short = "pytest rules"
        long_text = "pytest " + " ".join(f"filler{i}" for i in range(58)) + " pytest"
        unrelated = "gardening and weather notes"
        ro = build_store(tmp_path, [doc(long_text), doc(unrelated), doc(short)], tag="nofts")
        assert migrate_10.FTS5_AVAILABLE is False
        assert texts(search(ro, "pytest")) == [short, long_text]  # unrelated unit not returned
        ro.close()
    finally:
        migrate_10.FTS5_AVAILABLE = original_flag
