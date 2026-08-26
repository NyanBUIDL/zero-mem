"""DEF-034 lifecycle probes — knowledge_space_id capture → canonical → ingest → auth.

Executable evidence for the review-corrected verdict:
  CONFIRMED — standard capture adapters do not pass KS into the top-level
  canonical envelope. The capture STORE/boundary preserves a manually-injected
  top-level knowledge_space_id (probe I); the loss is in envelope construction.

Also covers the security nuance (probe J): global read on NULL-profile rows
ignores ks by design (D-2026-08-22-03), so a dropped KS does not widen global
read exposure in the tested paths — it only removes the space-grant channel.

NOTE: these are EVIDENCE tests, not fixes. They assert the CURRENT behavior.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from src.capture.adapter import normalize_event
from src.storage.jsonl_capture import CaptureStoreConfig, JsonlCaptureStore
from src.storage.ingest import ingest_file
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.retrieval.db import open_readonly
from tests.unit.test_m3_query import (
    _checkpoint_and_close,
    _make_env,
    _open_store,
    _write_jsonl,
)


_AUDIT = [{"rule": "probe", "fields": []}]


def _envelope(**over):
    return normalize_event(
        {"text": "probe", "redaction_audit": _AUDIT, **over},
        profile_id="p1", project_id="P", sequence=0,
        event_type="user_statement", source="hermes_chat",
    )


class TestDef034CaptureEnvelope:
    def test_adapter_envelope_has_no_knowledge_space_id(self):
        env = _envelope()
        assert "knowledge_space_id" not in env, (
            "capture adapter must not synthesize a top-level ks")

    def test_ks_via_payload_goes_to_sanitized_content_extra(self):
        env = _envelope(knowledge_space_id="quant-theory")
        assert "knowledge_space_id" not in env, "must not surface top-level"
        sc = env.get("sanitized_content")
        if isinstance(sc, dict) and "extra" in sc:
            assert "knowledge_space_id" in sc["extra"], (
                "KS in payload is parked in sanitized_content.extra")
        else:
            pytest.skip("payload had no leftover keys -> no extra block")

    def test_manual_top_level_ks_preserved_through_append_and_ingest(self, tmp_path):
        """The store/boundary does NOT drop a manually-injected top-level ks."""
        env = _envelope()
        env["knowledge_space_id"] = "ks-manual"
        root = tmp_path / "canon"
        store = JsonlCaptureStore(CaptureStoreConfig(root))
        store.append(env)
        line = json.loads((root / "events-v1.jsonl").read_text().splitlines()[0])
        assert line.get("knowledge_space_id") == "ks-manual"
        db = SQLiteStore(SQLiteStoreConfig(path=tmp_path / "m.sqlite"))
        db.ensure_schema()
        ingest_file(db, root / "events-v1.jsonl")
        _checkpoint_and_close(db)
        conn = sqlite3.connect(str(tmp_path / "m.sqlite"))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT knowledge_space_id FROM zm_meta").fetchone()
        conn.close()
        assert row["knowledge_space_id"] == "ks-manual", (
            "ingest denormalizes a top-level ks present in canonical")

    def test_captured_canonical_ingest_yields_null_ks(self, tmp_path):
        env = _envelope()
        root = tmp_path / "canon2"
        store = JsonlCaptureStore(CaptureStoreConfig(root))
        store.append(env)
        db = SQLiteStore(SQLiteStoreConfig(path=tmp_path / "m2.sqlite"))
        db.ensure_schema()
        ingest_file(db, root / "events-v1.jsonl")
        _checkpoint_and_close(db)
        conn = sqlite3.connect(str(tmp_path / "m2.sqlite"))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT knowledge_space_id FROM zm_meta").fetchone()
        conn.close()
        assert row["knowledge_space_id"] is None, (
            "standard-capture canonical carries no ks -> zm_meta NULL")

    def test_hand_crafted_ks_denormalizes(self, tmp_path):
        jl = tmp_path / "ks.jsonl"
        _write_jsonl(jl, [
            _make_env("ev-ks", profile_id="p1", project_id="P",
                      knowledge_space_id="quant-theory"),
        ])
        store = _open_store(tmp_path, "m3.sqlite")
        ingest_file(store, jl)
        _checkpoint_and_close(store)
        conn = sqlite3.connect(str(tmp_path / "m3.sqlite"))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT knowledge_space_id FROM zm_meta").fetchone()
        conn.close()
        assert row["knowledge_space_id"] == "quant-theory"


class TestDef034GlobalReadSecurityNuance:
    def test_global_read_null_profile_rows_visible_with_or_without_ks(self, tmp_path):
        """Probe J: global read on NULL-profile rows ignores ks by design;
        a dropped KS does NOT widen global-read exposure in tested paths."""
        from src.access.authorized_read import AuthorizedReadService
        from src.access.contracts import AccessRequest
        jl = tmp_path / "sec.jsonl"
        _write_jsonl(jl, [
            _make_env("ev-lost-ks", profile_id=None, project_id=None,
                      knowledge_space_id=None),
            _make_env("ev-kept-ks", profile_id=None, project_id=None,
                      knowledge_space_id="secret-ks"),
        ])
        store = _open_store(tmp_path, "sec.sqlite")
        ingest_file(store, jl)
        _checkpoint_and_close(store)
        ro = open_readonly(tmp_path / "sec.sqlite")
        svc = AuthorizedReadService(ro, "stranger", grant_conn=ro.conn)
        try:
            res = svc.query_events(
                AccessRequest(operation="READ",
                              requesting_profile_id="stranger",
                              include_global=True))
            ids = {v.event_id for v in res.items}
            # Both visible under global read: ks does not restrict NULL-profile
            # rows (D-2026-08-22-03). KS loss therefore does not add exposure.
            assert "ev-lost-ks" in ids
            assert "ev-kept-ks" in ids
            # Local-only (no global): no NULL-profile rows.
            res2 = svc.query_events(
                AccessRequest(operation="READ",
                              requesting_profile_id="stranger",
                              include_global=False))
            assert {v.event_id for v in res2.items} == set()
        finally:
            svc.close()
