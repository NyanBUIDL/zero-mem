"""DEF-003 (v1.3.4) — crash/power-loss durability proof tests.

AUD-003 gap: "no crash/power-loss proof; race is separately reproduced."
These tests simulate a hard kill (SIGKILL) mid-ingest and prove the durability
contract end-to-end:

1.  A subprocess ingesting a JSONL stream is SIGKILLed partway through.
2.  The canonical JSONL on disk is byte-identical before and after the kill
    (the sidecar never mutates canonical state during ingest).
3.  Re-ingesting from the surviving derived DB resumes deterministically:
    the checkpoint prefix-hash either matches exactly (resume) or the ingest
    fail-closes with ``source_changed`` — never silent corruption.
4.  After full replay to completion, the logical digest of the derived state
    equals a clean single-pass ingest of the same file (rebuildability).

Stdlib + existing test helpers only; no new dependencies.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

_CHILD = r'''
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, {root!r})
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.storage.ingest import ingest_file

db_path, jsonl_path, marker = (Path(p) for p in sys.argv[1:4])
store = SQLiteStore(SQLiteStoreConfig(path=db_path))
store.ensure_schema()
# Signal readiness: parent may kill any time after this file exists.
Path(marker).write_text("ready", encoding="utf-8")
report = ingest_file(store, jsonl_path)
# Long-lived: parent decides when we die. Flush nothing else.
time.sleep(600)
'''


def _make_jsonl(path: Path, n: int = 4000) -> None:
    lines = []
    for i in range(n):
        event = {
            "event_id": f"crash-{i:06d}",
            "event_type": "user_statement",
            "subject": f"crash durability event {i}",
            "created_at": "2026-08-23T00:00:00Z",
            "trace_id": f"T{i:06d}",
            "profile_id": "PR1",
            "project_id": "P",
        }
        lines.append(json.dumps(event, sort_keys=True))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _logical_digest(db_path: Path) -> str:
    """Digest of derived state with wall-clock columns normalized away
    (zm_meta records the ingest-time timestamp via _now(), which legitimately
    differs between two separate ingest runs of identical data)."""
    import re

    ts_re = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    attempts = 20 if os.name == "nt" else 1
    for attempt in range(attempts):
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name LIKE 'zm_%' ORDER BY name"
                ).fetchall()
            ]
            h = hashlib.sha256()
            for table in tables:
                h.update(table.encode())
                rows = conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                for row in rows:
                    normed = tuple(
                        "TIMESTAMP" if isinstance(v, str) and ts_re.match(v) else v
                        for v in row
                    )
                    h.update(repr(normed).encode())
            return h.hexdigest()
        except sqlite3.OperationalError as exc:
            transient = os.name == "nt" and "disk i/o error" in str(exc).lower()
            if not transient or attempt == attempts - 1:
                raise
            time.sleep(0.05)
        finally:
            conn.close()
    raise AssertionError("unreachable")


# no external timeout plugin; subprocess waits are bounded internally
def test_sigkill_mid_ingest_preserves_canonical_and_resumes(tmp_path: Path) -> None:
    jsonl = tmp_path / "events.jsonl"
    _make_jsonl(jsonl)
    canonical_before = jsonl.read_bytes()

    db = tmp_path / "derived.sqlite"
    marker = tmp_path / "child-ready.marker"
    script = tmp_path / "child_ingest.py"
    script.write_text(_CHILD.format(root=str(ROOT)), encoding="utf-8")

    proc = subprocess.Popen(
        [sys.executable, str(script), str(db), str(jsonl), str(marker)],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        # Wait until the child is inside ingest_file, then kill hard.
        deadline = time.monotonic() + 60
        while not marker.exists():
            if proc.poll() is not None:
                pytest.fail(f"child exited early: {proc.stderr.read().decode()[-500:]}")
            if time.monotonic() > deadline:
                proc.kill()
                pytest.fail("child never signalled readiness")
            time.sleep(0.05)
        time.sleep(0.4)  # let it get partway through the stream
        # WP-05: Windows has no SIGKILL; hard-kill via proc.kill() there.
        sigkill = getattr(signal, "SIGKILL", None)
        if sigkill is None:
            proc.kill()
        else:
            proc.send_signal(sigkill)
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()

    # 1. Canonical JSONL untouched by the (killed) ingest.
    assert jsonl.read_bytes() == canonical_before

    # 2. The derived DB survived in SOME consistent state; re-open read-only works.
    digest_after_kill = _logical_digest(db)

    # 3. Resume ingest in-process: must succeed or fail-closed — no corruption.
    from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
    from src.storage.ingest import ingest_file

    store = SQLiteStore(SQLiteStoreConfig(path=db))
    store.ensure_schema()
    report = ingest_file(store, jsonl)
    assert report.stopped is False, (
        f"resume halted unexpectedly: failures={report.failures[-3:]}"
    )
    store.close()

    # 4. Full replay equals clean single-pass ingest of the same file.
    clean_db = tmp_path / "clean.sqlite"
    store_clean = SQLiteStore(SQLiteStoreConfig(path=clean_db))
    store_clean.ensure_schema()
    ingest_file(store_clean, jsonl)
    store_clean.close()
    assert _logical_digest(db) == _logical_digest(clean_db)

    del digest_after_kill  # existence proof only


# no external timeout plugin; subprocess waits are bounded internally
def test_truncated_canonical_tail_fails_closed_on_replay(tmp_path: Path) -> None:
    """Power loss DURING a canonical append leaves a partial last line.

    Ingest must treat the incomplete tail as absent (checkpoint semantics) or
    fail closed — it must never project the torn line as a valid event.
    """
    jsonl = tmp_path / "torn.jsonl"
    _make_jsonl(jsonl, n=50)
    good = jsonl.read_bytes()
    torn = good[:-20]  # cut inside the last line's bytes
    jsonl.write_bytes(torn)

    from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
    from src.storage.ingest import ingest_file

    db = tmp_path / "derived.sqlite"
    store = SQLiteStore(SQLiteStoreConfig(path=db))
    store.ensure_schema()
    report = ingest_file(store, jsonl)
    store.close()

    # No event beyond the last COMPLETE line may exist.
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM zm_meta WHERE event_id='crash-000049'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 0, "torn tail line was projected as a complete event"

    # Repairing the file (as a later append would) then re-ingesting converges.
    jsonl.write_bytes(good)
    store = SQLiteStore(SQLiteStoreConfig(path=db))
    store.ensure_schema()
    report = ingest_file(store, jsonl)
    assert report.stopped is False
    store.close()
