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


def test_a_neighbor_that_matches_the_query_is_boosted_by_its_strong_neighbor(tmp_path):
    ro = _store(tmp_path, [_session("quokka quokka quokka facts", "a short quokka remark", "something else entirely"),
                           doc("one more quokka remark of the same length", ref="file://solo.txt")])
    try:
        ranked = texts(search(ro, "quokka", limit=10))
        assert ranked.index("a short quokka remark") < ranked.index("one more quokka remark of the same length")
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
