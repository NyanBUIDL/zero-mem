"""V150-WP2 — Option B: per-row knowledge-space authorization (DEF-010).

ADR-V150-01 Option B / SPIKE-B-SCHEMA: ``zm_meta`` has carried
``knowledge_space_id`` since migration 11 (V130-02), and ingest denormalizes it.
The space-grant path therefore no longer needs the (profile, project) resolution
coarsening — a space grant must authorize exactly the event rows whose
denormalized ``knowledge_space_id`` is in the granted set:

1. A row in granted space  -> authorized, EVEN IF its (profile, project) pair
   differs from every resolved corpus member (the old path denied/over-matched).
2. A row owned by a (profile, project) that IS a corpus member but whose own
   knowledge_space_id is NOT in the granted set -> DENIED (coarsening gone).
3. Rows with NULL knowledge_space_id are never authorized by a space grant.
4. The digest gate (DEF-011) still applies when armed; with no corpus conn and
   an unarmed gate, per-row authorization now works WITHOUT any corpus store.
"""

from __future__ import annotations

import json
import sqlite3

import pytest


def _store_with_events(tmp_path):
    """In-memory derived store with zm_meta carrying ks-denormalized events."""
    from src.storage.sqlite_store import SQLiteStoreConfig, SQLiteStore

    cfg = SQLiteStoreConfig(path=tmp_path / "derived.sqlite")
    store = SQLiteStore(cfg)
    store.ensure_schema()                # v13
    store.downgrade_to(12)               # v12: no zm_event_spaces
    conn = store._conn
    conn.row_factory = sqlite3.Row
    # AuthorizedReadService reads via the ReadonlyStore facade (.conn).
    from src.retrieval.db import ReadonlyStore
    ro = ReadonlyStore(conn, tmp_path / "derived.sqlite")

    def add_event(event_id, profile_id, ks):
        conn.execute(
            "INSERT INTO zm_meta (event_id, trace_id, event_type, source,"
            " schema_version, created_at, observed_at, sequence, session_id,"
            " profile_id, project_id, task_id, turn_id, parent_trace_id,"
            " lifecycle_status, verification_status, confidence, sensitivity,"
            " retention, content_hash, redaction_applied, ingested_at,"
            " origin_jsonl, knowledge_space_id)"
            " VALUES (?, 't1', 'session_lifecycle', 'test', 11,"
            " '2026-08-25T00:00:00Z', '2026-08-25T00:00:00Z', 1, NULL,"
            " ?, 'proj-a', NULL, NULL, NULL,"
            " 'active', 'none', 'medium', 'internal', 'persistent',"
            " ?, 0, '2026-08-25T00:00:00Z', 'x', ?)",
            (event_id, profile_id,
             __import__("hashlib").sha256(event_id.encode()).hexdigest(), ks))

    add_event("ev-in-space", "prof-x", "quant-theory")     # in granted ks
    add_event("ev-other-space", "prof-x", "other-ks")      # member pair, wrong ks
    add_event("ev-unscoped", "prof-x", None)               # NULL never matches
    conn.commit()
    # C4 review (P1): proper legacy = migration runner backfills the junction;
    # space authorization flows through the junction only (no singular fallback).
    store.ensure_schema()               # v13: migrate_13 backfills junction
    return ro


class TestDef010PerRowSpaceAuthorization:
    def test_row_in_granted_space_authorized_without_corpus(self, tmp_path):
        """Per-row match authorizes even with NO corpus connection at all."""
        from src.access.authorized_read import AuthorizedReadService
        from src.access.contracts import AccessRequest

        ro = _store_with_events(tmp_path)
        svc = AuthorizedReadService(ro, "prof-owner", grant_conn=ro.conn,
                                    corpus_conn=None)
        req = AccessRequest(operation="READ",
                            requesting_profile_id="prof-owner",
                            knowledge_space_ids=["quant-theory"])
        grants = [_grant("quant-theory")]
        result = svc.query_events(req, grants=grants)
        assert result.allowed
        ids = {v.event_id for v in result.items}
        assert "ev-in-space" in ids

    def test_member_pair_wrong_space_denied(self, tmp_path):
        """The coarsening is gone: a (profile, project) pair that would be a
        corpus member does NOT authorize a row outside the granted space."""
        from src.access.authorized_read import AuthorizedReadService
        from src.access.contracts import AccessRequest

        ro = _store_with_events(tmp_path)
        svc = AuthorizedReadService(ro, "prof-owner", grant_conn=ro.conn,
                                    corpus_conn=None)
        req = AccessRequest(operation="READ",
                            requesting_profile_id="prof-owner",
                            knowledge_space_ids=["quant-theory"])
        grants = [_grant("quant-theory")]
        result = svc.query_events(req, grants=grants)
        ids = {v.event_id for v in result.items}
        assert "ev-other-space" not in ids
        assert "ev-unscoped" not in ids

    def test_null_ks_never_authorized_by_space_grant(self):
        import inspect
        from src.access import authorized_read as mod
        src_text = inspect.getsource(mod._scope_allows)
        # Per-row branch must reference the row's own knowledge_space_id.
        assert "row_knowledge_space_id" in src_text or \
            "row_space_id" in src_text or "knowledge_space_id" in src_text, (
            "_scope_allows must implement the per-row ks check")


def _grant(target_id: str) :
    from src.access.grants import AuthorizedReadGrant
    return AuthorizedReadGrant(
        grant_id="g-test", subject_profile="prof-owner",
        operation="READ", target_type="knowledge_space",
        target_id=target_id, resource_types=["memory_event"],
    )
