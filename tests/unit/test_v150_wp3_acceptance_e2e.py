"""V150-WP3 acceptance — end-to-end through the REAL production path.

Full chain, no synthetic zm_meta rows and no hand-built service:

  canonical JSONL envelope (knowledge_space_id in payload)
    -> capture validation -> ingest_file (denormalize ks into zm_meta)
    -> read-only reopen
    -> _open_facade (real M6Runtime, env-configured corpus store)
    -> query_events with a knowledge-space grant
    => assert EXACTLY the granted rows surface; legacy NULL-ks rows stay hidden
       even though the corpus projection attests their member pair.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.storage.ingest import ingest_file
from tests.unit.test_m3_query import (
    TS,
    _checkpoint_and_close,
    _make_env,
    _open_store,
    _write_jsonl,
)


def _corpus_db(tmp_path: Path) -> Path:
    """Derived corpus DB whose projection ATTESTS the legacy row's pair —
    proving the deny for NULL-ks rows does not come from missing data."""
    p = tmp_path / "corpus-derived.sqlite"
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE zm_corpus_sources ("
        " source_id TEXT PRIMARY KEY, external_ref TEXT, kind TEXT,"
        " profile_id TEXT, project_id TEXT, knowledge_space_id TEXT)")
    conn.execute(
        "CREATE TABLE zm_corpus_units ("
        " unit_id TEXT PRIMARY KEY, source_ref TEXT, content_hash TEXT,"
        " profile_id TEXT, project_id TEXT, knowledge_space_id TEXT)")
    # Attest BOTH profiles as members of quant-theory — including the owner of
    # the legacy NULL-ks row. The resolver has every reason to authorize it;
    # canonical-first must still refuse.
    conn.execute(
        "INSERT INTO zm_corpus_sources VALUES"
        " ('s1','r1','txt','prof-A','proj-Q','quant-theory')")
    conn.commit()
    return p


class TestV150Wp3RealFacadeAcceptance:
    def test_full_chain_ingest_facade_grant(self, tmp_path, monkeypatch):
        from src.access.authorized_read import AuthorizedReadService
        from src.access.contracts import AccessRequest
        from src.access.grants import AuthorizedReadGrant
        from src.integration.m6 import handlers, runtime as rt

        # --- 1. Canonical JSONL with ks inside the envelopes -----------------
        items = [
            # in granted space, owned by another profile (cross-profile grant)
            _make_env("ev-in", project_id="proj-Q", profile_id="prof-A",
                      knowledge_space_id="quant-theory"),
            # same project as ev-in but different space (coarsening trap)
            _make_env("ev-other", project_id="proj-Q", profile_id="prof-A",
                      knowledge_space_id="ks-unrelated"),
            # legacy envelope without ks (canonical-first trap)
            _make_env("ev-legacy", project_id="proj-Q", profile_id="prof-A"),
            # owner's own event in the granted space (same-profile)
            _make_env("ev-mine", project_id="proj-M", profile_id="prof-B",
                      knowledge_space_id="quant-theory"),
        ]
        jl = tmp_path / "events.jsonl"
        _write_jsonl(jl, items)

        # --- 2. Real ingest: envelope ks denormalized into zm_meta ----------
        store = _open_store(tmp_path, "main.sqlite")
        ingest_file(store, jl)
        _checkpoint_and_close(store)

        # verify denormalization actually happened on the derived layer
        conn = sqlite3.connect(tmp_path / "main.sqlite")
        rows = dict(conn.execute(
            "SELECT event_id, knowledge_space_id FROM zm_meta").fetchall())
        conn.close()
        assert rows == {
            "ev-in": "quant-theory",
            "ev-other": "ks-unrelated",
            "ev-legacy": None,
            "ev-mine": "quant-theory",
        }, "ingest must denormalize envelope ks into zm_meta"

        # --- 3. REAL facade via env-configured M6Runtime ---------------------
        monkeypatch.setenv("ZM_M6_CORPUS_STORE_PATH",
                           str(_corpus_db(tmp_path)))
        r = rt.configure(tmp_path / "main.sqlite")
        try:
            req = handlers.M6Request(
                tool="memory_query",
                requesting_profile_id="prof-B",
                arguments={"knowledge_space_ids": ["quant-theory"]},
            ) if "arguments" in handlers.M6Request.__dataclass_fields__ else \
                handlers.M6Request(tool="memory_query",
                                   requesting_profile_id="prof-B")

            svc, sstore, _grants = handlers._open_facade(r, req)
            try:
                assert svc._corpus_conn is not None, (
                    "production construction must carry the corpus connection")

                request = AccessRequest(operation="READ",
                                        requesting_profile_id="prof-B",
                                        knowledge_space_ids=["quant-theory"])
                grant = AuthorizedReadGrant(
                    grant_id="g1", subject_profile="prof-B", operation="READ",
                    target_type="knowledge_space", target_id="quant-theory",
                    resource_types=["memory_event"])

                result = svc.query_events(request, grants=[grant])
                assert result.allowed
                seen = {v.event_id for v in result.items}

                # EXACT set — nothing more, nothing less:
                assert seen == {"ev-in", "ev-mine"}, (
                    f"per-row canonical authorization must surface exactly the "
                    f"granted-space rows; got {sorted(seen)}")

                # The two traps explicitly:
                assert "ev-other" not in seen, (
                    "DEF-010: same-project/different-space row must NOT leak "
                    "(coarsening regression guard)")
                assert "ev-legacy" not in seen, (
                    "DEF-011: NULL-ks row must NOT surface even though the "
                    "corpus projection attests its member pair")
            finally:
                svc.close()
        finally:
            rt.close_default()

    def test_owner_still_reads_own_unscoped_row(self, tmp_path):
        """The narrowing only affects the SPACE-GRANT channel: an owner reading
        their own unscoped event via implicit-local scope still works."""
        from src.retrieval.db import open_readonly

        items = [
            _make_env("mine-unscoped", project_id="proj-M",
                      profile_id="prof-B"),
        ]
        jl = tmp_path / "own.jsonl"
        _write_jsonl(jl, items)
        store = _open_store(tmp_path, "own.sqlite")
        ingest_file(store, jl)
        _checkpoint_and_close(store)

        ro = open_readonly(tmp_path / "own.sqlite")
        svc = AuthorizedReadService(ro, "prof-B", grant_conn=ro.conn,
                                    corpus_conn=None) if False else None
        from src.access.authorized_read import AuthorizedReadService as S
        from src.access.contracts import AccessRequest

        svc = S(ro, "prof-B", grant_conn=ro.conn, corpus_conn=None)
        result = svc.query_events(AccessRequest(operation="READ",
                                                requesting_profile_id="prof-B"))
        assert result.allowed
        assert {v.event_id for v in result.items} == {"mine-unscoped"}, (
            "owner implicit-local read of own unscoped row must be unaffected")
