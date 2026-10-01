"""T7 - the synthetic LongMemEval-format generator (used only when the real dataset cannot be downloaded)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "benchmarks" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def synth():
    return _load("synth_t7", "synth_longmemeval.py")


@pytest.fixture(scope="module")
def data(synth):
    return synth.generate(seed=11, questions=40, sessions=12)


def test_generation_is_a_pure_function_of_the_seed(synth):
    a = json.dumps(synth.generate(seed=5, questions=12, sessions=10), sort_keys=True)
    b = json.dumps(synth.generate(seed=5, questions=12, sessions=10), sort_keys=True)
    c = json.dumps(synth.generate(seed=6, questions=12, sessions=10), sort_keys=True)
    assert a == b and a != c


def test_items_follow_the_longmemeval_schema(data):
    required = {"question_id", "question_type", "question", "answer", "question_date", "haystack_session_ids",
                "haystack_dates", "haystack_sessions", "answer_session_ids"}
    for item in data:
        assert required <= set(item)
        assert len(item["haystack_session_ids"]) == len(item["haystack_sessions"]) == len(item["haystack_dates"]) == 12
        assert len(set(item["haystack_session_ids"])) == 12
        for session in item["haystack_sessions"]:
            assert session and all(turn["role"] in ("user", "assistant") and turn["content"].strip() for turn in session)


def test_answer_sessions_exist_and_carry_the_marked_evidence_turn(data):
    for item in data:
        answers = item["answer_session_ids"]
        assert answers and set(answers) <= set(item["haystack_session_ids"])
        marked = {sid for sid, session in zip(item["haystack_session_ids"], item["haystack_sessions"])
                  if any(turn.get("has_answer") for turn in session)}
        assert marked == set(answers)  # nothing else is marked, no evidence session is unmarked


def test_every_question_type_appears_and_ids_are_unique(synth):
    items = synth.generate(seed=3, questions=100, sessions=10)
    assert {item["question_type"] for item in items} == {t for t, _w in synth.TYPE_WEIGHTS}
    assert len({item["question_id"] for item in items}) == 100


def test_knowledge_update_evidence_is_chronological(data):
    for item in data:
        if item["question_type"] != "knowledge-update":
            continue
        positions = [item["haystack_session_ids"].index(sid) for sid in item["answer_session_ids"]]
        assert positions == sorted(positions)
        dates = item["haystack_dates"]
        assert dates == sorted(dates)


def test_the_file_is_accepted_by_the_benchmark_loader(synth):
    bench = _load("bench_t7_synth", "memory_qa_benchmark.py")
    items = list(bench.longmemeval_items(synth.generate(seed=2, questions=3, sessions=8)))
    assert len(items) == 3
    for question, chunks, gold, qtype in items:
        assert question and chunks and gold and qtype


def test_cli_writes_the_file(synth, tmp_path, capsys):
    out = tmp_path / "synth.json"
    assert synth.main(["--seed", "4", "--questions", "5", "--sessions", "8", "--out", str(out)]) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert len(written) == 5 and written[0]["question_id"].startswith("synth_4_")
    assert "NOT LongMemEval" in (synth.__doc__ or "")
