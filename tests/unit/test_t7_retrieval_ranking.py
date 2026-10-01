"""T7 - ranking quality of ``src/corpus/retrieval.py`` (each behaviour is backed by a measured benchmark delta).

See ``docs/benchmarks/RESULTS.md`` for the numbers behind: OR discovery with BM25 (instead of AND-first), the
short-text BM25 parameters, English stemming, the coordination factor and neighbor propagation.
"""
from __future__ import annotations

import pytest

from src.corpus import retrieval as retrieval_mod
from tests.unit.t3_corpus_helpers import build_store, doc, search, texts


def _store(tmp_path, docs):
    return build_store(tmp_path, docs)


# ----------------------------------------------------------------------------- OR discovery
def test_a_unit_matching_only_some_terms_is_found_even_when_another_unit_matches_all(tmp_path):
    ro = _store(tmp_path, [doc("quantum thermodynamics of engines"), doc("quantum computing hardware overview")])
    try:
        found = texts(search(ro, "quantum thermodynamics", limit=10))
        assert found[0] == "quantum thermodynamics of engines"
        assert "quantum computing hardware overview" in found  # AND-first would have hidden it
    finally:
        ro.close()


def test_discovery_without_any_authorized_match_is_empty(tmp_path):
    ro = _store(tmp_path, [doc("completely unrelated sentence"), doc("mine only", profile="other")])
    try:
        assert texts(search(ro, "quantum thermodynamics")) == []
    finally:
        ro.close()


# ----------------------------------------------------------------------------- stemming
@pytest.mark.parametrize("query,text", [
    ("adopted", "We are adopting two cats this spring"),
    ("adopting", "She adopted a dog last year"),
    ("adopt", "Adoption papers were signed yesterday"),
    ("living", "I live near the harbour"),
    ("studies", "He is studying biology and I study law"),
    ("teaching", "She teaches maths at the local school"),
    ("running", "She runs every morning"),
    ("painted", "Paintings of the lake are on sale"),
])
def test_inflected_query_terms_match_other_forms_of_the_word(tmp_path, query, text):
    ro = _store(tmp_path, [doc(text), doc("an unrelated line about nothing")])
    try:
        assert texts(search(ro, query)) == [text]
    finally:
        ro.close()


def test_stemming_does_not_match_words_that_only_share_a_prefix(tmp_path):
    ro = _store(tmp_path, [doc("adaptive learning rate schedules"), doc("a student of history")])
    try:
        assert texts(search(ro, "adopted")) == []
        assert texts(search(ro, "studies")) == []  # discovered by the shared root, rejected by the stem comparison
    finally:
        ro.close()


def test_short_terms_keep_prefix_matching(tmp_path):
    ro = _store(tmp_path, [doc("the dog barked at midnight"), doc("a dogged determination")])
    try:
        assert sorted(texts(search(ro, "dog"))) == ["a dogged determination", "the dog barked at midnight"]
    finally:
        ro.close()


def test_diacritics_are_still_folded_when_stemming(tmp_path):
    ro = _store(tmp_path, [doc("Nguyễn Văn Đạt đang học tiếng Việt"), doc("an unrelated english line")])
    try:
        assert texts(search(ro, "dat hoc")) == ["Nguyễn Văn Đạt đang học tiếng Việt"]
    finally:
        ro.close()


# ----------------------------------------------------------------------------- coordination
def test_partial_matches_are_scaled_by_the_fraction_of_query_terms_they_contain(tmp_path, monkeypatch):
    ro = _store(tmp_path, [doc("alpha beta gamma"), doc("alpha delta epsilon"), doc("zeta eta theta")])
    try:
        monkeypatch.setattr(retrieval_mod, "_COORD_EXPONENT", 0.0)
        plain = {h.normalized_text: h.lexical_score for h in search(ro, "alpha beta", limit=10).items}
        monkeypatch.setattr(retrieval_mod, "_COORD_EXPONENT", 1.0)
        scaled = {h.normalized_text: h.lexical_score for h in search(ro, "alpha beta", limit=10).items}
        assert scaled["alpha beta gamma"] == pytest.approx(plain["alpha beta gamma"])  # all terms: unchanged
        assert scaled["alpha delta epsilon"] == pytest.approx(plain["alpha delta epsilon"] * 0.5, rel=1e-4)
    finally:
        ro.close()


def test_a_single_term_query_is_never_scaled(tmp_path, monkeypatch):
    ro = _store(tmp_path, [doc("alpha beta gamma")])
    try:
        monkeypatch.setattr(retrieval_mod, "_COORD_EXPONENT", 0.0)
        plain = search(ro, "alpha").items[0].lexical_score
        monkeypatch.setattr(retrieval_mod, "_COORD_EXPONENT", 3.0)
        assert search(ro, "alpha").items[0].lexical_score == pytest.approx(plain)
    finally:
        ro.close()


# ----------------------------------------------------------------------------- neighbor propagation
def _session(*turns):
    return doc("\n\n".join(turns), ref="file://session-a.txt")


def test_neighbors_of_a_strong_hit_are_returned_with_a_fraction_of_its_score(tmp_path):
    session = _session("Mel: What do you love most about camping with the family?",
                       "Caroline: It is a chance to be present and together, we bond over stories.",
                       "Mel: That sounds wonderful, thanks for sharing!")
    ro = _store(tmp_path, [session, doc("unrelated notes about taxes", ref="file://other.txt")])
    try:
        items = search(ro, "camping family", limit=10).items
        by_text = {h.normalized_text: h for h in items}
        question = by_text["Mel: What do you love most about camping with the family?"]
        answer = by_text["Caroline: It is a chance to be present and together, we bond over stories."]
        assert question.lexical_score > 0
        assert answer.lexical_score == pytest.approx(retrieval_mod._NEIGHBOR_ALPHA * question.lexical_score, rel=1e-4)
        assert items[0] is question and items[1] is answer
        assert "unrelated notes about taxes" not in by_text
    finally:
        ro.close()


def test_neighbors_reach_two_units_but_not_three(tmp_path):
    turns = ["quokka sighting at dawn"] + [f"filler line number {i}" for i in range(1, 5)]
    ro = _store(tmp_path, [_session(*turns)])
    try:
        found = texts(search(ro, "quokka", limit=10))
        assert found[:3] == ["quokka sighting at dawn", "filler line number 1", "filler line number 2"]
        assert "filler line number 3" not in found
    finally:
        ro.close()


def test_neighbors_never_cross_a_source_boundary(tmp_path):
    first = doc("quokka sighting", ref="file://one.txt")
    second = doc("neighboring source text", ref="file://two.txt")
    ro = _store(tmp_path, [first, second])
    try:
        assert texts(search(ro, "quokka", limit=10)) == ["quokka sighting"]
    finally:
        ro.close()


def test_a_neighbor_that_completes_the_question_is_boosted_by_its_strong_neighbor(tmp_path):
    # query "alpha beta": unit 2 holds only "beta", its neighbor unit 1 holds "alpha" strongly -> adjacency completes the
    # question and lifts unit 2 above an otherwise identical unit of another source.
    ro = _store(tmp_path, [_session("alpha alpha alpha facts here", "a short beta remark", "something else entirely"),
                           doc("a short beta remark", ref="file://solo.txt")])
    try:
        found = [(h.normalized_text, h.source_id) for h in search(ro, "alpha beta", limit=10).items]
        beta_units = [source for text, source in found if text == "a short beta remark"]
        assert len(beta_units) == 2
        scores = {h.source_id: h.lexical_score for h in search(ro, "alpha beta", limit=10).items
                  if h.normalized_text == "a short beta remark"}
        assert max(scores.values()) > min(scores.values())
        winner = max(scores, key=scores.get)
        session_source = next(h.source_id for h in search(ro, "alpha beta", limit=10).items
                              if h.normalized_text.startswith("alpha alpha"))
        assert winner == session_source
    finally:
        ro.close()


def test_adjacent_units_that_hold_the_same_words_do_not_lift_each_other(tmp_path):
    # A run of rows that all contain "alpha" must not outrank an isolated unit that is the better match: only a
    # neighbor that brings query terms the unit lacks counts as context.
    rows = ["alpha row one", "alpha row two", "alpha row three", "alpha row four"]
    ro = _store(tmp_path, [doc("\n\n".join(rows), ref="file://table.txt"),
                           doc("alpha alpha", ref="file://isolated.txt")])
    try:
        assert texts(search(ro, "alpha", limit=10))[0] == "alpha alpha"
        plain = {h.normalized_text: h.lexical_score for h in search(ro, "alpha", limit=10).items}
        assert len({round(plain[row], 6) for row in rows}) <= 2  # no cluster reinforcement spread across the rows
    finally:
        ro.close()


def test_neighbor_expansion_respects_the_metadata_filter_and_the_limit(tmp_path):
    session = doc("\n\n".join(["quokka heading text", "plain neighbor line", "another neighbor line"]),
                  ref="file://m.txt", meta={"memory_type": "fact"})
    other = doc("quokka persona facet", ref="mem://persona/x", meta={"memory_type": "persona"})
    ro = _store(tmp_path, [session, other])
    try:
        persona = search(ro, "quokka", limit=10, metadata={"memory_type": "persona"})
        assert texts(persona) == ["quokka persona facet"]
        assert len(search(ro, "quokka", limit=2).items) == 2
    finally:
        ro.close()


def test_single_unit_sources_and_metadata_only_queries_are_unaffected(tmp_path):
    ro = _store(tmp_path, [doc("alpha one"), doc("alpha two"), doc("beta three")])
    try:
        assert sorted(texts(search(ro, "alpha"))) == ["alpha one", "alpha two"]
        assert len(search(ro, "", limit=10).items) == 3
    finally:
        ro.close()


def test_a_neighbor_in_another_profiles_source_is_unreachable(tmp_path):
    mine = doc("quokka note for me", ref="file://mine.txt", profile="me")
    theirs = _session("quokka hidden diary entry", "very private neighbor text")
    theirs["profile"] = "other"
    ro = _store(tmp_path, [mine, theirs])
    try:
        assert texts(search(ro, "quokka", profile="me", limit=10)) == ["quokka note for me"]
    finally:
        ro.close()


# ----------------------------------------------------------------------------- determinism
def test_ranking_is_identical_across_calls_and_cache_states(tmp_path):
    ro = _store(tmp_path, [_session("quokka camping trip", "we packed the tent", "and lots of snacks"),
                           doc("camping in the rain is fun", ref="file://b.txt")])
    try:
        first = [(h.normalized_text, h.lexical_score) for h in search(ro, "camping quokka", limit=10).items]
        retrieval_mod._doc_terms.cache_clear()
        second = [(h.normalized_text, h.lexical_score) for h in search(ro, "camping quokka", limit=10).items]
        assert first == second
    finally:
        ro.close()


# ----------------------------------------------------------------------------- bounded candidate set
@pytest.fixture
def small_candidate_limit(monkeypatch):
    monkeypatch.setattr(retrieval_mod, "_CANDIDATE_LIMIT", 5)


def test_units_covering_more_query_terms_survive_the_candidate_limit(tmp_path, small_candidate_limit):
    # 30 single-term matches registered BEFORE the one unit that holds both terms: rowid-order truncation would drop it.
    docs = [doc(f"alpha filler number {i}", ref=f"file://a{i:02d}.txt") for i in range(30)]
    docs.append(doc("alpha and beta together", ref="file://zz-both.txt"))
    ro = _store(tmp_path, docs)
    try:
        found = texts(search(ro, "alpha beta", limit=3))
        assert found[0] == "alpha and beta together"
    finally:
        ro.close()


def test_the_candidate_limit_is_deterministic_and_never_counts_hidden_rows(tmp_path, small_candidate_limit):
    visible = [doc(f"alpha note {i}", ref=f"file://v{i}.txt", profile="me") for i in range(12)]
    visible.append(doc("alpha beta gamma", ref="file://v-best.txt", profile="me"))
    hidden = [doc(f"alpha beta gamma delta {i}", ref=f"file://h{i}.txt", profile="other") for i in range(40)]
    clean = _store(tmp_path, visible)
    noisy = _store(tmp_path, hidden + visible)
    try:
        first = [(h.normalized_text, h.lexical_score) for h in search(clean, "alpha beta", profile="me", limit=4).items]
        second = [(h.normalized_text, h.lexical_score) for h in search(noisy, "alpha beta", profile="me", limit=4).items]
        assert first == second and first[0][0] == "alpha beta gamma"
    finally:
        clean.close()
        noisy.close()


def test_a_single_term_query_over_many_units_returns_a_stable_window(tmp_path, small_candidate_limit):
    ro = _store(tmp_path, [doc(f"quokka entry {i}", ref=f"file://q{i:02d}.txt") for i in range(20)])
    try:
        a = texts(search(ro, "quokka", limit=10))
        b = texts(search(ro, "quokka", limit=10))
        assert a == b and len(a) == 5  # at most _CANDIDATE_LIMIT units are scored
    finally:
        ro.close()
