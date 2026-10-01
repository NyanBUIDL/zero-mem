"""T7 - the QA benchmark runs through the real Memory pipeline and reports retrieval quality, latency, throughput.

Everything here uses tiny in-test datasets; the real LoCoMo / LongMemEval runs are documented in
``benchmarks/README.md`` and ``docs/benchmarks/RESULTS.md``.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _bench():
    spec = importlib.util.spec_from_file_location("mqb_t7", ROOT / "benchmarks" / "memory_qa_benchmark.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _lme(n_sessions: int = 3):
    animals = ["quokka", "pangolin", "marmot", "tapir", "wombat", "capybara"]
    return [{
        "question_id": "q1", "question_type": "single-session-user",
        "question": "Which animal did I photograph in Western Australia?",
        "haystack_session_ids": [f"s{i}" for i in range(n_sessions)],
        "haystack_sessions": [
            [{"role": "user", "content": f"I photographed a {animals[0]} in Western Australia."},
             {"role": "assistant", "content": "That sounds lovely."}] if i == 0 else
            [{"role": "user", "content": f"I like {animals[i]} documentaries about forests."},
             {"role": "assistant", "content": "Documentaries are a great way to relax."}]
            for i in range(n_sessions)],
        "answer_session_ids": ["s0"],
    }]


def _locomo():
    return [{
        "conversation": {"speaker_a": "A", "speaker_b": "B",
                         "session_1": [
                             {"speaker": "A", "text": "I adopted a cat named Miso.", "dia_id": "D1:1"},
                             {"speaker": "B", "text": "The weather is lovely today.", "dia_id": "D1:2"}],
                         "session_2": [
                             {"speaker": "A", "text": "Quokkas live in Western Australia.", "dia_id": "D2:1"},
                             {"speaker": "B", "text": "Redis eviction is configurable.", "dia_id": "D2:2"}]},
        "qa": [{"question": "What is the name of the cat?", "evidence": ["D1:1"], "category": 1},
               {"question": "Where do quokkas live?", "evidence": ["D2:1"], "category": 2},
               {"question": "Can redis evict keys and where do quokkas live?", "evidence": ["D2:2", "D2:1"],
                "category": 2}],
    }]


# ----------------------------------------------------------------------------- metrics (pure)
def test_score_ranking_reports_hit_recall_and_mrr():
    mod = _bench()
    s = mod.score_ranking(["a", "b", "c", "d"], {"b", "d", "zzz"}, [1, 2, 4])
    assert s["hit@1"] == 0.0 and s["hit@2"] == 1.0 and s["hit@4"] == 1.0
    assert s["recall@1"] == 0.0
    assert s["recall@2"] == pytest.approx(1 / 3)
    assert s["recall@4"] == pytest.approx(2 / 3)
    assert s["mrr"] == pytest.approx(0.5)


def test_score_ranking_without_a_gold_hit_scores_zero():
    mod = _bench()
    s = mod.score_ranking(["a", "b"], {"x"}, [1, 5])
    assert s["mrr"] == 0.0 and s["hit@5"] == 0.0 and s["recall@5"] == 0.0


def test_percentile_is_nearest_rank_and_deterministic():
    mod = _bench()
    values = [float(v) for v in range(1, 101)]
    assert mod.percentile(values, 50) == 50.0
    assert mod.percentile(values, 95) == 95.0
    assert mod.percentile([7.0], 95) == 7.0
    assert mod.percentile([], 50) == 0.0
    assert mod.percentile(list(reversed(values)), 95) == 95.0  # order independent


# ----------------------------------------------------------------------------- report shape
def test_run_reports_quality_latency_and_ingest_throughput():
    mod = _bench()
    res = mod.run(mod.longmemeval_items(_lme()), [1, 5, 10])
    assert res["questions"] == 1 and res["hit@1"] == 1.0 and res["recall@10"] == 1.0
    assert res["mrr"] == 1.0
    assert res["by_type"]["single-session-user"] == {
        "questions": 1, "hit@1": 1.0, "hit@5": 1.0, "hit@10": 1.0,
        "recall@1": 1.0, "recall@5": 1.0, "recall@10": 1.0, "mrr": 1.0}
    lat = res["latency_ms"]
    assert lat["queries"] == 1 and lat["p50"] > 0 and lat["p95"] >= lat["p50"] and lat["max"] >= lat["p95"]
    ing = res["ingest"]
    assert ing["adds"] == 6 and ing["seconds"] > 0 and ing["adds_per_second"] > 0
    assert len(res["fingerprint"]) == 16


def test_legacy_output_keys_are_kept():
    mod = _bench()
    res = mod.run(mod.locomo_items(_locomo()), [1, 5, 10])
    for key in ("questions", "recall@1", "recall@5", "recall@10", "hit@1", "hit@5", "hit@10", "hit@1_by_type"):
        assert key in res
    assert set(res["hit@1_by_type"]) == {"cat1", "cat2"}


def test_report_is_json_serialisable():
    mod = _bench()
    res = mod.run(mod.locomo_items(_locomo()), [1])
    assert json.loads(json.dumps(res, sort_keys=True)) == res


# ----------------------------------------------------------------------------- datasets and levels
def test_locomo_session_level_gold_is_the_session_of_each_evidence_turn():
    mod = _bench()
    items = list(mod.locomo_items(_locomo(), level="session"))
    (_q1, chunks, gold1, _t1), (_q2, _c2, gold2, _t2), (_q3, _c3, gold3, _t3) = items
    assert gold1 == {"session_1"} and gold2 == {"session_2"} and gold3 == {"session_2"}
    assert {tag for _text, tag, _group in chunks} == {"session_1", "session_2"}


def test_locomo_session_level_run_ranks_distinct_sessions():
    mod = _bench()
    res = mod.run(mod.locomo_items(_locomo(), level="session"), [1, 2], ingest="session")
    assert res["questions"] == 3 and res["hit@2"] == 1.0
    assert res["ingest"]["adds"] == 2  # one memory per session


def test_session_ingest_adds_one_memory_per_session_not_per_turn(monkeypatch):
    import zero_mem.memory as memory_mod

    mod = _bench()
    calls = []
    real_add = memory_mod.Memory.add

    def spy(self, text, *args, **kwargs):
        calls.append(text)
        return real_add(self, text, *args, **kwargs)

    monkeypatch.setattr(memory_mod.Memory, "add", spy)
    res = mod.run(mod.longmemeval_items(_lme(4)), [1, 5], ingest="session")
    assert len(calls) == 4 and res["hit@1"] == 1.0
    assert "I photographed a quokka" in calls[0]


def test_turn_ingest_collapses_hits_to_distinct_sessions_in_rank_order():
    mod = _bench()
    data = _lme(2)
    data[0]["haystack_sessions"][0] = [
        {"role": "user", "content": "I photographed a quokka in Western Australia."},
        {"role": "user", "content": "Another quokka photograph from Western Australia, a second one."},
        {"role": "user", "content": "A third quokka photograph from Western Australia."}]
    res = mod.run(mod.longmemeval_items(data), [1, 2])
    assert res["hit@1"] == 1.0 and res["mrr"] == 1.0  # three turns of s0 are ONE ranked session


def test_longmemeval_items_default_to_session_level_gold():
    mod = _bench()
    ((_q, chunks, gold, qtype),) = list(mod.longmemeval_items(_lme()))
    assert gold == {"s0"} and qtype == "single-session-user"
    assert all(len(chunk) == 3 for chunk in chunks)
    assert {group for _t, _tag, group in chunks} == {"s0", "s1", "s2"}


# ----------------------------------------------------------------------------- determinism / seed / json
def test_same_input_gives_the_same_fingerprint_twice():
    mod = _bench()
    a = mod.run(mod.locomo_items(_locomo()), [1, 5])
    b = mod.run(mod.locomo_items(_locomo()), [1, 5])
    assert a["fingerprint"] == b["fingerprint"]


def test_determinism_check_passes_on_the_real_pipeline():
    mod = _bench()
    res = mod.run(mod.locomo_items(_locomo()), [1, 5], check_determinism=True)
    assert res["determinism"] == {"checked": 3, "mismatches": 0, "ok": True}


def test_determinism_check_detects_an_unstable_engine():
    mod = _bench()

    class Flaky(mod.MemoryEngine):
        calls = 0

        def search(self, question, limit):
            hits = super().search(question, limit)
            Flaky.calls += 1
            return list(reversed(hits)) if Flaky.calls % 2 == 0 else hits

    res = mod.run(mod.locomo_items(_locomo()), [1], check_determinism=True, engine_factory=Flaky)
    assert res["determinism"]["ok"] is False and res["determinism"]["mismatches"] >= 1


def test_select_without_seed_is_the_first_n_and_with_seed_is_a_stable_sample():
    mod = _bench()
    data = list(range(50))
    assert mod.select(data, 5, None) == [0, 1, 2, 3, 4]
    a = mod.select(data, 5, 7)
    assert a == mod.select(data, 5, 7) and a == sorted(a) and len(set(a)) == 5
    assert a != mod.select(data, 5, 8)
    assert mod.select(data, None, 7) == data


def test_cli_writes_json_file_and_prints_the_same_report(tmp_path, capsys):
    mod = _bench()
    data = tmp_path / "locomo.json"
    data.write_text(json.dumps(_locomo()), encoding="utf-8")
    out = tmp_path / "out.json"
    assert mod.main(["locomo", str(data), "-k", "1", "5", "--json", str(out)]) == 0
    printed = json.loads(capsys.readouterr().out)
    written = json.loads(out.read_text(encoding="utf-8"))
    assert printed == written
    assert written["questions"] == 3 and written["config"]["dataset"] == "locomo"
    assert written["config"]["ks"] == [1, 5] and written["config"]["seed"] is None


def test_cli_exits_nonzero_when_the_determinism_check_fails(tmp_path, monkeypatch, capsys):
    mod = _bench()
    data = tmp_path / "locomo.json"
    data.write_text(json.dumps(_locomo()), encoding="utf-8")

    class Flaky(mod.MemoryEngine):
        calls = 0

        def search(self, question, limit):
            hits = super().search(question, limit)
            Flaky.calls += 1
            return list(reversed(hits)) if Flaky.calls % 2 == 0 else hits

    monkeypatch.setattr(mod, "MemoryEngine", Flaky)
    assert mod.main(["locomo", str(data), "--check-determinism"]) == 3


# ----------------------------------------------------------------------------- store reuse for experiments
def test_cache_dir_reuses_the_store_and_gives_identical_rankings(tmp_path, monkeypatch):
    import zero_mem.memory as memory_mod

    mod = _bench()
    cache = tmp_path / "cache"
    first = mod.run(mod.locomo_items(_locomo()), [1, 5], cache_dir=cache)
    assert first["ingest"]["adds"] > 0 and first["ingest"]["cached"] is False

    def boom(self, *a, **k):  # a cached run must not write
        raise AssertionError("add() called on a cached store")

    monkeypatch.setattr(memory_mod.Memory, "add", boom)
    second = mod.run(mod.locomo_items(_locomo()), [1, 5], cache_dir=cache)
    assert second["ingest"]["cached"] is True and second["ingest"]["adds"] == 0
    assert second["fingerprint"] == first["fingerprint"] and second["hit@5"] == first["hit@5"]


def test_cache_key_depends_on_ingest_mode(tmp_path):
    mod = _bench()
    mod.run(mod.longmemeval_items(_lme(3)), [1], cache_dir=tmp_path / "c", ingest="turn")
    mod.run(mod.longmemeval_items(_lme(3)), [1], cache_dir=tmp_path / "c", ingest="session")
    assert len([p for p in (tmp_path / "c").iterdir() if p.is_dir()]) == 2


# ----------------------------------------------------------------------------- real pipeline only
def test_benchmark_never_touches_the_index_directly():
    source = (ROOT / "benchmarks" / "memory_qa_benchmark.py").read_text(encoding="utf-8")
    for forbidden in ("retrieve_corpus", "sqlite3", "zm_corpus", "corpus_unit_search", "zero_mem.notes"):
        assert forbidden not in source
    assert "Memory.open" in source and ".recall(" in source and ".add(" in source


def test_the_recall_path_is_the_authorized_one(monkeypatch):
    """Every ranked list comes from ``Memory.recall`` of the pinned profile (never an unauthorized shortcut)."""
    import zero_mem.memory as memory_mod

    mod = _bench()
    seen = []
    real = memory_mod.Memory.recall

    def spy(self, query, *args, **kwargs):
        seen.append((self.profile_id, query))
        return real(self, query, *args, **kwargs)

    monkeypatch.setattr(memory_mod.Memory, "recall", spy)
    mod.run(mod.locomo_items(_locomo()), [1])
    assert {profile for profile, _q in seen} == {"bench"} and len(seen) == 3
