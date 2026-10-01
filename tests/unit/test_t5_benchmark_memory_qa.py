"""T5 - the offline QA benchmark builds its store with ``Memory`` (ported from the retired notes tests)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _bench():
    spec = importlib.util.spec_from_file_location("mqb", ROOT / "benchmarks" / "memory_qa_benchmark.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_benchmark_longmemeval_format():
    mod = _bench()
    data = [{
        "question_id": "q1", "question_type": "single-session-user",
        "question": "What is my dog's name?",
        "haystack_session_ids": ["s1", "s2"],
        "haystack_sessions": [
            [{"role": "user", "content": "My dog's name is Biscuit."}],
            [{"role": "user", "content": "I like hiking in autumn."}],
        ],
        "answer_session_ids": ["s1"],
    }]
    res = mod.run(mod.longmemeval_items(data), [1, 5])
    assert res["recall@1"] == 1.0 and res["hit@5"] == 1.0
    assert res["hit@1_by_type"] == {"single-session-user": 1.0}


def test_benchmark_locomo_format():
    mod = _bench()
    data = [{
        "conversation": {"speaker_a": "A", "speaker_b": "B", "session_1": [
            {"speaker": "A", "text": "I adopted a cat named Miso.", "dia_id": "D1:1"},
            {"speaker": "B", "text": "The weather is lovely today.", "dia_id": "D1:2"}]},
        "qa": [{"question": "What is the name of the cat?", "evidence": ["D1:1"], "category": 1}],
    }]
    res = mod.run(mod.locomo_items(data), [1])
    assert res["questions"] == 1 and res["recall@1"] == 1.0


def test_output_format_is_unchanged():
    mod = _bench()
    data = [{
        "conversation": {"session_1": [
            {"speaker": "A", "text": "Quokkas live in Western Australia.", "dia_id": "D1:1"},
            {"speaker": "B", "text": "Redis eviction is configurable.", "dia_id": "D1:2"}]},
        "qa": [{"question": "Where do quokkas live?", "evidence": ["D1:1"], "category": 2},
               {"question": "What about redis eviction?", "evidence": ["D1:2"], "category": 1}],
    }]
    res = mod.run(mod.locomo_items(data), [1, 5, 10])
    # T7 only ADDS keys (mrr, by_type, latency_ms, ingest, fingerprint, config): every T5 key keeps its meaning.
    legacy = ["questions", "recall@1", "recall@5", "recall@10", "hit@1", "hit@5", "hit@10", "hit@1_by_type"]
    assert set(legacy) <= set(res)
    assert {"mrr", "by_type", "latency_ms", "ingest", "fingerprint", "config"} <= set(res)
    assert res["questions"] == 2 and res["hit@1"] == 1.0
    assert set(res["hit@1_by_type"]) == {"cat1", "cat2"}


def test_the_benchmark_no_longer_depends_on_the_retired_notes_store():
    source = (ROOT / "benchmarks" / "memory_qa_benchmark.py").read_text(encoding="utf-8")
    assert "zero_mem.notes" not in source and "NotesStore" not in source
    assert "Memory" in source


def test_every_haystack_gets_a_fresh_private_store_in_a_temp_root(monkeypatch, tmp_path):
    import zero_mem.memory as memory_mod

    mod = _bench()
    opened = []
    real_open = memory_mod.Memory.open.__func__

    def spy(cls, profile_id, data_root=None, **kwargs):
        opened.append((profile_id, Path(data_root) if data_root else None))
        return real_open(cls, profile_id, data_root, **kwargs)

    monkeypatch.setattr(memory_mod.Memory, "open", classmethod(spy))
    chunks_a = [("A: alpha unique wombat fact", "D1:1")]
    chunks_b = [("B: beta unique tapir fact", "D2:1")]
    items = [("wombat?", chunks_a, {"D1:1"}, "cat1"), ("tapir?", chunks_b, {"D2:1"}, "cat1")]
    res = mod.run(iter(items), [1])
    assert res["hit@1"] == 1.0
    assert len(opened) == 2 and len({root for _p, root in opened}) == 2
    assert {p for p, _r in opened} == {"bench"}
    assert all(root is not None and root.parent.name.startswith("zm-bench-") for _p, root in opened)
    assert all(not root.exists() for _p, root in opened)  # temp roots are cleaned up


def test_questions_over_the_same_haystack_reuse_one_store():
    mod = _bench()
    chunks = [("A: quokkas live in Australia", "D1:1"), ("B: redis can evict keys", "D1:2")]
    items = [("where do quokkas live", chunks, {"D1:1"}, "cat1"), ("can redis evict", chunks, {"D1:2"}, "cat1")]
    res = mod.run(iter(items), [1])
    assert res["questions"] == 2 and res["hit@1"] == 1.0


def test_identical_turn_text_resolves_to_the_first_source_like_the_old_store():
    mod = _bench()
    chunks = [("A: thanks", "D1:1"), ("A: thanks", "D1:2"), ("B: marmots hibernate", "D1:3")]
    res = mod.run(iter([("marmots hibernate?", chunks, {"D1:3"}, "cat1")]), [1])
    assert res["hit@1"] == 1.0


def test_secret_looking_turns_do_not_break_the_run():
    mod = _bench()
    chunks = [("A: my key is " + "sk-" + "ant-api03-abcdefghijklmnopqrstuvwxyz0123456789", "D1:1"),
              ("B: pangolins eat ants", "D1:2")]
    res = mod.run(iter([("what do pangolins eat", chunks, {"D1:2"}, "cat1")]), [1])
    assert res["hit@1"] == 1.0
