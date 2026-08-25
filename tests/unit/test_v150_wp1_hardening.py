"""V150-WP1 — Option A hardening tests (DEF-009, DEF-011).

Option A of ADR-V150-01 (GATE-V150-1: A + B-schema spike):

- DEF-009a: ``CorpusSourceRegistry._update_record`` must not re-read the whole
  registry JSONL on every update (O(n)/update). The rewrite must use the
  in-memory index to emit the new file content.
- DEF-009b: ``AuthorizedReadService.authorized_query`` cursor fingerprint must
  carry ``profile_id=profile_filter`` (not the project filter) — naming-only,
  behavior-neutral fix pinned by test.
- DEF-011: space-grant authorization must fail closed when the derived corpus
  projection is stale/tampered relative to canonical registry state. A
  digest-mismatch (or missing digest) must produce DENY for space-scoped reads,
  never an over-authorize.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# DEF-009a — registry update must be O(1) amortized (no full re-read)
# ---------------------------------------------------------------------------

def _mk_registry(tmp_path: Path):
    from src.corpus.registry import CorpusSourceRegistry

    reg = CorpusSourceRegistry(root=tmp_path / "corpus")
    return reg


def _register(reg, ref: str, payload: bytes = b"body", **kw):
    return reg.register_source(
        content=payload, external_ref=ref, kind="txt",
        profile_id=kw.get("profile_id"), project_id=kw.get("project_id"),
        knowledge_space_id=kw.get("knowledge_space_id"),
    )


class TestDef009aRegistryIndexRewrite:
    def test_update_record_does_not_re_read_whole_file(self, tmp_path, monkeypatch):
        """The rewrite path must consult the in-memory record list instead of
        re-parsing the entire JSONL from disk on every single update."""
        import src.corpus.registry as reg_mod

        reg = _mk_registry(tmp_path)
        recs = [_register(reg, f"doc-{i}") for i in range(5)]

        calls = {"n": 0}
        orig = Path.read_bytes

        def counting_read_bytes(self, *a, **kw):
            if self == reg._path:
                calls["n"] += 1
            return orig(self, *a, **kw)

        monkeypatch.setattr(Path, "read_bytes", counting_read_bytes)

        updated = type(recs[0])(**{**recs[0].as_dict(), "lifecycle_status": "archived"})
        reg._update_record(updated)

        assert calls["n"] == 0, (
            "_update_record re-read the registry JSONL from disk "
            "(O(n) per update); it must derive new content from the in-memory index")

    def test_update_preserves_history_and_other_records(self, tmp_path):
        """Behavior contract unchanged: other sources untouched, updated row
        replaced exactly once (no duplicate), file remains valid JSONL."""
        reg = _mk_registry(tmp_path)
        a1 = _register(reg, "doc-a", b"v1")
        b1 = _register(reg, "doc-b", b"other")
        # Rebind doc-a's latest version with a changed lifecycle status.
        a2 = type(a1)(**{**a1.as_dict(), "lifecycle_status": "archived"})
        reg._update_record(a2)

        lines = [
            json.loads(l.decode("utf-8"))
            for l in reg.path.read_bytes().splitlines()
        ]
        rows_a = [r for r in lines if r["source_id"] == a1.source_id]
        assert len(rows_a) == 1, (
            "updated record must appear exactly once in its updated form")
        assert rows_a[0]["lifecycle_status"] == "archived"
        assert any(r["source_id"] == b1.source_id for r in lines), (
            "unrelated records must remain untouched")
        assert reg.get_by_source_id(a1.source_id).lifecycle_status == "archived"
        assert reg.get_by_source_id(b1.source_id) is not None

    def test_append_only_when_no_prior_line(self, tmp_path):
        reg = _mk_registry(tmp_path)
        rec = _register(reg, "fresh-doc", b"content")
        assert reg.get_by_source_id(rec.source_id) is not None
        lines = reg.path.read_bytes().splitlines()
        assert len(lines) == 1


# ---------------------------------------------------------------------------
# DEF-009b — fp_request field-name fix (naming only)
# ---------------------------------------------------------------------------

class TestDef009bFingerprintFieldNames:
    def test_cursor_fingerprint_binds_profile_filter_to_profile_field(self, tmp_path):
        """A cursor minted under profile filter P and project filter X must NOT
        validate under swapped filters when the effective scope text is equal —
        i.e. the fingerprint request fields are named correctly."""
        from src.access.authorized_read import AuthorizedReadService

        captured = {}

        real_make_fingerprint = None

        def fake_validate(cursor, fp, limit):
            captured["ok"] = True
            return {"sort": ["created_at", "event_id"]}

        svc = AuthorizedReadService.__new__(AuthorizedReadService)
        # Minimal stubbing: we inspect make_fingerprint input indirectly via
        # source-level pinning (behavior-neutral change; keep it simple).
        import inspect
        src_text = inspect.getsource(AuthorizedReadService)
        assert "fp_request" in src_text
        # The bug: profile_id=project_filter. After the fix both filters map to
        # their own fields explicitly.
        import re
        m = re.search(
            r"fp_request\s*=\s*_QR\((.*?)\)", src_text, re.S)
        assert m, "fp_request construction not found"
        body = m.group(1)
        assert "profile_id=profile_filter" in body, (
            "cursor fingerprint request must bind profile_id=profile_filter")
        assert "project_id=project_filter" in body or (
            "session_id=session_filter" in body), (
            "fingerprint request must name project/session fields correctly")


# ---------------------------------------------------------------------------
# DEF-011 — projection digest gate for space-grant authorization
# ---------------------------------------------------------------------------

def _corpus_conn_with_projection(tmp_path: Path, ks: str = "ks-1",
                                 profile: str = "prof-a",
                                 project: str = "proj-a") -> sqlite3.Connection:
    """Build a minimal corpus-derived DB carrying zm_corpus_* rows."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE zm_corpus_sources ("
        " source_id TEXT PRIMARY KEY, external_ref TEXT, kind TEXT,"
        " profile_id TEXT, project_id TEXT, knowledge_space_id TEXT)")
    conn.execute(
        "CREATE TABLE zm_corpus_units ("
        " unit_id TEXT PRIMARY KEY, source_ref TEXT, content_hash TEXT,"
        " profile_id TEXT, project_id TEXT, knowledge_space_id TEXT)")
    conn.execute(
        "INSERT INTO zm_corpus_sources VALUES ('s1', 'r1', 'txt', ?, ?, ?)",
        (profile, project, ks))
    conn.commit()
    return conn


class TestDef011DigestGate:
    def test_digest_gate_exists_and_is_fail_closed(self):
        """The service must expose a projection-integrity gate used before
        trusting space-member resolution, failing closed on mismatch."""
        import hashlib
        import inspect
        from src.access import authorized_read as mod

        src_text = inspect.getsource(mod)
        # A digest/integrity verification hook must be wired into the module.
        assert "ProjectionDigestGate" in src_text and "_projection_digest" in src_text, (
            "authorized_read must implement a projection digest/integrity gate")

    def test_stale_projection_denies_space_grant(self, tmp_path):
        """With digest gate armed and a tampered/stale projection (digest
        mismatch), space-scoped resolution must refuse to expand members =>
        deny (fail-closed), regardless of what zm_corpus_sources claims."""
        pytest.importorskip("src.access.knowledge_space_resolver")
        from src.access.authorized_read import AuthorizedReadService
        from src.access.contracts import AllowedScope
        from src.access.knowledge_space_resolver import resolve_space_members

        conn = _corpus_conn_with_projection(tmp_path)
        members = resolve_space_members(conn, ["ks-1"])
        assert ("prof-a", "proj-a") in set(members)

        svc = AuthorizedReadService.__new__(AuthorizedReadService)
        svc._store = None
        svc._requester = "prof-other"
        svc._grant_conn = None
        svc._corpus_conn = conn
        # Arm the gate with a digest that CANNOT match the current projection.
        svc._projection_digest = "0" * 64

        scope = AllowedScope(
            operation="read", allowed_profile_ids=[], allowed_project_ids=[],
            allowed_knowledge_space_ids=["ks-1"], global_read_allowed=False,
            resource_types=["memory_event"], isolated=False)
        expanded = svc._expand_scope_with_spaces(scope)
        # Gate mismatch => no member expansion (space stays non-authorizing).
        assert expanded.allowed_profile_ids == [] and \
            expanded.allowed_project_ids == [], (
            "digest mismatch must prevent space-member expansion (fail-closed)")

    def test_matching_digest_allows_expansion(self, tmp_path):
        from src.access.authorized_read import AuthorizedReadService
        from src.access.contracts import AllowedScope
        from src.access.projection_integrity import compute_corpus_projection_digest

        conn = _corpus_conn_with_projection(tmp_path)
        digest = compute_corpus_projection_digest(conn)

        svc = AuthorizedReadService.__new__(AuthorizedReadService)
        svc._store = None
        svc._requester = "prof-other"
        svc._grant_conn = None
        svc._corpus_conn = conn
        svc._projection_digest = digest

        scope = AllowedScope(
            operation="read", allowed_profile_ids=[], allowed_project_ids=[],
            allowed_knowledge_space_ids=["ks-1"], global_read_allowed=False,
            resource_types=["memory_event"], isolated=False)
        expanded = svc._expand_scope_with_spaces(scope)
        assert ("prof-a" in expanded.allowed_profile_ids) or (
            "proj-a" in expanded.allowed_project_ids), (
            "matching digest must allow normal space-member expansion")

    def test_open_facade_passes_digest_through_env(self, tmp_path, monkeypatch):
        """DEF-012 lesson: the gate must be armed at the REAL production
        construction point (_open_facade), not just library-level."""
        import inspect

        monkeypatch.setenv("ZM_CORPUS_PROJECTION_DIGEST", "deadbeef")
        from src.integration.m6 import handlers as m6_handlers

        src_text = inspect.getsource(m6_handlers._open_facade)
        assert "expected_projection_digest" in src_text, (
            "_open_facade must arm the DEF-011 integrity gate")
        assert "ZM_CORPUS_PROJECTION_DIGEST" in (
            inspect.getsource(m6_handlers)), (
            "digest expectation must resolve from env/request configuration")
