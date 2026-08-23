"""WP-4 (v1.3.1): corpus_ingest_quant_lab stats + idempotency.

Script-level unit test with a tmp_path registry: registering identical content
twice must classify the second pass as dedup_hits with new_sources unchanged,
and the output must carry real counters (actually_new) in both modes.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

_spec = importlib.util.spec_from_file_location(
    "corpus_ingest_quant_lab", SCRIPTS / "corpus_ingest_quant_lab.py")
ingest = importlib.util.module_from_spec(_spec)
sys.modules["corpus_ingest_quant_lab"] = ingest  # dataclasses resolves module
_spec.loader.exec_module(ingest)


@dataclass
class _Rec:
    external_ref: str


class FakeRegistry:
    """Dedup-by-external_ref registry stub (size-delta observable)."""

    def __init__(self):
        self._records: dict[str, _Rec] = {}

    def all_records(self):
        return list(self._records.values())

    def register_source(self, *, content, external_ref, kind, profile_id,
                        project_id, knowledge_space_id, custom_meta, provenance):
        self._records.setdefault(external_ref, _Rec(external_ref))
        return self._records[external_ref]

    register_source_with_blob = register_source


class FakeBlobs:
    def put(self, *, content, source_ref):
        return "blob-ref"


def _paper(tmp_path: Path, md_name="2026-01-01 - a1 - T"):
    d = tmp_path / md_name
    d.mkdir(parents=True, exist_ok=True)
    md = d / f"{md_name}.md"
    md.write_text("# paper", encoding="utf-8")
    return ingest.PaperDir(path=d, date="2026-01-01", arxiv_id="a1",
                           title="T", md_file=md, pdf_name=None)


@pytest.fixture
def patched_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "QUANT_LAB", tmp_path)
    monkeypatch.setattr(ingest, "PAPERS_DIR", tmp_path / "papers")


def test_second_run_counts_dedup_not_new(patched_paths, tmp_path):
    papers = [_paper(tmp_path)]
    reg = FakeRegistry()

    first = ingest.register(reg, FakeBlobs(), dry_run=False, papers=papers)
    assert first["new_sources"] == 1
    assert first["dedup_hits"] == 0
    assert first["actually_new"] == 1
    assert first["orphan_md"] == 1

    second = ingest.register(reg, FakeBlobs(), dry_run=False, papers=papers)
    assert second["new_sources"] == 0, "idempotent re-run must not count new"
    assert second["dedup_hits"] == 1
    assert second["actually_new"] == 0
    assert len(reg.all_records()) == 1


def test_apply_mode_counts_kind_counters(patched_paths, tmp_path):
    papers = [_paper(tmp_path)]
    reg = FakeRegistry()
    res = ingest.register(reg, FakeBlobs(), dry_run=False, papers=papers)
    for key in ("primary_pdf", "derived_md", "orphan_md", "new_sources",
                "dedup_hits", "actually_new", "dirs"):
        assert key in res


def test_main_prints_real_actually_new(patched_paths, tmp_path, capsys,
                                       monkeypatch):
    papers = [_paper(tmp_path)]
    shared_registry = FakeRegistry()

    def make_registry(root):
        return shared_registry

    fake_src = type(sys)("fakesrcpkg")
    fake_corpus = type(sys)("fakesrcpkg.corpus")
    fake_corpus_mod = type(sys)("fakesrcpkg.corpus.registry")
    fake_blob_mod = type(sys)("fakesrcpkg.corpus.blob_store")

    class FakeBlobsCls:
        def __init__(self, root):
            pass

    fake_corpus_mod.CorpusSourceRegistry = staticmethod(make_registry)
    fake_blob_mod.CorpusBlobStore = FakeBlobsCls
    fake_corpus.registry = fake_corpus_mod
    fake_corpus.blob_store = fake_blob_mod
    fake_src.corpus = fake_corpus
    monkeypatch.setitem(sys.modules, "src", fake_src)
    monkeypatch.setitem(sys.modules, "src.corpus", fake_corpus)
    monkeypatch.setitem(sys.modules, "src.corpus.registry", fake_corpus_mod)
    monkeypatch.setitem(sys.modules, "src.corpus.blob_store", fake_blob_mod)
    monkeypatch.setattr(ingest, "parse_papers", lambda: papers)

    monkeypatch.setattr(sys, "argv",
                        ["corpus_ingest_quant_lab.py", "--apply",
                         "--root", str(tmp_path / "reg")])
    ingest.main()
    out = capsys.readouterr().out
    assert '"actually_new": 1' in out

    # Second run: real zero.
    monkeypatch.setattr(sys, "argv",
                        ["corpus_ingest_quant_lab.py", "--apply",
                         "--root", str(tmp_path / "reg")])
    ingest.main()
    out2 = capsys.readouterr().out
    assert '"actually_new": 0' in out2
