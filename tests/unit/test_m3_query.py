"""M3.1 focused tests — query contract and structured read-only filters.

Mirrors the verified M2 envelope/tombstone shapes (no hand-rolled schemas). Builds a
derived SQLite store via M2's own ingestion, then queries it exclusively through the
M3 read-only layer (`src/retrieval`). Proves M3 does not mutate JSONL or derived state.

Run: .venv/bin/python -m pytest tests/unit/test_m3_query.py -q
"""

from __future__ import annotations

import hashlib
import json
import socket
import sqlite3
import subprocess
from pathlib import Path

import pytest

from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.storage.ingest import ingest_file, rebuild_from_jsonl

import src.retrieval as r
from src.retrieval import db as rdb
from src.retrieval.models import (
    INVALID_TIME_RANGE,
    QueryError,
    QueryRequest,
    UNSUPPORTED_FILTER,
)

TS = "2026-01-01T00:00:00Z"


# ---- corpus builders (verified M2 envelope shape) -------------------------

def _make_env(event_id, **over):
    base = dict(
        event_id=event_id,
        trace_id=f"tr-{event_id}",
        event_type="tool_observation",
        source="pre_tool_call",
        schema_version=1,
        created_at=TS,
        observed_at=TS,
        sequence=0,
        lifecycle_status="observed",
        verification_status="none",
        confidence="medium",
        sensitivity="internal",
        retention="persistent",
        sanitized_content_hash=f"h-{event_id}",
        sanitized_content={"text": f"clean content for {event_id}"},
        redaction_audit=[],
    )
    base.update(over)
    return base


def _make_tombstone(tomb_id, target, **over):
    env = _make_env(
        tomb_id,
        event_type="system_event",
        lifecycle_status="deleted",
        trace_id=f"tr-{tomb_id}",
        sanitized_content={"text": f"delete {target}"},
    )
    env["deletion"] = {"target_event_id": target}
    if "deletion" in over:
        env["deletion"].update(over.pop("deletion"))
    env.update(over)
    return env


def _write_jsonl(path: Path, items) -> None:
    path.write_text("\n".join(json.dumps(i) for i in items) + "\n")


def _open_store(tmp_path: Path, name: str = "m.sqlite") -> SQLiteStore:
    store = SQLiteStore(SQLiteStoreConfig(path=tmp_path / name))
    store.ensure_schema()
    return store


def _checkpoint_and_close(store: SQLiteStore) -> None:
    """Force WAL checkpoint so a later read-only reopen sees all committed rows."""
    try:
        store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        store._conn.commit()
    except sqlite3.Error:
        pass
    store.close()


def _ingest_corpus(tmp_path: Path, name: str = "m.sqlite") -> SQLiteStore:
    """Build + ingest the corpus, then checkpoint so a read-only reopen is consistent.

    Returns the SAME store object (built + checkpointed, still open). Reopening a
    second *write* store under WAL mode would truncate the WAL and lose committed
    rows, so callers must use this store (or open a separate read-only connection
    via `r.open_readonly(store.path)`) rather than reopening a write store.
    """
    jl = tmp_path / "corpus.jsonl"
    _build_corpus(jl)
    store = _open_store(tmp_path, name)
    rebuild_from_jsonl(store, [jl])
    try:
        store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        store._conn.commit()
    except sqlite3.Error:
        pass
    return store


def _build_corpus(path: Path) -> None:
    """Representative corpus: varied metadata across traces/projects/profiles/sessions."""
    items = [
        _make_env("e1", project_id="P", profile_id="A", session_id="S1",
                  created_at="2026-01-01T00:00:00Z", observed_at="2026-01-01T00:00:00Z",
                  verification_status="deterministic_verification"),
        _make_env("e2", project_id="P", profile_id="A", session_id="S1",
                  event_type="user_statement", created_at="2026-01-02T00:00:00Z",
                  observed_at="2026-01-02T00:00:00Z"),
        _make_env("e3", project_id="P", profile_id="B", session_id="S2",
                  created_at="2026-01-03T00:00:00Z", observed_at="2026-01-03T00:00:00Z",
                  retention="temporary"),
        _make_env("e4", project_id="Q", profile_id="A", session_id="S1",
                  created_at="2026-01-04T00:00:00Z", observed_at="2026-01-04T00:00:00Z",
                  lifecycle_status="archived"),
        _make_env("e5", project_id="Q", profile_id="B", session_id="S2",
                  created_at="2026-01-05T00:00:00Z", observed_at="2026-01-05T00:00:00Z",
                  verification_status="user_confirmation"),
        _make_env("e6", project_id="P", profile_id="A", session_id="S3", task_id="T1",
                  turn_id="U1", parent_trace_id="tr-e1",
                  created_at="2026-01-06T00:00:00Z", observed_at="2026-01-06T00:00:00Z"),
        # e7 deliberately has NO session/profile/project/task/turn (NULL identities).
        _make_env("e7", created_at="2026-01-07T00:00:00Z", observed_at="2026-01-07T00:00:00Z"),
    ]
    _write_jsonl(path, items)


# ---- read-only Snapshot proof ---------------------------------------------

DERIVED_TABLES = (
    "zm_meta", "zm_lifecycle", "zm_provenance", "zm_ingest_checkpoint",
    "zm_ingest_log", "zm_relations", "zm_scopes", "zm_artifacts",
    "zm_tombstones", "zm_deletion_audit", "zm_migrations",
)


class Snapshot:
    """Objective before/after proof that M3 queries do not mutate derived state."""

    def __init__(self, store: SQLiteStore, jsonl: Path):
        self._conn = store._conn
        self._jsonl = jsonl
        self.schema_hash = self._schema_ddl_hash()
        self.counts = {t: self._count(t) for t in DERIVED_TABLES}
        self.meta_hash = self._meta_content_hash()
        self.jsonl_sha = self._jsonl_sha()
        self.db_size = self._db_size(store.path)

    def _schema_ddl_hash(self) -> str:
        rows = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name"
        ).fetchall()
        blob = "\n".join(r["sql"] for r in rows)
        return hashlib.sha256(blob.encode()).hexdigest()

    def _count(self, table: str) -> int:
        try:
            return int(self._conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])
        except sqlite3.Error:
            return -1

    def _meta_content_hash(self) -> str:
        cols = ", ".join(
            c for c in (
                "event_id", "trace_id", "event_type", "source", "created_at", "observed_at",
                "session_id", "profile_id", "project_id", "task_id", "turn_id",
                "parent_trace_id", "lifecycle_status", "verification_status", "retention",
                "content_hash",
            )
        )
        rows = self._conn.execute(f"SELECT {cols} FROM zm_meta ORDER BY event_id").fetchall()
        blob = "\n".join("|".join("" if r[c] is None else str(r[c]) for c in cols.split(", ")) for r in rows)
        return hashlib.sha256(blob.encode()).hexdigest()

    def _jsonl_sha(self) -> str:
        return hashlib.sha256(self._jsonl.read_bytes()).hexdigest()

    def _db_size(self, path: Path) -> int:
        total = 0
        for p in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
            if p.exists():
                total += p.stat().st_size
        return total

    def assert_unchanged(self, other: "Snapshot") -> None:
        assert self.schema_hash == other.schema_hash, "schema DDL changed"
        assert self.counts == other.counts, "row counts changed"
        assert self.meta_hash == other.meta_hash, "zm_meta content changed"
        assert self.jsonl_sha == other.jsonl_sha, "JSONL bytes changed"
        # DB file size may fluctuate from WAL trim; allow only small variance.
        assert abs(self.db_size - other.db_size) <= 4096, "DB file size changed unexpectedly"


# ---- true read-only connection --------------------------------------------

def test_readonly_open(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    assert rs.get_schema_version() == 9
    rs.close()
    store.close()


def test_query_only_enabled(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    assert rdb._readonly_conn_is_query_only(rs) is True
    rs.close()
    store.close()


def test_schema_validation_readonly(tmp_path: Path) -> None:
    """Schema check is SELECT-only: it does not call ensure_schema/migrations."""
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    assert rs.validate_schema() == 9
    rs.close()
    store.close()


def test_schema_mismatch_rejected(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    store._conn.execute("INSERT INTO zm_migrations(version, applied_at, note) VALUES (99, 'x', 'test')")
    store._conn.commit()
    store.close()
    with pytest.raises(QueryError) as exc:
        r.open_readonly(store.path)
    assert exc.value.code == "schema_mismatch"
    store.close()


def test_database_unavailable_missing(tmp_path: Path) -> None:
    with pytest.raises(QueryError) as exc:
        r.open_readonly(tmp_path / "does-not-exist.sqlite")
    assert exc.value.code == "database_unavailable"


# ---- exact lookups ---------------------------------------------------------

def test_exact_event_lookup(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    view = r.get_event(rs, "e1")
    assert view is not None
    assert view.event_id == "e1"
    assert view.project_id == "P"
    assert view.content_source == "metadata_only"
    rs.close()
    store.close()


def test_exact_event_lookup_missing(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    assert r.get_event(rs, "nope") is None
    rs.close()
    store.close()


def test_trace_lookup(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    views = r.get_trace(rs, "tr-e1")
    assert [v.event_id for v in views] == ["e1"]
    rs.close()
    store.close()


# ---- structured filters ---------------------------------------------------

def test_event_type_filter(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    res = r.query_events(rs, QueryRequest(event_type="user_statement"))
    assert [v.event_id for v in res.items] == ["e2"]
    rs.close()
    store.close()


def test_source_filter(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    res = r.query_events(rs, QueryRequest(source="pre_tool_call"))
    assert len(res.items) == 7
    rs.close()
    store.close()


def test_session_filter(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    res = r.query_events(rs, QueryRequest(session_id="S1"))
    assert sorted(v.event_id for v in res.items) == ["e1", "e2", "e4"]
    rs.close()
    store.close()


def test_profile_filter(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    res = r.query_events(rs, QueryRequest(profile_id="A"))
    assert sorted(v.event_id for v in res.items) == ["e1", "e2", "e4", "e6"]
    rs.close()
    store.close()


def test_project_filter(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    res = r.query_events(rs, QueryRequest(project_id="P"))
    assert sorted(v.event_id for v in res.items) == ["e1", "e2", "e3", "e6"]
    rs.close()
    store.close()


def test_task_filter(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    res = r.query_events(rs, QueryRequest(task_id="T1"))
    assert [v.event_id for v in res.items] == ["e6"]
    rs.close()
    store.close()


def test_turn_filter(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    res = r.query_events(rs, QueryRequest(turn_id="U1"))
    assert [v.event_id for v in res.items] == ["e6"]
    rs.close()
    store.close()


def test_parent_trace_filter(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    res = r.query_events(rs, QueryRequest(parent_trace_id="tr-e1"))
    assert [v.event_id for v in res.items] == ["e6"]
    rs.close()
    store.close()


def test_lifecycle_filter(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    res = r.query_events(rs, QueryRequest(lifecycle_status="archived"))
    assert [v.event_id for v in res.items] == ["e4"]
    rs.close()
    store.close()


def test_verification_filter(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    res = r.query_events(rs, QueryRequest(verification_status="deterministic_verification"))
    assert [v.event_id for v in res.items] == ["e1"]
    rs.close()
    store.close()


def test_retention_filter(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    res = r.query_events(rs, QueryRequest(retention="temporary"))
    assert [v.event_id for v in res.items] == ["e3"]
    rs.close()
    store.close()


# ---- time ranges ----------------------------------------------------------

def test_created_at_range(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    res = r.query_events(rs, QueryRequest(
        created_at_after="2026-01-03T00:00:00Z", created_at_before="2026-01-05T00:00:00Z"))
    assert sorted(v.event_id for v in res.items) == ["e3", "e4", "e5"]
    rs.close()
    store.close()


def test_observed_at_range(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    res = r.query_events(rs, QueryRequest(observed_at_after="2026-01-06T00:00:00Z"))
    assert [v.event_id for v in res.items] == ["e6", "e7"]
    rs.close()
    store.close()


def test_invalid_time_range(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    with pytest.raises(QueryError) as exc:
        r.query_events(rs, QueryRequest(created_at_after="not-a-timestamp!!"))
    assert exc.value.code == INVALID_TIME_RANGE
    rs.close()
    store.close()


# ---- combined / deterministic / empty -------------------------------------

def test_combined_and(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    res = r.query_events(rs, QueryRequest(project_id="P", profile_id="A", session_id="S1"))
    assert sorted(v.event_id for v in res.items) == ["e1", "e2"]
    rs.close()
    store.close()


def test_deterministic_ordering(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    res1 = r.query_events(rs, QueryRequest(project_id="P"))
    res2 = r.query_events(rs, QueryRequest(project_id="P"))
    order1 = [v.event_id for v in res1.items]
    order2 = [v.event_id for v in res2.items]
    assert order1 == order2
    # Stable sort key is (created_at ASC, event_id ASC).
    assert order1 == ["e1", "e2", "e3", "e6"]
    rs.close()
    store.close()


def test_zero_result_success(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    res = r.query_events(rs, QueryRequest(project_id="ZZZ-nonexistent"))
    assert res.items == []
    assert res.total == 0
    rs.close()
    store.close()


# ---- deleted exclusion -----------------------------------------------------

def test_deleted_exclusion(tmp_path: Path) -> None:
    jl = tmp_path / "corpus.jsonl"
    _write_jsonl(jl, [
        _make_env("a", project_id="P", created_at="2026-01-01T00:00:00Z"),
        _make_env("b", project_id="P", created_at="2026-01-02T00:00:00Z"),
    ])
    store = _open_store(tmp_path)
    rebuild_from_jsonl(store, [jl])
    _write_jsonl(tmp_path / "del.jsonl", [_make_tombstone("d1", "a")])
    ingest_file(store, tmp_path / "del.jsonl")
    store.close()
    reopened = SQLiteStore(SQLiteStoreConfig(path=tmp_path / "m.sqlite"))
    rs = r.open_readonly(reopened.path)
    res = r.query_events(rs, QueryRequest(project_id="P"))
    assert [v.event_id for v in res.items] == ["b"]
    assert r.get_event(rs, "a") is None
    rs.close()
    reopened.close()


# ---- NULL identities ------------------------------------------------------

def test_null_identities_remain_null(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    view = r.get_event(rs, "e7")
    assert view is not None
    assert view.session_id is None
    assert view.profile_id is None
    assert view.project_id is None
    assert view.task_id is None
    assert view.turn_id is None
    rs.close()
    store.close()


# ---- errors ---------------------------------------------------------------

def test_unsupported_filter(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    with pytest.raises(QueryError) as exc:
        r.query_events(rs, QueryRequest(lifecycle_status="deleted"))
    assert exc.value.code == UNSUPPORTED_FILTER
    rs.close()
    store.close()


def test_invalid_query_non_string(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    with pytest.raises(QueryError) as exc:
        r.query_events(rs, QueryRequest(event_id=123))  # type: ignore[arg-type]
    assert exc.value.code == "invalid_query"
    rs.close()
    store.close()


def test_sanitized_error_codes(tmp_path: Path) -> None:
    """Unknown filter names / bad input map to fixed codes; no raw SQL text."""
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    codes = set()
    for fn in (
        lambda: r.query_events(rs, QueryRequest(lifecycle_status="deleted")),
        lambda: r.query_events(rs, QueryRequest(created_at_after="bad")),
        lambda: r.query_events(rs, QueryRequest(event_id=5)),  # type: ignore[arg-type]
    ):
        try:
            fn()
        except QueryError as e:
            codes.add(e.code)
            assert "SELECT" not in str(e) and "sqlite3." not in str(e)
    assert UNSUPPORTED_FILTER in codes
    assert INVALID_TIME_RANGE in codes
    assert "invalid_query" in codes
    rs.close()
    store.close()


# ---- secret safety --------------------------------------------------------

def test_secret_absence(tmp_path: Path) -> None:
    secret = "SK-M3-SECRET-XYZ"
    jl = tmp_path / "corpus.jsonl"
    _write_jsonl(jl, [
        _make_env("s1", project_id="P", sanitized_content={"text": f"normal {secret} embedded"}),
    ])
    store = _open_store(tmp_path)
    rebuild_from_jsonl(store, [jl])
    store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    store._conn.commit()
    rs = r.open_readonly(store.path)
    view = r.get_event(rs, "s1")
    assert view is not None
    # M3.1 is metadata-only: sanitized_content is NOT returned, so the secret is absent.
    blob = json.dumps(view.__dict__, default=str)
    assert secret not in blob
    rs.close()


# ---- read-only proof (before/after) ---------------------------------------

def test_readonly_no_mutation(tmp_path: Path) -> None:
    jl = tmp_path / "corpus.jsonl"
    _build_corpus(jl)
    store = _open_store(tmp_path)
    rebuild_from_jsonl(store, [jl])
    store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    store._conn.commit()
    snap_before = Snapshot(store, jl)

    rs = r.open_readonly(store.path)
    r.query_events(rs, QueryRequest(project_id="P"))
    r.query_events(rs, QueryRequest(profile_id="A", verification_status="deterministic_verification"))
    r.get_event(rs, "e1")
    r.get_trace(rs, "tr-e1")
    r.list_session(rs, "S1")
    r.list_project(rs, "Q")
    r.list_profile(rs, "B")
    r.query_events(rs, QueryRequest(created_at_after="2026-01-03T00:00:00Z"))
    rs.close()

    # Snapshot AFTER on the same (still-open) connection — no reopen that could
    # truncate the WAL and mask a real comparison.
    snap_after = Snapshot(store, jl)
    snap_before.assert_unchanged(snap_after)
    store.close()


def test_jsonl_unchanged(tmp_path: Path) -> None:
    jl = tmp_path / "corpus.jsonl"
    _build_corpus(jl)
    sha_before = hashlib.sha256(jl.read_bytes()).hexdigest()
    store = _open_store(tmp_path)
    rebuild_from_jsonl(store, [jl])
    store.close()
    rs = r.open_readonly(store.path)
    r.query_events(rs, QueryRequest(project_id="P"))
    r.get_event(rs, "e1")
    rs.close()
    assert hashlib.sha256(jl.read_bytes()).hexdigest() == sha_before


def test_sqlite_rows_unchanged(tmp_path: Path) -> None:
    jl = tmp_path / "corpus.jsonl"
    _build_corpus(jl)
    store = _open_store(tmp_path)
    rebuild_from_jsonl(store, [jl])
    store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    store._conn.commit()
    before = {t: store._conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
              for t in DERIVED_TABLES}
    rs = r.open_readonly(store.path)
    r.query_events(rs, QueryRequest(project_id="P"))
    rs.close()
    after = {t: store._conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
             for t in DERIVED_TABLES}
    assert before == after
    store.close()


def test_schema_unchanged(tmp_path: Path) -> None:
    jl = tmp_path / "corpus.jsonl"
    _build_corpus(jl)
    store = _open_store(tmp_path)
    rebuild_from_jsonl(store, [jl])
    store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    store._conn.commit()
    before = store._conn.execute(
        "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name").fetchall()
    rs = r.open_readonly(store.path)
    r.query_events(rs, QueryRequest(project_id="P"))
    rs.close()
    after = store._conn.execute(
        "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name").fetchall()
    assert [r["sql"] for r in before] == [r["sql"] for r in after]
    store.close()


def test_checkpoint_unchanged(tmp_path: Path) -> None:
    jl = tmp_path / "corpus.jsonl"
    _build_corpus(jl)
    store = _open_store(tmp_path)
    rebuild_from_jsonl(store, [jl])
    store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    store._conn.commit()
    before = store._conn.execute("SELECT COUNT(*) AS n FROM zm_ingest_checkpoint").fetchone()["n"]
    rs = r.open_readonly(store.path)
    r.query_events(rs, QueryRequest(project_id="P"))
    rs.close()
    after = store._conn.execute("SELECT COUNT(*) AS n FROM zm_ingest_checkpoint").fetchone()["n"]
    assert before == after
    store.close()


def test_lifecycle_unchanged(tmp_path: Path) -> None:
    jl = tmp_path / "corpus.jsonl"
    _build_corpus(jl)
    store = _open_store(tmp_path)
    rebuild_from_jsonl(store, [jl])
    store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    store._conn.commit()
    before = store._conn.execute("SELECT COUNT(*) AS n FROM zm_lifecycle").fetchone()["n"]
    rs = r.open_readonly(store.path)
    r.query_events(rs, QueryRequest(project_id="P"))
    rs.close()
    after = store._conn.execute("SELECT COUNT(*) AS n FROM zm_lifecycle").fetchone()["n"]
    assert before == after
    store.close()


def test_tombstones_unchanged(tmp_path: Path) -> None:
    jl = tmp_path / "corpus.jsonl"
    _build_corpus(jl)
    store = _open_store(tmp_path)
    rebuild_from_jsonl(store, [jl])
    store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    store._conn.commit()
    before = store._conn.execute("SELECT COUNT(*) AS n FROM zm_tombstones").fetchone()["n"]
    rs = r.open_readonly(store.path)
    r.query_events(rs, QueryRequest(project_id="P"))
    rs.close()
    after = store._conn.execute("SELECT COUNT(*) AS n FROM zm_tombstones").fetchone()["n"]
    assert before == after
    store.close()


# ---- no LLM / network -----------------------------------------------------

def test_no_llm_calls(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    real_run = subprocess.run
    real_popen = subprocess.Popen

    def _blocked(*a, **k):
        raise AssertionError("M3.1 must not spawn subprocesses (LLM/network)")

    subprocess.run = _blocked  # type: ignore[assignment]
    subprocess.Popen = _blocked  # type: ignore[assignment]
    try:
        r.query_events(rs, QueryRequest(project_id="P"))
        r.get_event(rs, "e1")
    finally:
        subprocess.run = real_run
        subprocess.Popen = real_popen
    rs.close()
    store.close()


def test_no_network_calls(tmp_path: Path) -> None:
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)

    def _blocked_socket(*a, **k):
        raise AssertionError("M3.1 must not open sockets (network)")

    real_socket = socket.socket
    socket.socket = _blocked_socket  # type: ignore[assignment]
    try:
        r.query_events(rs, QueryRequest(project_id="P"))
    finally:
        socket.socket = real_socket
    rs.close()
    store.close()


# ---- no real ~/.hermes writes ---------------------------------------------

def test_no_real_hermes_home_writes(tmp_path: Path) -> None:
    real_home = Path.home() / ".hermes"
    baseline = ({p.relative_to(real_home) for p in real_home.rglob("*")}
                 if real_home.exists() else set())
    store = _ingest_corpus(tmp_path)
    rs = r.open_readonly(store.path)
    r.query_events(rs, QueryRequest(project_id="P"))
    r.get_event(rs, "e1")
    rs.close()
    store.close()
    after = ({p.relative_to(real_home) for p in real_home.rglob("*")}
              if real_home.exists() else set())
    new_files = after - baseline
    attributable = [n for n in new_files if n.suffix in (".sqlite", ".sqlite-wal", ".sqlite-shm", ".jsonl")]
    assert attributable == [], f"M3.1 wrote to real ~/.hermes: {attributable}"


# ---- scope boundaries -----------------------------------------------------

def test_no_m3_2_behavior(tmp_path: Path) -> None:
    """M3.1 exposes no pagination/cursor/FTS/ranking surfaces."""
    assert not hasattr(r.query, "search_text")
    assert not hasattr(r.query, "query_events_paginated")
    assert "cursor" not in dir(r.query)
    assert not any(f in QueryRequest.__dataclass_fields__ for f in ("cursor", "limit", "text", "fts"))


def test_no_m4_behavior(tmp_path: Path) -> None:
    """M3.1 introduces no M4 project-memory write or routing surface."""
    assert not hasattr(r, "write_memory")
    assert not hasattr(r, "route_query")
    assert not hasattr(r, "inject_context")


def test_module_level_no_schema_mutation_import() -> None:
    """Importing M3 must not import/apply migrations or touch the read-write store."""
    assert not hasattr(r, "ensure_schema")
    assert not hasattr(r, "rebuild_from_jsonl")
