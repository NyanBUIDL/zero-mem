import importlib.util
import json
from pathlib import Path

import pytest

from zero_mem import cli
from zero_mem.notes import NotesStore, chunk_text, parse_chat

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def store(tmp_path):
    return NotesStore(tmp_path / "n.jsonl", tmp_path / "n.sqlite3")


def test_add_search_dedup(store):
    assert store.add_text("Alice prefers PostgreSQL for storage.")["added"] == 1
    assert store.add_text("Alice prefers PostgreSQL for storage.")["duplicate"] == 1
    hits = store.search("which database does Alice prefer? PostgreSQL")
    assert hits and "PostgreSQL" in hits[0].text
    assert store.search("") == [] and store.search("zzzunknown") == []


@pytest.mark.parametrize("secret", [
    "token sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789",
    "AKIAIOSFODNN7EXAMPLE",
    "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    "password=hunter2hunter2",
])
def test_secrets_rejected_not_persisted(store, secret):
    assert store.add_text(secret)["rejected_secret"] == 1
    assert store.count() == 0 and not store.stream.exists() or store.stream.read_text() == ""


def test_rebuild_from_canonical(store):
    store.add_text("Deploy staging on fly.io.\n\nProd runs on bare metal.")
    store.db.unlink()
    assert store.rebuild() == 1
    assert store.search("fly.io")


def test_chunking_and_chat_parsing():
    assert all(len(c) <= 800 for c in chunk_text("word " * 1000))
    assert parse_chat("User: hi\nAssistant: hello\nmore\nUser: bye") == ["User: hi", "Assistant: hello\nmore", "User: bye"]
    jl = '{"role":"user","content":"hi"}\n{"role":"assistant","content":[{"text":"yo"}]}'
    assert parse_chat(jl) == ["user: hi", "assistant: yo"]


def test_cli_roundtrip(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ZERO_MEM_DATA_ROOT", str(tmp_path / "data"))
    f = tmp_path / "log.md"
    f.write_text("# Plan\n\nShip the ingest CLI on Friday.\n")
    assert cli.main(["ingest", str(f)]) == 0
    assert json.loads(capsys.readouterr().out)["added"] >= 1
    assert cli.main(["search", "--json", "ingest", "Friday"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out and out[0]["source"] == "log.md"


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
