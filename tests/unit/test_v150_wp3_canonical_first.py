"""V150-WP3 — canonical-first: drop resolution fallback (DEF-011 closed).

A row whose canonical envelope carries no ``knowledge_space_id`` is UNSCOPED
(D-2026-08-22-03). It must NEVER be authorized by a knowledge-space grant on
the event path — not even via the corpus projection resolver. Space
authorization on the event path reads exactly one source:
``zm_meta.knowledge_space_id`` (derived from canonical JSONL, rebuildable).
"""

from __future__ import annotations

import inspect

import pytest


class TestDef011CanonicalFirst:
    def test_scope_allows_has_no_resolution_fallback(self):
        """``_scope_allows`` must not consult space_members for event rows."""
        from src.access import authorized_read as mod

        src_text = inspect.getsource(mod._scope_allows)
        assert "space_members" not in src_text.replace(
            "space_members: Optional[set] = None", ""
        ).replace("def _scope_allows(scope", ""), (
            "_scope_allows must be per-row only: the space_members fallback "
            "(derived corpus state) must no longer participate in event "
            "authorization")

    def test_null_ks_row_denied_even_with_resolver_data(self, tmp_path):
        """Direct contract: a NULL-ks row stays DENIED; space_members is no
        longer even an accepted parameter (canonical-first, per-row only)."""
        from src.access.authorized_read import _scope_allows
        from src.access.contracts import AllowedScope

        scope = AllowedScope(
            operation="read", allowed_profile_ids=[],
            allowed_project_ids=[],
            allowed_knowledge_space_ids=["quant-theory"],
            global_read_allowed=False, resource_types=["memory_event"],
            isolated=False, is_grant=True)  # DEF-028: grant-scope semantics
        # The resolver argument is GONE from the signature entirely.
        with pytest.raises(TypeError):
            _scope_allows(scope, "prof-owner", "prof-x", "proj-a",
                          space_members={("prof-x", "proj-a")},
                          row_knowledge_space_id=None)
        assert _scope_allows(scope, "prof-owner", "prof-x", "proj-a",
                             row_knowledge_space_id=None) is False, (
            "unscoped (NULL ks) row must never match a space grant")
        assert _scope_allows(scope, "prof-owner", "prof-x", "proj-a",
                             row_knowledge_space_id="other-ks") is False
        assert _scope_allows(scope, "prof-owner", "prof-x", "proj-a",
                             row_knowledge_space_id="quant-theory") is True

    def test_query_events_ignores_resolver_for_null_ks_rows(self, tmp_path):
        """End-to-end through query_events: with an armed digest gate AND a
        matching corpus projection attesting the member pair, a NULL-ks row
        still does not appear under a space grant."""
        import hashlib
        import sqlite3

        from src.access.authorized_read import AuthorizedReadService
        from src.access.contracts import AccessRequest
        from src.retrieval.db import ReadonlyStore
        from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig

        cfg = SQLiteStoreConfig(path=tmp_path / "derived.sqlite")
        store = SQLiteStore(cfg)
        store.ensure_schema()
        conn = store._conn
        conn.row_factory = sqlite3.Row
        conn.execute(
            "INSERT INTO zm_meta (event_id, trace_id, event_type, source,"
            " schema_version, created_at, observed_at, sequence, session_id,"
            " profile_id, project_id, task_id, turn_id, parent_trace_id,"
            " lifecycle_status, verification_status, confidence, sensitivity,"
            " retention, content_hash, redaction_applied, ingested_at,"
            " origin_jsonl, knowledge_space_id)"
            " VALUES ('ev-legacy-null', 't1', 'session_lifecycle', 'test', 11,"
            " '2026-08-25T00:00:00Z', '2026-08-25T00:00:00Z', 1, NULL,"
            " 'prof-x', 'proj-a', NULL, NULL, NULL,"
            " 'active', 'none', 'medium', 'internal', 'persistent', ?, 0,"
            " '2026-08-25T00:00:00Z', 'x', NULL)",
            (hashlib.sha256(b"ev-legacy-null").hexdigest(),))
        conn.commit()
        ro = ReadonlyStore(conn, tmp_path / "derived.sqlite")

        # Corpus conn that WOULD attest (prof-x, proj-a) as a space member.
        corpus = sqlite3.connect(":memory:")
        corpus.execute(
            "CREATE TABLE zm_corpus_sources (source_id TEXT PRIMARY KEY,"
            " external_ref TEXT, kind TEXT, profile_id TEXT, project_id TEXT,"
            " knowledge_space_id TEXT)")
        corpus.execute(
            "CREATE TABLE zm_corpus_units (unit_id TEXT PRIMARY KEY,"
            " source_ref TEXT, content_hash TEXT, profile_id TEXT,"
            " project_id TEXT, knowledge_space_id TEXT)")
        corpus.execute(
            "INSERT INTO zm_corpus_sources VALUES"
            " ('s1', 'r1', 'txt', 'prof-x', 'proj-a', 'quant-theory')")

        svc = AuthorizedReadService(ro, "prof-owner", grant_conn=ro.conn,
                                    corpus_conn=corpus)
        req = AccessRequest(operation="READ",
                            requesting_profile_id="prof-owner",
                            knowledge_space_ids=["quant-theory"])
        grant = __import__("tests.unit.test_v150_wp2_per_row_ks",
                           fromlist=["_grant"])._grant("quant-theory")
        result = svc.query_events(req, grants=[grant])
        ids = {v.event_id for v in result.items}
        assert "ev-legacy-null" not in ids, (
            "NULL-ks row must not surface via the resolver path even when the "
            "corpus projection attests membership")
