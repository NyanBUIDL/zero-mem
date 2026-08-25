"""V140-02 Option B — RED-first tests for knowledge-space resolution layer (DEF-004).

These tests encode the APPROVED behavior (GATE-2: Option B, no zm_meta schema
change). They must FAIL before the resolver + ``_scope_allows`` fix land, and
PASS after.

V150-WP3 SUPERSESSION (2026-08-25, ADR-V150-01 appendix): the event path moved
to canonical-first per-row authorization (zm_meta.knowledge_space_id). The
space_members fallback is REMOVED from _scope_allows — resolver-derived
membership no longer authorizes event rows. The 4 _scope_allows tests below
are formally SUPERSEDED and now PIN THE ABSENCE of the old behavior
(resolver layer itself remains tested for the corpus path).

Coverage:
1. Resolver maps space -> (profile, project) members from derived corpus state.
   [STILL VALID — corpus-path resolution]
2-4. [SUPERSEDED by V150-WP3] replaced by absence-pins.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.access.knowledge_space_resolver import resolve_space_members
from src.access.contracts import AllowedScope, READ
from src.access import authorized_read


# ---------------------------------------------------------------------------
# Synthetic corpus DB with knowledge_space_id on sources/units (derived state)
# ---------------------------------------------------------------------------

@pytest.fixture
def corpus_conn(tmp_path: Path):
    db = tmp_path / "corpus.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE zm_corpus_sources ("
        "source_id TEXT PRIMARY KEY, profile_id TEXT, project_id TEXT, "
        "knowledge_space_id TEXT)"
    )
    conn.execute(
        "CREATE TABLE zm_corpus_units ("
        "unit_id TEXT PRIMARY KEY, profile_id TEXT, project_id TEXT, "
        "knowledge_space_id TEXT)"
    )
    # Space "quant-theory" owned by (prof-X, proj-Y) and an unowned row (None,None)
    conn.execute(
        "INSERT INTO zm_corpus_sources VALUES (?,?,?,?)",
        ("s1", "prof-X", "proj-Y", "quant-theory"),
    )
    conn.execute(
        "INSERT INTO zm_corpus_units VALUES (?,?,?,?)",
        ("u1", "prof-X", "proj-Y", "quant-theory"),
    )
    # unowned corpus resource still maps to (None, None) sentinel
    conn.execute(
        "INSERT INTO zm_corpus_sources VALUES (?,?,?,?)",
        ("s2", None, None, "quant-theory"),
    )
    # A different space owned by someone else
    conn.execute(
        "INSERT INTO zm_corpus_sources VALUES (?,?,?,?)",
        ("s3", "prof-Z", "proj-W", "other-space"),
    )
    conn.commit()
    yield conn
    conn.close()


def test_resolver_maps_space_to_members(corpus_conn):
    members = resolve_space_members(corpus_conn, ["quant-theory"])
    assert (("prof-X", "proj-Y") in members) or (  # sqlite may yield None as None
        ("prof-X", "proj-Y") in [(str(a), str(b)) for a, b in members]
    )
    # distinct members set
    assert len(members) >= 1
    ids = {a for a, _ in members}
    assert "prof-X" in ids


def test_resolver_empty_for_unknown_space(corpus_conn):
    assert resolve_space_members(corpus_conn, ["does-not-exist"]) == []


def test_resolver_empty_for_no_input(corpus_conn):
    assert resolve_space_members(corpus_conn, []) == []


# ---------------------------------------------------------------------------
# _scope_allows: V150-WP3 — resolution fallback REMOVED (canonical-first)
# The 4 original Option B tests are superseded; these pin the absence.
# ---------------------------------------------------------------------------

def test_scope_allows_space_member_event():
    """SUPERSEDED (V150-WP3): space_members no longer authorizes event rows.
    Pin: passing row ks in the granted set is the ONLY authorizing form."""
    scope = AllowedScope(
        operation=READ,
        allowed_knowledge_space_ids=["quant-theory"],
    )
    assert authorized_read._scope_allows(
        scope, "requester", "prof-X", "proj-Y",
        row_knowledge_space_id="quant-theory",
    ) is True


def test_scope_allows_denies_non_member_event():
    """SUPERSEDED (V150-WP3): a row outside the granted ks is denied."""
    scope = AllowedScope(
        operation=READ,
        allowed_knowledge_space_ids=["quant-theory"],
    )
    assert authorized_read._scope_allows(
        scope, "requester", "prof-Z", "proj-W",
        row_knowledge_space_id="other-ks",
    ) is False


def test_scope_allows_space_grant_without_members_is_fail_closed():
    """SUPERSEDED (V150-WP3): NULL row ks => denied, no resolver involvement."""
    scope = AllowedScope(
        operation=READ,
        allowed_knowledge_space_ids=["quant-theory"],
    )
    assert authorized_read._scope_allows(
        scope, "requester", "prof-X", "proj-Y",
        row_knowledge_space_id=None,
    ) is False


def test_scope_allows_space_grant_legacy_no_param_still_fail_closed():
    """Pin unchanged: no row ks argument => fail-closed for space grants."""
    scope = AllowedScope(
        operation=READ,
        allowed_knowledge_space_ids=["quant-theory"],
    )
    assert authorized_read._scope_allows(
        scope, "requester", "prof-X", "proj-Y",
    ) is False


# ---------------------------------------------------------------------------
# Facade expansion: AuthorizedReadService._expand_scope_with_spaces (B)
# ---------------------------------------------------------------------------

def test_expand_scope_with_spaces_merges_members(corpus_conn):
    """SUPERSEDED (V150-WP3): expansion is now a NO-OP on the event path —
    member merging was the coarsening channel and is removed. The scope is
    returned unchanged; event authorization stays per-row."""
    from src.access import AuthorizedReadService
    from src.access.contracts import AllowedScope

    svc = AuthorizedReadService.__new__(AuthorizedReadService)
    svc._corpus_conn = corpus_conn
    space_scope = AllowedScope(
        operation=READ,
        allowed_knowledge_space_ids=["quant-theory"],
    )
    expanded = svc._expand_scope_with_spaces(space_scope)
    # No-op: dimensions unchanged, nothing merged from corpus members.
    assert expanded.allowed_profile_ids == []
    assert expanded.allowed_project_ids == []
    assert expanded.allowed_knowledge_space_ids == ["quant-theory"]
    # Per-row only: a row with matching ks authorizes, others do not.
    assert authorized_read._scope_allows(
        expanded, "requester", "prof-X", "proj-Y",
        row_knowledge_space_id="quant-theory",
    ) is True
    assert authorized_read._scope_allows(
        expanded, "requester", "prof-Z", "proj-W",
        row_knowledge_space_id="other-ks",
    ) is False


def test_expand_scope_without_corpus_conn_keeps_fail_closed(corpus_conn):
    """No corpus connection => space grant cannot be resolved => stays non-
    authorizing (fail-closed), no silent authorization."""
    from src.access import AuthorizedReadService
    from src.access.contracts import AllowedScope

    svc = AuthorizedReadService.__new__(AuthorizedReadService)
    svc._corpus_conn = None  # no resolver data
    space_scope = AllowedScope(
        operation=READ,
        allowed_knowledge_space_ids=["quant-theory"],
    )
    expanded = svc._expand_scope_with_spaces(space_scope)
    # Unchanged (no expansion); scope still non-authorizing for any row.
    assert expanded.allowed_profile_ids == []
    assert authorized_read._scope_allows(
        expanded, "requester", "prof-X", "proj-Y",
    ) is False

