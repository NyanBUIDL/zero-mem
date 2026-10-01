"""T7 - ranking never sees, and is never influenced by, anything outside the authorized scope.

Load-bearing invariant of ``src/corpus/retrieval.py`` (authorization-before-influence): every ranking input (candidate set,
candidate cap, term statistics, neighbor expansion, aggregation) is computed over the AUTHORIZED rows only.  The strongest
black-box form of that statement is checked here for several callers and random corpora: a store holding other
principals' rows next to the caller's rows returns exactly (texts, scores, order) what a store holding only the caller's
authorized rows returns.
"""
from __future__ import annotations

import random

import pytest

from src.corpus import retrieval as retrieval_mod
from tests.unit.t3_corpus_helpers import build_store, doc, search, texts

WORDS = ("quokka marmot tapir wombat caroline melanie adoption support group beach camping pottery violin "
         "paint marathon library museum garden recipe sunrise concert festival hiking painting running").split()


def _sentence(rng: random.Random) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(rng.randint(3, 14)))


def _corpus(seed: int, n: int = 90):
    """(profile, project, space, text) rows of several principals; text pools overlap on purpose."""
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        owner = rng.choice(["alice", "alice", "bob", "carol", None])
        project = rng.choice([None, None, None, "proj-x"])
        space = rng.choice([None, None, "ks-shared"])
        if owner is None:
            project = space = None
        rows.append((owner, project, space, _sentence(rng)))
    return rows


def _authorized_for_alice(row) -> bool:
    """What the plain implicit request of ``alice`` is allowed to read: own rows (any scope dims) and all-NULL rows."""
    owner, project, space, _text = row
    return owner == "alice" or (owner is None and project is None and space is None)


def _docs(rows):
    """Docs with refs that depend only on the row, so a subset store derives the same source ids (tie-break keys)."""
    return [doc(text, ref=f"file://row-{index}.txt", profile=owner, project=project, space=space)
            for index, (owner, project, space, text) in rows]


def _signature(result):
    return [(hit.normalized_text, hit.combined_score, hit.lexical_score) for hit in result.items]


# ----------------------------------------------------------------------------- discovery cap vs scope
@pytest.fixture
def tiny_window(monkeypatch):
    monkeypatch.setattr(retrieval_mod, "_DISCOVERY_FACTOR", 0)
    monkeypatch.setattr(retrieval_mod, "_DISCOVERY_CAP_FLOOR", 6)


def test_text_query_finds_own_rows_even_when_other_profiles_fill_the_discovery_window(tmp_path, tiny_window):
    crowd = [doc(f"quokka crowd entry number {i}", profile="other") for i in range(60)]
    mine = [doc("my quokka photograph from the beach", profile="me"), doc("quokka facts for me", profile="me")]
    ro = build_store(tmp_path, crowd + mine)
    try:
        result = search(ro, "quokka", profile="me", limit=5)
        assert sorted(texts(result)) == sorted(["my quokka photograph from the beach", "quokka facts for me"])
    finally:
        ro.close()


def test_or_fallback_also_scopes_before_the_window(tmp_path, tiny_window):
    crowd = [doc(f"quokka zebra crowd {i}", profile="other") for i in range(60)]
    mine = [doc("quokka only mine", profile="me")]
    ro = build_store(tmp_path, crowd + mine)
    try:
        assert texts(search(ro, "quokka giraffe", profile="me", limit=5)) == ["quokka only mine"]
    finally:
        ro.close()


def test_metadata_filter_is_applied_in_sql_for_text_queries_too(tmp_path, tiny_window):
    docs = [doc(f"quokka filler {i}", profile="me", meta={"memory_type": "fact"}) for i in range(40)]
    docs.append(doc("quokka late persona facet", profile="me", meta={"memory_type": "persona"}))
    ro = build_store(tmp_path, docs)
    try:
        res = search(ro, "quokka", profile="me", limit=5, metadata={"memory_type": "persona"})
        assert texts(res) == ["quokka late persona facet"]
    finally:
        ro.close()


# ----------------------------------------------------------------------------- non-influence (black box)
@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
@pytest.mark.parametrize("query", [
    "quokka", "caroline adoption", "beach camping pottery", "support group marathon library",
    "painting running hiking", "nonexistentterm quokka"])
def test_hidden_rows_do_not_change_scores_order_or_membership(tmp_path, seed, query):
    rows = _corpus(seed)
    indexed = list(enumerate(rows))
    allowed = [(i, row) for i, row in indexed if _authorized_for_alice(row)]
    full = build_store(tmp_path, _docs(indexed), tag="full")
    only = build_store(tmp_path, _docs(allowed), tag="only")
    try:
        with_hidden = search(full, query, profile="alice", limit=500)
        without = search(only, query, profile="alice", limit=500)
        assert _signature(with_hidden) == _signature(without)
        for hit in with_hidden.items:
            assert (hit.profile_id == "alice") or (hit.profile_id is None and hit.knowledge_space_id is None)
    finally:
        full.close()
        only.close()


@pytest.mark.parametrize("query", ["quokka", "quokka marmot", "caroline adoption support"])
def test_hidden_rows_do_not_change_results_when_the_window_is_tiny(tmp_path, tiny_window, query):
    rows = _corpus(11, n=120)
    indexed = list(enumerate(rows))
    allowed = [(i, row) for i, row in indexed if _authorized_for_alice(row)]
    full = build_store(tmp_path, _docs(indexed), tag="full")
    only = build_store(tmp_path, _docs(allowed), tag="only")
    try:
        assert _signature(search(full, query, profile="alice", limit=6)) == \
            _signature(search(only, query, profile="alice", limit=6))
    finally:
        full.close()
        only.close()


def test_a_flood_of_a_rare_term_in_hidden_rows_cannot_change_idf_or_length_statistics(tmp_path):
    base = [doc("alice tapir at the museum", ref="file://a1.txt", profile="alice"),
            doc("alice marmot and tapir together", ref="file://a2.txt", profile="alice"),
            doc("alice wombat at the beach with a long sentence about nothing relevant", ref="file://a3.txt",
                profile="alice")]
    flood = [doc("tapir " * 30, ref=f"file://m{i}.txt", profile="mallory") for i in range(50)] + \
        [doc("wombat marmot " + "filler " * 80, ref=f"file://n{i}.txt", profile="mallory") for i in range(20)]
    clean = build_store(tmp_path, base, tag="clean")
    noisy = build_store(tmp_path, flood + base, tag="noisy")
    try:
        for query in ("tapir", "marmot tapir", "wombat beach", "museum tapir wombat"):
            assert _signature(search(clean, query, profile="alice", limit=20)) == \
                _signature(search(noisy, query, profile="alice", limit=20)), query
    finally:
        clean.close()
        noisy.close()


def test_no_hit_outside_the_authorized_scope_is_ever_returned(tmp_path):
    rows = _corpus(21, n=150)
    store = build_store(tmp_path, _docs(list(enumerate(rows))))
    try:
        for query in ("quokka", "caroline adoption", "beach", "support group marathon", "violin paint"):
            result = search(store, query, profile="alice", limit=500)
            allowed_texts = {text for owner, project, space, text in rows
                             if _authorized_for_alice((owner, project, space, text))}
            for hit in result.items:
                assert hit.normalized_text in allowed_texts
                assert hit.profile_id in ("alice", None)
    finally:
        store.close()
