"""V140-02 Option B — RED-first tests for knowledge-space resolution layer (DEF-004).

These tests encode the APPROVED behavior (GATE-2: Option B, no zm_meta schema
change). They must FAIL before the resolver + ``_scope_allows`` fix land, and
PASS after.

Coverage:
1. Resolver maps space -> (profile, project) members from derived corpus state.
2. Space-grant authorizes an event whose (profile, project) is in that set.
3. Fail-closed: space-grant DENIES an event whose (profile, project) is NOT in
   the resolved set, and DENIES when the space has no corpus members (no
   resolver data => no authorization).
4. ``_scope_allows`` honors resolved space members instead of returning False.
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
# _scope_allows honors resolved space members (Option B)
# ---------------------------------------------------------------------------

def test_scope_allows_space_member_event():
    """A space grant must authorize an event whose (profile, project) is a
    resolved member of the granted space."""
    members = {("prof-X", "proj-Y")}
    scope = AllowedScope(
        operation=READ,
        allowed_knowledge_space_ids=["quant-theory"],
    )
    # Event owned by the corpus member of quant-theory => authorized.
    assert authorized_read._scope_allows(
        scope, "requester", "prof-X", "proj-Y",
        space_members=members,
    ) is True


def test_scope_allows_denies_non_member_event():
    """Space grant must NOT authorize an event outside the resolved member set."""
    members = {("prof-X", "proj-Y")}
    scope = AllowedScope(
        operation=READ,
        allowed_knowledge_space_ids=["quant-theory"],
    )
    # Event owned by a different profile/project => denied (fail-closed).
    assert authorized_read._scope_allows(
        scope, "requester", "prof-Z", "proj-W",
        space_members=members,
    ) is False


def test_scope_allows_space_grant_without_members_is_fail_closed():
    """No resolver data (empty members) => space grant cannot authorize anything."""
    scope = AllowedScope(
        operation=READ,
        allowed_knowledge_space_ids=["quant-theory"],
    )
    # Without members, even a plausible row is denied (no silent authorization).
    assert authorized_read._scope_allows(
        scope, "requester", "prof-X", "proj-Y",
        space_members=set(),
    ) is False


def test_scope_allows_space_grant_legacy_no_param_still_fail_closed():
    """Backward-compatible call without space_members keeps fail-closed behavior
    for space grants (no regressions / no silent authorization)."""
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
    """DEF-004 Option B: facade expands a space grant scope into the concrete
    (profile, project) members resolved from corpus state, so the existing
    profile/project predicates authorize space-owned rows without a zm_meta
    schema change."""
    from src.access import AccessRequest, AuthorizedReadService, READ
    from src.access.contracts import AllowedScope

    svc = AuthorizedReadService.__new__(AuthorizedReadService)
    svc._corpus_conn = corpus_conn
    space_scope = AllowedScope(
        operation=READ,
        allowed_knowledge_space_ids=["quant-theory"],
    )
    expanded = svc._expand_scope_with_spaces(space_scope)
    assert "prof-X" in expanded.allowed_profile_ids
    assert "proj-Y" in expanded.allowed_project_ids
    # The expanded scope now authorizes a row owned by the corpus member.
    assert authorized_read._scope_allows(
        expanded, "requester", "prof-X", "proj-Y",
        space_members=svc._space_members_for(expanded),
    ) is True
    # And denies a row outside the resolved set.
    assert authorized_read._scope_allows(
        expanded, "requester", "prof-Z", "proj-W",
        space_members=svc._space_members_for(expanded),
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

