"""Importable (spawn-safe) worker functions for tests/unit/test_t2_corpus_storage.py."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path


def blob_put(root: str, content: bytes, barrier, out) -> None:
    from src.corpus.blob_store import CorpusBlobStore

    try:
        store = CorpusBlobStore(root=Path(root))
        barrier.wait(30)
        digest = store.put(content=content, source_ref="t2")
        out.put(("ok", digest))
    except BaseException as exc:  # noqa: BLE001 - report every failure to the parent
        out.put(("error", f"{type(exc).__name__}: {exc}"))


def register_same(root: str, content: bytes, ref: str, barrier, out) -> None:
    """Every process registers the same logical source + bytes."""
    from src.corpus.registry import CorpusSourceRegistry

    try:
        registry = CorpusSourceRegistry(root=Path(root))  # snapshot taken BEFORE the barrier
        barrier.wait(30)
        rec = registry.register_source_with_blob(
            content=content, external_ref=ref, kind="txt", profile_id="p1")
        out.put(("ok", rec.source_version_id))
    except BaseException as exc:  # noqa: BLE001
        out.put(("error", f"{type(exc).__name__}: {exc}"))


def register_many(root: str, worker: int, count: int, shared_ref: str, barrier, out) -> None:
    """Each process registers ``count`` private sources plus one shared source."""
    from src.corpus.registry import CorpusSourceRegistry

    try:
        registry = CorpusSourceRegistry(root=Path(root))
        barrier.wait(30)
        for i in range(count):
            registry.register_source_with_blob(
                content=f"worker {worker} doc {i} " .encode() * 40,
                external_ref=f"mem://w{worker}/{i}", kind="txt", profile_id="p1")
        registry.register_source_with_blob(
            content=b"shared persona facet\n", external_ref=shared_ref, kind="txt", profile_id="p1")
        out.put(("ok", worker))
    except BaseException as exc:  # noqa: BLE001
        out.put(("error", f"{type(exc).__name__}: {exc}"))


def rebuild_loop(db_path: str, corpus_root: str, rounds: int, out) -> None:
    """Writer: rebuild the derived corpus tables in place ``rounds`` times."""
    from src.corpus.blob_store import CorpusBlobStore
    from src.corpus.derived_store import rebuild_from_corpus
    from src.corpus.registry import CorpusSourceRegistry
    from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig

    try:
        store = SQLiteStore(SQLiteStoreConfig(path=Path(db_path)))
        registry = CorpusSourceRegistry(root=Path(corpus_root))
        blobs = CorpusBlobStore(root=Path(corpus_root))
        out.put(("ready", 0))
        for _ in range(rounds):
            rebuild_from_corpus(store._conn, registry, blob_store=blobs)
            store._conn.commit()
        store.close()
        out.put(("done", rounds))
    except BaseException as exc:  # noqa: BLE001
        out.put(("error", f"{type(exc).__name__}: {exc}"))


def read_loop(db_path: str, expected_sources: int, expected_units: int, stop, out) -> None:
    """Reader: count empty / partial / erroring snapshots until ``stop`` is set."""
    from src.retrieval.db import open_readonly

    reads = empty = partial = errors = 0
    first_error = ""
    ro = None
    try:
        out.put(("ready", 0))
        while not stop.is_set():
            try:
                ro = open_readonly(Path(db_path))
                conn = ro.conn
                conn.execute("BEGIN")  # one explicit read transaction == one consistent snapshot
                try:
                    n_units = conn.execute("SELECT COUNT(*) FROM zm_corpus_units").fetchone()[0]
                    n_fts = conn.execute("SELECT COUNT(*) FROM zm_corpus_fts").fetchone()[0]
                    n_src = conn.execute("SELECT COUNT(*) FROM zm_corpus_sources").fetchone()[0]
                finally:
                    conn.rollback()
                reads += 1
                if n_units == 0 and n_src == 0:
                    empty += 1
                elif (n_src, n_units, n_fts) != (expected_sources, expected_units, expected_units):
                    partial += 1
            except Exception as exc:  # noqa: BLE001 - every reader failure counts
                errors += 1
                first_error = first_error or f"{type(exc).__name__}: {exc}"
            finally:
                if ro is not None:
                    try:
                        ro.close()
                    except Exception:  # noqa: BLE001
                        pass
                    ro = None
            time.sleep(0.001)
        out.put(("result", {"reads": reads, "empty": empty, "partial": partial,
                            "errors": errors, "first_error": first_error}))
    except BaseException as exc:  # noqa: BLE001
        out.put(("error", f"{type(exc).__name__}: {exc}"))
