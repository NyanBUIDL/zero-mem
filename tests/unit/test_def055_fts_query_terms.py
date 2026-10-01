"""DEF-055 - hyphen / punctuation queries must split into separate FTS terms.

``blue-green`` and ``pre-commit`` used to become ``bluegreen`` / ``precommit``
(0 hits), ``C++`` became the prefix ``c*``.  Vietnamese diacritic handling must
keep working.
"""
from __future__ import annotations

import sqlite3
import unicodedata

import pytest

from src.corpus.retrieval import _fts_or_query, _fts_safe_query, _fts_term_count
from tests.unit.t3_corpus_helpers import build_store, doc, search, texts


# --- query builder ------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("blue-green", '"blue"* "green"*'),
    ("pre-commit", '"pre"* "commit"*'),
    ("foo_bar", '"foo"* "bar"*'),
    ("config.yaml", '"config"* "yaml"*'),
    ("node.js/express", '"node"* "js"* "express"*'),
    ("quantum (collapse)", '"quantum"* "collapse"*'),   # pre-existing contract
    ("quantum collapse", '"quantum"* "collapse"*'),     # pre-existing contract
])
def test_query_builder_splits_on_non_word_characters(raw, expected):
    assert _fts_safe_query(raw) == expected


def test_single_character_term_is_exact_not_prefix():
    # "C++" must not become the prefix c* (matches every word starting with c).
    assert _fts_safe_query("c++") == '"c"'
    assert _fts_safe_query("c++ templates") == '"c" "templates"*'


def test_punctuation_only_query_has_no_lexical_constraint():
    assert _fts_safe_query("---") == ""
    assert _fts_safe_query("++ ?? --") == ""


def test_operator_characters_cannot_inject_fts_syntax():
    built = _fts_safe_query('a" OR "b* NEAR(x) ^y')
    # Every term is individually quoted; no bare operator or unbalanced quote.
    assert built.count('"') % 2 == 0
    assert "NEAR(" not in built and "(" not in built and "^" not in built
    # And SQLite accepts the expression.
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE t USING fts5(content)")
    conn.execute("SELECT * FROM t WHERE t MATCH ?", (built,)).fetchall()


def test_or_query_and_term_count_use_split_terms():
    assert _fts_or_query("blue-green rollout") == '"blue"* OR "green"* OR "rollout"*'
    assert _fts_term_count("blue-green rollout") == 3
    assert _fts_term_count("---") == 0


def test_query_text_is_nfc_normalized():
    from src.corpus.query_planner import normalize_query_text

    decomposed = unicodedata.normalize("NFD", "Tiếng Việt")
    assert decomposed != "Tiếng Việt"
    assert normalize_query_text(decomposed) == "tiếng việt"


# --- end to end through the authorized facade ---------------------------------

def _ro(tmp_path, *texts_, **kw):
    return build_store(tmp_path, [doc(t, **kw) for t in texts_])


def test_hyphenated_term_matches(tmp_path):
    ro = _ro(tmp_path, "We ship with a blue-green deployment strategy.",
             "Completely unrelated gardening note.")
    assert texts(search(ro, "blue-green")) == ["We ship with a blue-green deployment strategy."]
    ro.close()


def test_pre_commit_matches(tmp_path):
    ro = _ro(tmp_path, "Run pre-commit before every push.", "Another unrelated line.")
    assert texts(search(ro, "pre-commit")) == ["Run pre-commit before every push."]
    ro.close()


def test_cpp_does_not_become_a_c_prefix(tmp_path):
    ro = _ro(tmp_path, "I write C++ and Rust daily.", "Code classes and compilers.")
    assert texts(search(ro, "C++")) == ["I write C++ and Rust daily."]
    ro.close()


def test_underscore_and_dotted_names_match(tmp_path):
    ro = _ro(tmp_path, "Call foo_bar() before deploy.", "Edit config.yaml and restart.",
             "Nothing relevant here.")
    assert texts(search(ro, "foo_bar")) == ["Call foo_bar() before deploy."]
    assert texts(search(ro, "config.yaml")) == ["Edit config.yaml and restart."]
    ro.close()


def test_hyphen_in_multi_term_query_is_not_hidden_by_or_fallback(tmp_path):
    """Old behaviour: ``bluegreen`` AND-match failed, the OR fallback then
    returned the unrelated 'rollout' unit and hid the real miss.

    T7: discovery is a single OR query ranked by BM25, so a partial match is no longer hidden when a full match
    exists; it must rank BELOW the unit that holds every word of the query.
    """
    both = "blue-green rollout plan for the api"
    only_rollout = "monthly rollout report"
    ro = _ro(tmp_path, both, only_rollout)
    found = texts(search(ro, "blue-green rollout"))
    assert found == [both, only_rollout]
    ro.close()


def test_adjacent_hyphenated_phrase_outranks_scattered_terms(tmp_path):
    adjacent = "we use blue-green deployment"
    scattered = "green fields and a blue sky deployment"
    ro = _ro(tmp_path, scattered, adjacent)
    assert texts(search(ro, "blue-green deployment")) == [adjacent, scattered]
    ro.close()


# --- Vietnamese diacritics ----------------------------------------------------

VI_DOC = "Triển khai ứng dụng bằng blue-green"


def test_vietnamese_query_with_diacritics_matches(tmp_path):
    ro = _ro(tmp_path, VI_DOC, "Chuyện khác hoàn toàn.")
    assert texts(search(ro, "triển khai")) == [VI_DOC]
    assert texts(search(ro, "TRIỂN KHAI")) == [VI_DOC]
    ro.close()


def test_vietnamese_decomposed_query_matches_composed_text(tmp_path):
    # Single term: no OR fallback can mask a missed match.
    ro = _ro(tmp_path, VI_DOC, "Chuyện khác hoàn toàn.")
    decomposed = unicodedata.normalize("NFD", "triển")
    assert decomposed != "triển"
    assert texts(search(ro, decomposed)) == [VI_DOC]
    ro.close()


def test_vietnamese_sqlite_foldable_diacritics_still_match_unaccented_query(tmp_path):
    ro = _ro(tmp_path, "Ưu tiên cho phiên bản mới")
    assert texts(search(ro, "uu tien")) == ["Ưu tiên cho phiên bản mới"]
    ro.close()


def test_vietnamese_with_hyphen_splits_and_matches(tmp_path):
    ro = _ro(tmp_path, "tái triển khai dịch vụ")
    assert texts(search(ro, "tái-triển-khai")) == ["tái triển khai dịch vụ"]
    ro.close()
