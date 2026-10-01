"""T7 - ``Memory.recall`` reuses one read-only connection instead of re-opening (and re-hashing) the database per call.

``open_readonly`` fingerprints the whole derived database file twice per open (identity fence); on a 13k-unit store that
was 28 ms of every recall.  The connection is reused while the file is the same (device, inode); a replaced file
(``zero-mem upgrade``, restore) is reopened, and every other read-side guarantee is unchanged: grants and new writes are
read through the same connection on every call.
"""
from __future__ import annotations

import os
import sqlite3
import threading

import pytest

from tests.unit.t5_memory_helpers import SHARED, Env


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.close()


@pytest.fixture
def opens(monkeypatch):
    import src.retrieval.db as db

    real = db.open_readonly
    calls = []

    def spy(path):
        calls.append(path)
        return real(path)

    monkeypatch.setattr(db, "open_readonly", spy)
    return calls


def test_consecutive_recalls_open_the_database_once(env, opens):
    m = env.open("claude-code")
    m.add("quokkas live in Western Australia")
    for _ in range(4):
        assert m.recall("quokkas").status == "ok"
    assert len(opens) == 1


def test_context_and_recall_share_the_connection(env, opens):
    m = env.open("claude-code")
    m.add("persona facet about terse answers", "persona")
    m.recall("terse")
    m.context()
    m.recall("terse")
    assert len(opens) == 1


def test_a_write_after_a_recall_is_visible_to_the_next_recall(env):
    m = env.open("claude-code")
    m.add("first note about wombats")
    assert len(m.recall("wombats", limit=10)) == 1
    m.add("second note about wombats")
    assert len(m.recall("wombats", limit=10)) == 2


def test_a_revoked_grant_is_effective_on_the_very_next_recall(env):
    a = env.agent("claude-code", write_shared=True)
    b = env.agent("codex")
    a.add("shared about pangolins", scope="shared")
    assert b.recall("pangolins").status == "ok"
    env.prov.revoke("codex", space=SHARED, operation="READ")
    assert b.recall("pangolins").status == "empty"
    env.prov.grant_read("codex", space=SHARED)
    assert b.recall("pangolins").status == "ok"


def _swap_in_a_rebuilt_database(memory, keep_units: bool) -> None:
    """What ``zero-mem upgrade`` does: build a new database file and atomically replace the old one."""
    db = memory.layout.derived_db
    staged = db.with_name(db.name + ".staged")
    src = sqlite3.connect(db)
    src.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # no stale WAL frames may follow the old file's inode
    dst = sqlite3.connect(staged)
    src.backup(dst)
    if not keep_units:
        dst.execute("DELETE FROM zm_corpus_units")
        dst.execute("DELETE FROM zm_corpus_fts")
        dst.commit()
    src.close()
    dst.close()
    os.replace(staged, db)


def test_a_replaced_database_file_is_reopened(env, opens):
    m = env.open("claude-code")
    m.add("tapirs live in forests")
    assert m.recall("tapirs").status == "ok"
    _swap_in_a_rebuilt_database(m, keep_units=False)
    assert m.recall("tapirs").status == "empty"  # a stale connection would still answer from the old inode
    assert len(opens) == 2


def test_close_releases_the_connection_and_a_later_recall_reopens(env, opens):
    m = env.open("claude-code")
    m.add("marmots hibernate")
    assert m.recall("marmots").status == "ok"
    m.close()
    assert m._ro is None
    assert m.recall("marmots").status == "ok"
    assert len(opens) == 2
    m.close()


def test_concurrent_recalls_are_serialized_and_consistent(env):
    m = env.open("claude-code")
    for i in range(20):
        m.add(f"capybara fact number {i}")
    errors: list = []
    results: list = []

    def worker():
        try:
            for _ in range(10):
                results.append(len(m.recall("capybara", limit=50)))
        except Exception as exc:  # pragma: no cover - a failure is the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and set(results) == {20}


def test_a_missing_database_still_reports_a_typed_error(env, opens):
    m = env.open("claude-code")
    m.add("something")
    assert m.recall("something").status == "ok"
    m.layout.derived_db.unlink()
    res = m.recall("something")
    assert res.status in ("error", "empty") and not res.hits
