"""T2 (shared-memory-runtime) corpus storage defects.

DEF-050  stale units after a source update
DEF-053  multi-process write races (blob temp names, registry duplicate lines)
DEF-057  sensitivity=secret sources must not be projected into units
DEF-058  O(N) projection per add -> project_source()
DEF-059  in-place rebuild is not reader-safe
DEF-060  silent per-source extraction failures

Evidence for each defect is recorded in docs/defects/closures/T2.md.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from src.access import AccessRequest, AuthorizedReadService
from src.corpus.adapters.base import FormatAdapter, FormatKind
from src.corpus.blob_store import CorpusBlobStore
from src.corpus.derived_store import project_corpus, rebuild_from_corpus
from src.corpus.extract import ExtractionResult, ExtractionStatus, ExtractionUnit
from src.corpus.registry import CorpusSourceRegistry
from src.retrieval.db import open_readonly
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class Env:
    """One corpus root + one derived DB (DELETE journal so fresh RO readers see commits)."""

    def __init__(self, tmp_path: Path, name: str = "env") -> None:
        self.root = tmp_path / f"{name}-corpus"
        self.db_path = tmp_path / f"{name}.sqlite"
        self.store = SQLiteStore(SQLiteStoreConfig(path=self.db_path))
        self.store.ensure_schema()
        self.conn = self.store._conn
        self.conn.execute("PRAGMA journal_mode=DELETE")
        self.registry = CorpusSourceRegistry(root=self.root)
        self.blobs = CorpusBlobStore(root=self.root)

    def register(self, content: bytes, ref: str = "mem://persona/main", kind: str = "txt",
                 profile_id: str = "claude-code", **kw):
        return self.registry.register_source_with_blob(
            content=content, external_ref=ref, kind=kind, profile_id=profile_id,
            blob_store=self.blobs, **kw)

    def project(self):
        report = project_corpus(self.conn, self.registry, blob_store=self.blobs)
        self.conn.commit()
        return report

    def unit_rows(self, source_id=None):
        sql = "SELECT unit_id, source_location_id, normalized_text, unit_order FROM zm_corpus_units"
        args: tuple = ()
        if source_id is not None:
            sql += " WHERE source_ref=?"
            args = (source_id,)
        return self.conn.execute(sql + " ORDER BY unit_order, unit_id", args).fetchall()

    def fts_ids(self):
        return {r[0] for r in self.conn.execute("SELECT unit_id FROM zm_corpus_fts")}

    def search(self, text: str, profile: str = "claude-code"):
        ro = open_readonly(self.db_path)
        try:
            res = AuthorizedReadService(ro, requesting_profile_id=profile).corpus_unit_search(
                AccessRequest(operation="READ", requesting_profile_id=profile,
                              target_profile_ids=[profile], resource_type="corpus_unit"),
                text, limit=50)
            return [h.normalized_text for h in res.items]
        finally:
            ro.close()

    def close(self):
        self.store.close()


@pytest.fixture()
def env(tmp_path):
    e = Env(tmp_path)
    try:
        yield e
    finally:
        e.close()


class FakeLineAdapter(FormatAdapter):
    """Content-addressed unit ids (stable under reordering), order = position."""

    format = FormatKind.TXT
    parser_name = "fake:lines"

    def is_available(self) -> bool:
        return True

    def supports(self, kind_hint: str) -> bool:
        return kind_hint == "t2fake"

    def extract(self, *, source_ref, content, kind_hint):
        self.calls = getattr(self, "calls", 0) + 1
        lines = [l for l in content.decode("utf-8").splitlines() if l.strip()]
        units = tuple(
            ExtractionUnit(
                unit_id=f"{source_ref}#h{hashlib.sha1(l.encode()).hexdigest()[:8]}",
                kind="text", text=l, source_ref=source_ref, order=i)
            for i, l in enumerate(lines, start=1))
        return ExtractionResult(source_ref=source_ref, status="complete", units=units,
                                parser_name=self.parser_name, byte_length=len(content))


@pytest.fixture()
def fake_adapter(monkeypatch):
    import src.corpus.adapters.registry as areg

    adapter = FakeLineAdapter()
    real_select = areg.select_adapter
    monkeypatch.setattr(
        areg, "select_adapter",
        lambda kind: adapter if kind == "t2fake" else real_select(kind))
    return adapter


V1 = b"Persona prefers terse answers.\nWorkflow: run pytest before every commit.\nLine three will be deleted.\n"
V2 = b"Persona prefers terse answers.\nWorkflow: run pytest before every commit.\n"


# ---------------------------------------------------------------------------
# DEF-050 - stale units after a source update
# ---------------------------------------------------------------------------

class TestDef050StaleUnits:
    def test_v2_dropping_a_line_removes_it_from_search_and_tables(self, env):
        rec1 = env.register(V1)
        env.project()
        assert any("deleted" in t for t in env.search("deleted"))
        assert len(env.unit_rows()) == 3 and len(env.fts_ids()) == 3

        rec2 = env.register(V2)
        assert rec2.source_id == rec1.source_id and rec2.content_hash != rec1.content_hash
        env.project()

        assert env.search("deleted") == []
        assert any("terse" in t for t in env.search("terse"))
        assert len(env.unit_rows()) == 2
        assert len(env.fts_ids()) == 2
        assert not any("deleted" in r["normalized_text"] for r in env.unit_rows())

    def test_unchanged_units_keep_their_ids(self, env):
        env.register(V1)
        env.project()
        before = {r["source_location_id"]: r["unit_id"] for r in env.unit_rows()}
        env.register(V2)
        env.project()
        after = {r["source_location_id"]: r["unit_id"] for r in env.unit_rows()}
        assert set(after) == set(before) - {k for k in before if k.endswith("#L3")}
        for loc, uid in after.items():
            assert before[loc] == uid, "unchanged unit must keep its unit_id"

    def test_stale_removal_is_part_of_callers_transaction(self, env):
        """Projection never commits: rolling back v2 restores the complete v1 state."""
        env.register(V1)
        env.project()
        env.register(V2)
        project_corpus(env.conn, env.registry, blob_store=env.blobs)  # no commit
        assert len(env.unit_rows()) == 2
        env.conn.rollback()
        assert len(env.unit_rows()) == 3
        assert len(env.fts_ids()) == 3

    def test_unit_that_becomes_secret_in_v2_is_removed(self, env):
        env.register(b"keep this line\nrotate me later\n")
        env.project()
        env.register(b"keep this line\npassword=hunter2 rotate me later\n")
        report = env.project()
        texts = [r["normalized_text"] for r in env.unit_rows()]
        assert texts == ["keep this line"]
        assert report.units_rejected_secret == 1
        assert env.fts_ids() == {r["unit_id"] for r in env.unit_rows()}

    def test_changed_order_of_surviving_unit_is_updated(self, env, fake_adapter):
        env.register(b"alpha line\nbeta line\ngamma line\n", ref="mem://x/fake", kind="t2fake")
        env.project()
        env.register(b"beta line\ngamma line\n", ref="mem://x/fake", kind="t2fake")
        env.project()
        rows = {r["normalized_text"]: r["unit_order"] for r in env.unit_rows()}
        assert rows == {"beta line": 1, "gamma line": 2}

    def test_incremental_state_equals_clean_rebuild(self, env):
        env.register(V1)
        env.project()
        env.register(V2)
        env.project()
        incremental = {(r["unit_id"], r["normalized_text"], r["unit_order"]) for r in env.unit_rows()}
        rebuild_from_corpus(env.conn, env.registry, blob_store=env.blobs)
        env.conn.commit()
        rebuilt = {(r["unit_id"], r["normalized_text"], r["unit_order"]) for r in env.unit_rows()}
        assert incremental == rebuilt
