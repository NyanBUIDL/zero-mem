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


V1 = b"Persona prefers terse answers.\n\nWorkflow: run pytest before every commit.\n\nLine three will be deleted.\n"
V2 = b"Persona prefers terse answers.\n\nWorkflow: run pytest before every commit.\n"


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
        assert set(after) == set(before) - {k for k in before if k.endswith("#L5")}
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
        env.register(b"keep this line\n\nrotate me later\n")
        env.project()
        env.register(b"keep this line\n\npassword=hunter2 rotate me later\n")
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


# ---------------------------------------------------------------------------
# DEF-053 - multi-process write races
# ---------------------------------------------------------------------------

import json
import multiprocessing
import os
import threading

from tests.unit import _t2_workers as W


def _run_procs(targets_args, timeout=120):
    """Start one spawn process per (target, args); return the parent-queue results."""
    ctx = multiprocessing.get_context("spawn")
    out = ctx.Queue()
    barrier = ctx.Barrier(len(targets_args))
    procs = [ctx.Process(target=t, args=(*a, barrier, out)) for t, a in targets_args]
    for p in procs:
        p.start()
    results = [out.get(timeout=timeout) for _ in procs]
    for p in procs:
        p.join(timeout)
    return results


class TestDef053BlobStoreConcurrency:
    def test_blob_temp_names_are_unique_per_writer(self, tmp_path, monkeypatch):
        """Two writers of the same digest must never share one temp path."""
        store = CorpusBlobStore(root=tmp_path / "c")
        seen = []
        real_replace = os.replace

        def spy(src, dst):
            seen.append(Path(src))
            return real_replace(src, dst)

        monkeypatch.setattr(os, "replace", spy)
        digest = store.put(content=b"same bytes", source_ref="a")
        target = store._path_for(digest)
        target.unlink()  # force a second physical write of the same digest
        store.put(content=b"same bytes", source_ref="b")
        assert len(seen) == 2 and seen[0] != seen[1]
        assert all(p.parent == target.parent for p in seen)  # same dir -> atomic replace

    def test_four_processes_write_identical_bytes_without_crash(self, tmp_path):
        root = tmp_path / "corpus"
        CorpusBlobStore(root=root)  # create dirs up front
        for round_no in range(3):
            content = (f"round {round_no} ".encode() * 600_000)[:6_000_000]
            results = _run_procs([(W.blob_put, (str(root), content)) for _ in range(4)])
            errors = [r for r in results if r[0] != "ok"]
            assert errors == [], errors
            digests = {r[1] for r in results}
            assert digests == {hashlib.sha256(content).hexdigest()}
            store = CorpusBlobStore(root=root)
            assert store.get(digests.pop()) == content
        leftovers = [p for p in (root / "blobs").rglob("*") if p.is_file() and len(p.name) != 64]
        assert leftovers == [], leftovers


class TestDef053RegistryConcurrency:
    def test_four_processes_same_logical_source_create_one_line(self, tmp_path):
        root = tmp_path / "corpus"
        CorpusSourceRegistry(root=root)
        for round_no in range(3):
            ref = f"mem://persona/race-{round_no}"
            results = _run_procs([(W.register_same, (str(root), b"identical bytes\n", ref)) for _ in range(4)])
            assert [r for r in results if r[0] != "ok"] == [], results
            assert len({r[1] for r in results}) == 1
            lines = (root / "corpus_sources.jsonl").read_bytes().splitlines()
            matching = [l for l in lines if json.loads(l)["external_ref"] == ref]
            assert len(matching) == 1, f"round {round_no}: {len(matching)} lines for one logical source"

    def test_concurrent_distinct_sources_all_land_exactly_once(self, tmp_path):
        root = tmp_path / "corpus"
        CorpusSourceRegistry(root=root)
        results = _run_procs(
            [(W.register_many, (str(root), w, 10, "mem://persona/shared")) for w in range(4)])
        assert [r for r in results if r[0] != "ok"] == [], results
        raw = (root / "corpus_sources.jsonl").read_bytes()
        assert raw.endswith(b"\n")
        rows = [json.loads(l) for l in raw.splitlines()]  # every line is intact JSON
        assert len(rows) == 4 * 10 + 1
        assert len({r["source_id"] for r in rows}) == 41
        assert len(CorpusSourceRegistry(root=root).all_records()) == 41

    def test_stale_long_lived_registry_rereads_inside_the_lock(self, tmp_path):
        root = tmp_path / "corpus"
        stale = CorpusSourceRegistry(root=root)           # snapshot: empty
        fresh = CorpusSourceRegistry(root=root)
        v1 = fresh.register_source_with_blob(content=b"v1\n", external_ref="mem://p/x", kind="txt")
        again = stale.register_source_with_blob(content=b"v1\n", external_ref="mem://p/x", kind="txt")
        assert again.source_version_id == v1.source_version_id
        assert len((root / "corpus_sources.jsonl").read_bytes().splitlines()) == 1
        v2 = stale.register_source_with_blob(content=b"v2\n", external_ref="mem://p/x", kind="txt")
        assert v2.supersedes == v1.source_version_id      # chain built from the on-disk truth
        assert len((root / "corpus_sources.jsonl").read_bytes().splitlines()) == 2
        assert len(CorpusSourceRegistry(root=root).all_records()) == 2

    def test_write_lock_is_reentrant_within_a_thread(self, tmp_path):
        from src.corpus.registry import corpus_write_lock

        root = tmp_path / "corpus"
        reg = CorpusSourceRegistry(root=root)
        done = []

        def work():
            with corpus_write_lock(root):
                reg.register_source_with_blob(content=b"a\n", external_ref="mem://p/a", kind="txt")
                fresh = CorpusSourceRegistry(root=root)   # constructing inside the lock must not block
                assert len(fresh.all_records()) == 1
                done.append(True)

        t = threading.Thread(target=work, daemon=True)
        t.start()
        t.join(20)
        assert done == [True], "register/construct inside corpus_write_lock deadlocked"

    def test_lock_timeout_fails_closed_without_writing(self, tmp_path, monkeypatch):
        import src.corpus.registry as reg_mod
        from src.corpus.contracts import ValidationError
        from src.storage.coordination import locked

        root = tmp_path / "corpus"
        reg = CorpusSourceRegistry(root=root)
        monkeypatch.setattr(reg_mod, "WRITE_LOCK_TIMEOUT", 0.2)
        with locked((root / ".write.lock").resolve(), mode="exclusive"):
            with pytest.raises(ValidationError, match="write_lock_timeout"):
                reg.register_source(content=b"x", external_ref="mem://p/t", kind="txt")
        assert (root / "corpus_sources.jsonl").read_bytes() == b""


# ---------------------------------------------------------------------------
# DEF-058 - project_source(): O(1) incremental projection
# ---------------------------------------------------------------------------

def _dump_derived(conn):
    """Order-independent, complete image of the derived corpus tables."""
    src = {tuple(r) for r in conn.execute(
        "SELECT source_id, content_hash, external_ref, kind, profile_id, project_id, "
        "knowledge_space_id, sensitivity, lifecycle_status, blob_ref FROM zm_corpus_sources")}
    units = {tuple(r) for r in conn.execute(
        "SELECT unit_id, source_ref, source_location_id, content_hash, normalized_text, kind, "
        "unit_order, page, parent_ref, profile_id, project_id, knowledge_space_id, duplicate_of, "
        "lifecycle_status, sensitivity, provenance_hash FROM zm_corpus_units")}
    fts = {tuple(r) for r in conn.execute("SELECT unit_id, content FROM zm_corpus_fts")}
    return src, units, fts


class TestDef058ProjectSource:
    def test_project_source_equals_project_corpus_per_source(self, tmp_path):
        from src.corpus.derived_store import project_source

        docs = [(f"doc {i} alpha beta\n\nsecond line {i}\n".encode(), f"mem://d/{i}") for i in range(6)]
        a, b = Env(tmp_path, "a"), Env(tmp_path, "b")
        try:
            for env_ in (a, b):
                for content, ref in docs:
                    env_.register(content, ref=ref)
            a.project()
            for rec in b.registry.all_records():
                report = project_source(b.conn, b.registry, rec, blob_store=b.blobs)
                assert report.sources_projected == 1
            b.conn.commit()
            assert _dump_derived(a.conn) == _dump_derived(b.conn)
            assert len(_dump_derived(b.conn)[1]) == 12
        finally:
            a.close()
            b.close()

    def test_project_source_accepts_source_id_and_unknown_id_fails_closed(self, env):
        from src.corpus.derived_store import CorpusProjectionError, project_source

        rec = env.register(V1)
        report = project_source(env.conn, env.registry, rec.source_id, blob_store=env.blobs)
        env.conn.commit()
        assert (report.sources_projected, report.units_projected) == (1, 3)
        with pytest.raises(CorpusProjectionError):
            project_source(env.conn, env.registry, "no-such-source", blob_store=env.blobs)

    def test_project_source_never_regresses_to_an_older_version(self, env):
        from src.corpus.derived_store import project_source

        v1 = env.register(V1)
        v2 = env.register(V2)
        project_source(env.conn, env.registry, v1, blob_store=env.blobs)  # stale record handed in
        env.conn.commit()
        assert len(env.unit_rows()) == 2
        row = env.conn.execute("SELECT content_hash FROM zm_corpus_sources").fetchone()
        assert row[0] == v2.content_hash

    def test_project_source_does_not_commit(self, env):
        from src.corpus.derived_store import project_source

        rec = env.register(V1)
        project_source(env.conn, env.registry, rec, blob_store=env.blobs)
        env.conn.rollback()
        assert env.unit_rows() == []

    def test_adding_one_source_to_1000_does_not_reextract_the_others(self, env, fake_adapter):
        from src.corpus.derived_store import project_source

        for i in range(1000):
            env.register(f"fact number {i} about topic {i % 7}\n".encode(), ref=f"mem://fact/{i}", kind="t2fake")
        full = env.project()
        assert full.sources_projected == 1000 and fake_adapter.calls == 1000

        new = env.register(b"brand new persona fact\n", ref="mem://fact/new", kind="t2fake")
        fake_adapter.calls = 0
        report = project_source(env.conn, env.registry, new, blob_store=env.blobs)
        env.conn.commit()
        assert fake_adapter.calls == 1, "only the new source may be extracted"
        assert (report.sources_projected, report.units_projected) == (1, 1)
        assert env.conn.execute("SELECT COUNT(*) FROM zm_corpus_sources").fetchone()[0] == 1001
        assert any("brand new" in t for t in env.search("brand"))


# ---------------------------------------------------------------------------
# DEF-060 - per-source extraction status (never silent)
# ---------------------------------------------------------------------------

class StatusAdapter(FormatAdapter):
    """Returns a scripted outcome per kind hint 't2status:<outcome>'."""

    format = FormatKind.TXT
    parser_name = "fake:status"
    available = True

    def is_available(self) -> bool:
        return self.available

    def supports(self, kind_hint: str) -> bool:
        return kind_hint.startswith("t2status:")

    def extract(self, *, source_ref, content, kind_hint):
        outcome = kind_hint.split(":", 1)[1]
        if outcome == "raise":
            raise RuntimeError("boom with details that must not be persisted verbatim")
        if outcome == "badstatus":
            return ExtractionResult.__new__(ExtractionResult)  # no attributes -> invalid
        if outcome == "partial":
            unit = ExtractionUnit(unit_id=f"{source_ref}#p1", kind="text", text="partial text unit",
                                  source_ref=source_ref, order=1)
            return ExtractionResult(source_ref=source_ref, status="partial", units=(unit,),
                                    parser_name=self.parser_name)
        return ExtractionResult(source_ref=source_ref, status=outcome, error_reason=f"scripted {outcome}",
                                parser_name=self.parser_name, byte_length=len(content))


@pytest.fixture()
def status_adapter(monkeypatch):
    import src.corpus.adapters.registry as areg

    adapter = StatusAdapter()
    real_select = areg.select_adapter
    monkeypatch.setattr(
        areg, "select_adapter",
        lambda kind: adapter if kind.startswith("t2status:") else real_select(kind))
    return adapter


class TestDef060SourceStatus:
    def test_unsupported_kind_is_reported_not_silent(self, env):
        from src.corpus.derived_store import source_status

        good = env.register(b"plain note\n", ref="mem://note/a")
        docx = env.register(b"PK\x03\x04 not really a docx", ref="file://report.xyzzy", kind="xyzzy")
        report = env.project()
        by_id = {e["source_id"]: e for e in report.source_statuses}
        assert by_id[docx.source_id]["status"] == "unsupported_format"
        assert by_id[docx.source_id]["units"] == 0
        assert "xyzzy" in by_id[docx.source_id]["reason"]
        assert by_id[good.source_id]["status"] == "complete"
        assert by_id[good.source_id]["units"] == 1
        assert report.extractions_failed == 1
        # queryable afterwards, from the persisted derived state
        assert source_status(env.conn, docx.source_id)["status"] == "unsupported_format"
        assert source_status(env.conn, good.source_id)["status"] == "complete"

    def test_status_is_visible_from_a_fresh_readonly_connection(self, env):
        from src.corpus.derived_store import source_status

        docx = env.register(b"x", ref="file://a.xyzzy", kind="xyzzy")
        env.project()
        ro = open_readonly(env.db_path)
        try:
            entry = source_status(ro.conn, docx.source_id)
        finally:
            ro.close()
        assert entry["source_id"] == docx.source_id
        assert entry["status"] == "unsupported_format"

    @pytest.mark.parametrize("outcome", [
        "corrupt_source", "empty_source", "missing_source", "permission_denied",
        "parser_unavailable", "unsupported_format", "adapter_failed"])
    def test_every_adapter_failure_status_is_recorded(self, env, status_adapter, outcome):
        from src.corpus.derived_store import source_status

        rec = env.register(b"bytes", ref=f"mem://s/{outcome}", kind=f"t2status:{outcome}")
        report = env.project()
        entry = source_status(env.conn, rec.source_id)
        assert entry["status"] == outcome
        assert entry["units"] == 0
        assert outcome in entry["reason"]
        assert report.extractions_failed == 1
        assert report.source_statuses[0]["status"] == outcome

    def test_adapter_exception_and_invalid_status_are_adapter_failed(self, env, status_adapter):
        from src.corpus.derived_store import source_status

        a = env.register(b"bytes", ref="mem://s/raise", kind="t2status:raise")
        b = env.register(b"bytes", ref="mem://s/bad", kind="t2status:badstatus")
        report = env.project()
        for rec in (a, b):
            assert source_status(env.conn, rec.source_id)["status"] == "adapter_failed"
        assert "details that must not be persisted" not in json.dumps(report.source_statuses)
        assert report.extractions_failed == 2

    def test_parser_unavailable_when_adapter_reports_unavailable(self, env, status_adapter):
        from src.corpus.derived_store import source_status

        rec = env.register(b"bytes", ref="mem://s/x", kind="t2status:partial")
        status_adapter.available = False
        env.project()
        assert source_status(env.conn, rec.source_id)["status"] == "parser_unavailable"

    def test_partial_extraction_is_reported_as_partial(self, env, status_adapter):
        from src.corpus.derived_store import source_status

        rec = env.register(b"bytes", ref="mem://s/p", kind="t2status:partial")
        env.project()
        entry = source_status(env.conn, rec.source_id)
        assert (entry["status"], entry["units"]) == ("partial", 1)

    def test_empty_txt_source_is_empty_source(self, env):
        from src.corpus.derived_store import source_status

        rec = env.register(b"   \n\n", ref="mem://note/blank")
        env.project()
        assert source_status(env.conn, rec.source_id)["status"] == "empty_source"

    def test_source_without_blob_is_blob_unavailable(self, env):
        from src.corpus.derived_store import source_status

        rec = env.registry.register_source(content=b"no blob stored", external_ref="mem://x/noblob", kind="txt")
        assert rec.blob_ref is None
        env.project()
        assert source_status(env.conn, rec.source_id)["status"] == "blob_unavailable"

    def test_unknown_source_is_not_projected(self, env):
        from src.corpus.derived_store import source_status

        entry = source_status(env.conn, "does-not-exist")
        assert entry["status"] == "not_projected" and entry["units"] == 0

    def test_failed_v2_extraction_removes_stale_v1_units(self, env):
        from src.corpus.derived_store import source_status

        rec = env.register(b"v1 line one\n\nv1 line two\n", ref="mem://note/gone")
        env.project()
        assert len(env.unit_rows()) == 2
        env.register(b"  \n", ref="mem://note/gone")  # v2: nothing extractable
        env.project()
        assert env.unit_rows() == [] and env.fts_ids() == set()
        assert source_status(env.conn, rec.source_id)["status"] == "empty_source"

    def test_secret_rejection_sets_contained_secret_and_status(self, env):
        from src.corpus.derived_store import source_status

        only = env.register(b"password=hunter2 and more words\n", ref="mem://note/onlysecret")
        mixed = env.register(b"safe line here\n\napi_key = sk_live_abcdef0123456789abcd\n", ref="mem://note/mixed")
        report = env.project()
        e_only = source_status(env.conn, only.source_id)
        e_mixed = source_status(env.conn, mixed.source_id)
        assert (e_only["status"], e_only["units"], e_only["contained_secret"]) == ("rejected_secret", 0, True)
        assert (e_mixed["status"], e_mixed["units"], e_mixed["contained_secret"]) == ("complete", 1, True)
        assert e_mixed["units_rejected_secret"] == 1 and "units_rejected_secret:1" in e_mixed["reason"]
        assert report.units_rejected_secret == 2

    def test_clean_source_has_contained_secret_false(self, env):
        from src.corpus.derived_store import source_status

        rec = env.register(b"nothing sensitive\n", ref="mem://note/clean")
        env.project()
        assert source_status(env.conn, rec.source_id)["contained_secret"] is False

    def test_flag_contained_secret_returns_marked_copy(self):
        from src.corpus.derived_store import _flag_contained_secret

        original = ExtractionResult(source_ref="s", status="complete")
        flagged = _flag_contained_secret(original)
        assert flagged.contained_secret is True and original.contained_secret is False

    def test_rebuild_reproduces_statuses(self, env):
        from src.corpus.derived_store import source_status

        env.register(b"plain note\n", ref="mem://note/a")
        docx = env.register(b"x", ref="file://a.xyzzy", kind="xyzzy")
        env.project()
        before = source_status(env.conn, docx.source_id)
        rebuild_from_corpus(env.conn, env.registry, blob_store=env.blobs)
        env.conn.commit()
        assert source_status(env.conn, docx.source_id) == before

    def test_report_as_dict_is_backward_compatible(self, env):
        env.register(b"plain note\n", ref="mem://note/a")
        report = env.project()
        assert set(report.as_dict()) == {
            "sources_projected", "units_projected", "units_rejected_secret", "extractions_failed"}
        assert "source_statuses" in report.as_dict(include_sources=True)


# ---------------------------------------------------------------------------
# DEF-057 (storage part) - sensitivity=secret sources are withheld
# ---------------------------------------------------------------------------

class TestDef057SecretSensitivityWithheld:
    def test_secret_source_yields_no_units_and_is_not_searchable(self, env, fake_adapter):
        from src.corpus.derived_store import source_status

        rec = env.register(b"classified harmless looking words\n", ref="mem://s/classified",
                           kind="t2fake", sensitivity="secret")
        report = env.project()
        assert env.unit_rows() == [] and env.fts_ids() == set()
        assert env.search("classified") == []
        assert fake_adapter.__dict__.get("calls", 0) == 0, "withheld source must not even be extracted"
        entry = source_status(env.conn, rec.source_id)
        assert (entry["status"], entry["units"], entry["reason"]) == (
            "withheld_sensitivity", 0, "sensitivity_secret")
        assert report.units_projected == 0 and report.extractions_failed == 0

    def test_new_secret_version_removes_units_of_the_earlier_version(self, env):
        env.register(b"visible while internal\n", ref="mem://s/flip")
        env.project()
        assert len(env.unit_rows()) == 1
        env.register(b"now classified content\n", ref="mem://s/flip", sensitivity="secret")
        env.project()
        assert env.unit_rows() == [] and env.fts_ids() == set()

    @pytest.mark.parametrize("level", ["public", "internal", "private"])
    def test_other_sensitivities_are_still_projected(self, env, level):
        env.register(f"{level} words\n".encode(), ref=f"mem://s/{level}", sensitivity=level)
        report = env.project()
        assert report.units_projected == 1
        assert len(env.unit_rows()) == 1

    def test_project_source_also_withholds(self, env):
        from src.corpus.derived_store import project_source

        rec = env.register(b"secret doc\n", ref="mem://s/one", sensitivity="secret")
        report = project_source(env.conn, env.registry, rec, blob_store=env.blobs)
        assert report.units_projected == 0
        assert report.source_statuses[0]["status"] == "withheld_sensitivity"


# ---------------------------------------------------------------------------
# DEF-059 - rebuild_from_corpus must be reader-safe
# ---------------------------------------------------------------------------

class TestDef059RebuildReaderSafe:
    N_SOURCES = 400

    def _seed_live_db(self, tmp_path):
        root = tmp_path / "corpus"
        db_path = tmp_path / "live.sqlite"
        store = SQLiteStore(SQLiteStoreConfig(path=db_path))  # production pragmas: WAL
        store.ensure_schema()
        registry = CorpusSourceRegistry(root=root)
        blobs = CorpusBlobStore(root=root)
        for i in range(self.N_SOURCES):
            registry.register_source_with_blob(
                content=f"doc {i} first line\n\nsecond line {i}\n".encode(),
                external_ref=f"mem://d/{i}", kind="txt", profile_id="p", blob_store=blobs)
        project_corpus(store._conn, registry, blob_store=blobs)
        store._conn.commit()
        assert store._conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        store.close()
        return root, db_path

    def test_concurrent_reader_never_sees_empty_partial_or_errors(self, tmp_path):
        root, db_path = self._seed_live_db(tmp_path)
        ctx = multiprocessing.get_context("spawn")
        reader_q, writer_q, stop = ctx.Queue(), ctx.Queue(), ctx.Event()
        reader = ctx.Process(target=W.read_loop, args=(
            str(db_path), self.N_SOURCES, 2 * self.N_SOURCES, stop, reader_q))
        writer = ctx.Process(target=W.rebuild_loop, args=(str(db_path), str(root), 4, writer_q))
        reader.start()
        assert reader_q.get(timeout=60)[0] == "ready"
        writer.start()
        outcome = None
        while outcome is None:
            kind, payload = writer_q.get(timeout=300)
            if kind in ("done", "error"):
                outcome = (kind, payload)
        stop.set()
        kind, result = reader_q.get(timeout=60)
        reader.join(60)
        writer.join(60)
        assert outcome[0] == "done", outcome
        assert kind == "result", result
        assert result["reads"] >= 5, f"reader did not overlap the rebuilds: {result}"
        assert result["empty"] == 0, result
        assert result["partial"] == 0, result
        assert result["errors"] == 0, result

    def test_rebuild_commits_when_it_owns_the_transaction(self, env):
        env.register(V1)
        env.project()
        rebuild_from_corpus(env.conn, env.registry, blob_store=env.blobs)  # no explicit commit
        other = sqlite3.connect(str(env.db_path))
        try:
            assert other.execute("SELECT COUNT(*) FROM zm_corpus_units").fetchone()[0] == 3
            assert other.execute("SELECT COUNT(*) FROM zm_corpus_fts").fetchone()[0] == 3
        finally:
            other.close()

    def test_failure_while_building_leaves_live_tables_untouched(self, env, monkeypatch):
        import src.corpus.derived_store as ds

        env.register(V1)
        env.project()

        def boom(*a, **kw):
            raise RuntimeError("extraction exploded")

        monkeypatch.setattr(ds, "project_corpus", boom)
        with pytest.raises(RuntimeError):
            rebuild_from_corpus(env.conn, env.registry, blob_store=env.blobs)
        assert len(env.unit_rows()) == 3 and len(env.fts_ids()) == 3

    def test_rebuild_inside_callers_transaction_rolls_back_with_it(self, env):
        env.register(V1)
        env.project()
        env.conn.execute("BEGIN")
        rebuild_from_corpus(env.conn, env.registry, blob_store=env.blobs)
        env.conn.rollback()
        assert len(env.unit_rows()) == 3 and len(env.fts_ids()) == 3

    def test_rebuild_with_no_registry_sources_yields_empty_valid_tables(self, env):
        report = rebuild_from_corpus(env.conn, env.registry, blob_store=env.blobs)
        assert report.sources_projected == 0
        assert env.unit_rows() == [] and env.fts_ids() == set()
