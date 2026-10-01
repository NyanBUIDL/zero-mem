"""T5 / DEF-057 - lifecycle tombstone: a source whose latest version is ``deleted`` is excluded from projection.

The raw blob of every earlier version is kept (AGENTS.md: never delete raw traces); only the derived
units/FTS rows disappear, and a full rebuild reproduces that.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.corpus.blob_store import CorpusBlobStore
from src.corpus.derived_store import (
    SOURCE_STATUSES,
    project_corpus,
    project_source,
    rebuild_from_corpus,
    source_status,
)
from src.corpus.registry import CorpusSourceRegistry
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "corpus"
        self.root.mkdir()
        self.registry = CorpusSourceRegistry(root=self.root)
        self.blobs = CorpusBlobStore(root=self.root)
        self.store = SQLiteStore(SQLiteStoreConfig(path=tmp_path / "d.sqlite3"))
        self.store.ensure_schema()
        self.conn = self.store._conn

    def add(self, ref: str, text: str, *, lifecycle: str = "observed"):
        return self.registry.register_source_with_blob(
            content=text.encode(), external_ref=ref, kind="txt", profile_id="p1",
            custom_meta={"memory_type": "fact"}, lifecycle_status=lifecycle, blob_store=self.blobs)

    def units(self, ref: str | None = None) -> list[str]:
        rows = self.conn.execute("SELECT normalized_text FROM zm_corpus_units ORDER BY unit_id").fetchall()
        return [r[0] for r in rows]

    def fts_rows(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM zm_corpus_fts").fetchone()[0]


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.store.close()


def tombstone(env: Env, record, body: str = '{"tombstone": true}'):
    return env.registry.register_source_with_blob(
        content=body.encode(), external_ref=record.external_ref, kind=record.kind,
        profile_id=record.profile_id, project_id=record.project_id,
        knowledge_space_id=record.knowledge_space_id, custom_meta=dict(record.custom_meta),
        lifecycle_status="deleted", blob_store=env.blobs)


def test_deleted_status_is_part_of_the_closed_vocabulary():
    assert "deleted" in SOURCE_STATUSES


def test_tombstone_version_removes_units_and_fts_rows(env):
    keep = env.add("mem://fact/keep", "alpha keep unit")
    gone = env.add("mem://fact/gone", "beta forgotten unit")
    project_corpus(env.conn, env.registry, blob_store=env.blobs)
    env.conn.commit()
    assert env.units() == ["alpha keep unit", "beta forgotten unit"] and env.fts_rows() == 2

    tomb = tombstone(env, gone)
    assert tomb.source_id == gone.source_id and tomb.lifecycle_status == "deleted"
    project_source(env.conn, env.registry, tomb, blob_store=env.blobs)
    env.conn.commit()

    assert env.units() == ["alpha keep unit"] and env.fts_rows() == 1
    status = source_status(env.conn, gone.source_id)
    assert status["status"] == "deleted" and status["units"] == 0
    assert source_status(env.conn, keep.source_id)["status"] == "complete"
    row = env.conn.execute(
        "SELECT lifecycle_status FROM zm_corpus_sources WHERE source_id=?", (gone.source_id,)).fetchone()
    assert row[0] == "deleted"


def test_tombstone_never_reads_or_extracts_the_tombstone_blob(env):
    gone = env.add("mem://fact/gone", "beta forgotten unit")
    project_corpus(env.conn, env.registry, blob_store=env.blobs)
    # a tombstone whose bytes WOULD yield a searchable unit if it were extracted
    tomb = tombstone(env, gone, body="searchable tombstone words")
    project_source(env.conn, env.registry, tomb, blob_store=env.blobs)
    env.conn.commit()
    assert env.units() == [] and env.fts_rows() == 0


def test_full_projection_of_a_registry_with_a_tombstone_has_no_units(env):
    gone = env.add("mem://fact/gone", "beta forgotten unit")
    tombstone(env, gone)
    report = project_corpus(env.conn, env.registry, blob_store=env.blobs)
    env.conn.commit()
    assert env.units() == [] and report.units_projected == 0 and report.extractions_failed == 0


def test_rebuild_from_corpus_keeps_a_forgotten_source_forgotten(env):
    env.add("mem://fact/keep", "alpha keep unit")
    gone = env.add("mem://fact/gone", "beta forgotten unit")
    tombstone(env, gone)
    rebuild_from_corpus(env.conn, env.registry, blob_store=env.blobs)
    assert env.units() == ["alpha keep unit"]
    assert source_status(env.conn, gone.source_id)["status"] == "deleted"


def test_raw_blobs_of_earlier_versions_are_kept(env):
    gone = env.add("mem://fact/gone", "beta forgotten unit")
    tombstone(env, gone)
    assert env.blobs.exists(gone.blob_ref) and env.blobs.get(gone.blob_ref) == b"beta forgotten unit"
    lines = [json.loads(x) for x in (env.root / "corpus_sources.jsonl").read_text().splitlines()]
    assert [r["lifecycle_status"] for r in lines] == ["observed", "deleted"]
    assert lines[1]["supersedes"] == lines[0]["source_version_id"]


def test_re_adding_the_original_bytes_after_a_tombstone_is_a_new_version_and_resurrects(env):
    gone = env.add("mem://fact/gone", "beta forgotten unit")
    tombstone(env, gone)
    again = env.add("mem://fact/gone", "beta forgotten unit")
    tomb_line = json.loads((env.root / "corpus_sources.jsonl").read_text().splitlines()[1])
    # identity is content-addressed, so the resurrected version reuses v1's version id; the chain order
    # (``supersedes`` = the tombstone) is what distinguishes it
    assert again.lifecycle_status == "observed" and again.supersedes == tomb_line["source_version_id"]
    project_source(env.conn, env.registry, again, blob_store=env.blobs)
    env.conn.commit()
    assert env.units() == ["beta forgotten unit"]


def test_stale_record_for_a_forgotten_source_does_not_resurrect_it(env):
    gone = env.add("mem://fact/gone", "beta forgotten unit")
    project_source(env.conn, env.registry, gone, blob_store=env.blobs)
    tombstone(env, gone)
    # a caller still holding the old record cannot regress the derived state
    project_source(env.conn, env.registry, gone, blob_store=env.blobs)
    env.conn.commit()
    assert env.units() == []


def test_upgrade_guard_does_not_count_forgotten_sources_as_an_empty_projection(env, tmp_path):
    """A store whose every source is forgotten has sources but zero units; ``zero-mem upgrade``
    must not refuse it as ``CORPUS_PROJECTION_EMPTY``."""
    from zero_mem import upgrade as upgrade_mod

    gone = env.add("mem://fact/gone", "beta forgotten unit")
    tombstone(env, gone)
    project_corpus(env.conn, env.registry, blob_store=env.blobs)
    env.conn.commit()
    db = tmp_path / "d.sqlite3"
    assert upgrade_mod._corpus_counts(db, immutable=False) == (0, 0)
    upgrade_mod._guard_corpus_projection(db, db)  # must not raise


def test_upgrade_guard_still_refuses_live_sources_that_produced_no_units(env, tmp_path):
    from zero_mem import upgrade as upgrade_mod

    env.add("mem://fact/live", "alpha live unit")
    project_corpus(env.conn, env.registry, blob_store=env.blobs)
    env.conn.execute("DELETE FROM zm_corpus_fts")
    env.conn.execute("DELETE FROM zm_corpus_units")
    env.conn.commit()
    db = tmp_path / "d.sqlite3"
    assert upgrade_mod._corpus_counts(db, immutable=False) == (1, 0)
    with pytest.raises(upgrade_mod.UpgradeError):
        upgrade_mod._guard_corpus_projection(db, db)
