"""M3.4 focused tests — relation / scope / artifact read-only queries.

Reuses the verified M2.4 projection (zm_relations / zm_scopes / zm_artifacts) exactly as
ingested; M3.4 only READS it. Fixtures use the same _open_store + ingest_file pattern as the
verified M2 tests. The read-only proof is extended to cover zm_relations, zm_scopes and
zm_artifacts (in addition to the M3.1 derived-table set).

Scope semantics (schema-truthful, no inference):
- project/profile/session scope -> zm_meta columns (served by M3.1 helpers).
- knowledge_space scope -> only an observed zm_scopes row; NO event-level linkage exists in the
  verified M2 schema, so list_knowledge_space returns [] (no global fallback, no invented edges).
- artifact references -> metadata only; stored_path (internal filesystem pointer) is never exposed.
"""

from __future__ import annotations

import json
import sqlite3
import hashlib
import dataclasses
from pathlib import Path

import pytest

from src.retrieval import (
    open_readonly,
    get_related,
    get_parent,
    get_children,
    get_artifacts,
    list_project,
    list_profile,
    list_session,
    list_knowledge_space,
    RelatedView,
    ArtifactRefView,
    QueryError,
)
from src.retrieval.models import (
    INVALID_DIRECTION,
    INVALID_RELATION_TYPE,
    INVALID_LIMIT,
    CURSOR_QUERY_MISMATCH,
    CURSOR_LIMIT_MISMATCH,
)

# Reuse the M3.1 harness helpers.
from tests.unit.test_m3_query import (  # noqa: E402
    _make_env,
    _write_jsonl,
    _open_store,
    _checkpoint_and_close,
    Snapshot,
)

SECRET = "SK-M3R-DONTLEAK-9f3c2a1b"
SECRET_PAR = "p0 note with " + SECRET
SECRET_ART = "derived note with " + SECRET


def _ingest_relations_corpus(tmp_path: Path):
    """Build a corpus exercising parent/child, derived_from, scope, artifact, deletion.

    Targets are ingested BEFORE sources so the M2 relation projection can link edges.
    """
    items = [
        _make_env("p0", sanitized_content={"text": SECRET_PAR}, project_id="P", profile_id="U", knowledge_space_id="KS", session_id="sess-1"),
        _make_env("d2", sanitized_content={"text": "derived two content"}, project_id="P", session_id="sess-1",
                  lifecycle_status="deleted"),
        _make_env(
            "d1", sanitized_content={"text": SECRET_ART}, project_id="P", session_id="sess-1", relation_ids=["d2"],
            artifact_refs=[{
                "artifact_id": "a1", "content_hash": "h1", "kind": "note",
                "retention": "persistent", "stored_path": "/SECRET/FS/PATH/a1.bin",
            }],
        ),
        _make_env("c1", sanitized_content={"text": "child one content"}, parent_trace_id="tr-p0", project_id="P",
                  session_id="sess-1", relation_ids=["d1"]),
        _make_env("other", sanitized_content={"text": "unrelated content"}, project_id="Q", session_id="sess-1"),
        # Soft-deleted SOURCE: related to d1, but del itself is deleted; its live target may still appear
        # when querying the live target (deleted-source edges are not covered by the deleted-target rule).
        _make_env("del", sanitized_content={"text": "doomed content"}, project_id="P", session_id="sess-1", relation_ids=["d1"],
                  lifecycle_status="deleted"),
    ]
    jl = tmp_path / "c.jsonl"
    _write_jsonl(jl, items)
    store = _open_store(tmp_path, "m.sqlite")
    from src.storage.ingest import ingest_file
    ingest_file(store, jl)
    store._conn.commit()
    _checkpoint_and_close(store)
    return jl


# ---- relation lookup ----
def test_get_related_both_directions(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    res = get_related(rs, "p0")
    rels = {(v.direction, v.relation, v.target_event_id) for v in res.items}
    assert ("incoming", "child_of", "c1") in rels
    assert res.total == 1


def test_get_related_outgoing(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    # d1's only outgoing edge is d1->d2, but d2 is deleted -> excluded -> empty.
    res = get_related(rs, "d1", direction="outgoing")
    assert res.items == []


def test_get_related_incoming(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    # d1 has incoming derived_from from c1 (live) and del (deleted SOURCE, but del is the resolved
    # target here and is deleted -> excluded by the deleted-target rule). So only c1 remains.
    res = get_related(rs, "d1", direction="incoming")
    assert sorted(v.target_event_id for v in res.items) == ["c1"]


def test_get_related_relation_type_filter(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    # derived_from targets of d1: c1 (live) and d2 (deleted, excluded) -> only c1.
    res = get_related(rs, "d1", relation_type="derived_from")
    assert sorted(v.target_event_id for v in res.items) == ["c1"]


def test_get_parent_and_children(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    parent = get_parent(rs, "c1")
    assert isinstance(parent, RelatedView)
    assert parent.target_event_id == "p0"
    children = get_children(rs, "p0")
    assert [v.target_event_id for v in children.items] == ["c1"]


def test_no_explicit_relation_empty_success(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    res = get_related(rs, "other")
    assert res.items == []
    assert res.total == 0


def test_directionality_preserved(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    out = get_related(rs, "d1", direction="outgoing")  # -> d2 deleted, so empty
    inc = get_related(rs, "d1", direction="incoming")  # c1, del (both derived_from)
    assert out.items == []
    assert inc.items[0].direction == "incoming"
    assert all(v.target_event_id in ("c1", "del") for v in inc.items)
    # directed: outgoing must not contain the incoming edge target
    assert all(v.target_event_id != "c1" for v in out.items)


def test_no_inferred_relation(tmp_path):
    """Same-project events with no explicit edge must not appear as related."""
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    res = get_related(rs, "p0")
    # 'p0' shares project P with d1/d2/c1 but only has an explicit child_of edge to c1.
    assert sorted(v.target_event_id for v in res.items) == ["c1"]


def test_invalid_relation_direction(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    with pytest.raises(QueryError) as ei:
        get_related(rs, "p0", direction="sideways")
    assert ei.value.code == INVALID_DIRECTION


def test_invalid_relation_type(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    with pytest.raises(QueryError) as ei:
        get_related(rs, "p0", relation_type="")
    assert ei.value.code == INVALID_RELATION_TYPE


# ---- scope queries ----
def test_list_project(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    evs = list_project(rs, "P")
    assert sorted(e.event_id for e in evs) == ["c1", "d1", "p0"]


def test_list_profile(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    evs = list_profile(rs, "U")
    assert [e.event_id for e in evs] == ["p0"]


def test_list_session(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    evs = list_session(rs, "sess-1")
    assert sorted(e.event_id for e in evs) == ["c1", "d1", "other", "p0"]


def test_zero_result_scope_no_global_fallback(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    assert list_project(rs, "DOES-NOT-EXIST") == []


def test_explicit_combined_project_and_profile(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    p = {e.event_id for e in list_project(rs, "P")}
    u = {e.event_id for e in list_profile(rs, "U")}
    assert p & u == {"p0"}


def test_knowledge_space_returns_empty_no_inference(tmp_path):
    """No event-level knowledge_space linkage exists; must return [] (no inference/fallback)."""
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    res = list_knowledge_space(rs, "KS")
    assert res.items == []


# ---- artifact references ----
def test_get_artifacts_lookup(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    res = get_artifacts(rs, "d1")
    assert len(res.items) == 1
    a = res.items[0]
    assert isinstance(a, ArtifactRefView)
    assert a.artifact_id == "a1"
    assert a.reference == "artifact:a1"


def test_artifact_safe_reference_no_path_leak(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    a = get_artifacts(rs, "d1").items[0]
    assert not hasattr(a, "stored_path")
    assert "SECRET/FS/PATH" not in a.reference
    assert "/SECRET" not in json.dumps(a.__dict__)


def test_artifact_no_content_opened(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    res = get_artifacts(rs, "nonexistent")
    assert res.items == []


# ---- deleted-target exclusion ----
def test_deleted_related_target_excluded(tmp_path):
    """d2 is deleted; d1's derived_from edge to d2 must NOT surface d2 as a target."""
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    res = get_related(rs, "d1")
    assert all(v.target_event_id != "d2" for v in res.items)
    # del is a deleted SOURCE; querying del returns its live target d1 (deleted-source not excluded per plan).
    res2 = get_related(rs, "del")
    assert all(v.target_event_id != "del" for v in res2.items)
    assert "d1" in [v.target_event_id for v in res2.items]


def test_non_deleted_related_target_included(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    res = get_related(rs, "d1")
    # c1 (live) is an incoming derived_from target and must appear.
    assert "c1" in [v.target_event_id for v in res.items]


# ---- deterministic ordering ----
def test_deterministic_relation_ordering(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    r1 = [v.target_event_id for v in get_related(rs, "d1").items]
    r2 = [v.target_event_id for v in get_related(rs, "d1").items]
    assert r1 == r2


def test_deterministic_scope_ordering(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    a = [e.event_id for e in list_project(rs, "P")]
    b = [e.event_id for e in list_project(rs, "P")]
    assert a == b


# ---- pagination ----
def test_relation_pagination_no_duplicates(tmp_path):
    hub = "hub"
    items = [_make_env(hub, sanitized_content={"text": "hub content"}, project_id="P")]
    for i in range(3):
        items.append(_make_env(f"n{i}", sanitized_content={"text": f"node {i}"}, project_id="P", relation_ids=[hub]))
    jl = tmp_path / "c.jsonl"
    _write_jsonl(jl, items)
    store = _open_store(tmp_path, "m.sqlite")
    from src.storage.ingest import ingest_file
    ingest_file(store, jl)
    _checkpoint_and_close(store)
    rs = open_readonly(tmp_path / "m.sqlite")
    p1 = get_related(rs, hub, direction="incoming", limit=2)
    assert len(p1.items) == 2
    assert p1.next_cursor is not None
    p2 = get_related(rs, hub, direction="incoming", limit=2, cursor=p1.next_cursor)
    seen = {v.target_event_id for v in p1.items} | {v.target_event_id for v in p2.items}
    assert seen == {"n0", "n1", "n2"}
    assert len(seen) == 3


def test_scope_pagination(tmp_path):
    items = [_make_env(f"e{i}", sanitized_content={"text": f"content {i}"}, project_id="P") for i in range(5)]
    jl = tmp_path / "c.jsonl"
    _write_jsonl(jl, items)
    store = _open_store(tmp_path, "m.sqlite")
    from src.storage.ingest import ingest_file
    ingest_file(store, jl)
    _checkpoint_and_close(store)
    rs = open_readonly(tmp_path / "m.sqlite")
    assert len(list_project(rs, "P")) == 5


# ---- cursor binding ----
def _build_hub_corpus(tmp_path):
    """Live (non-deleted) hub with 3 incoming edges, for pagination/cursor tests."""
    hub = "hub"
    items = [_make_env(hub, sanitized_content={"text": "hub content"}, project_id="P")]
    for i in range(3):
        items.append(_make_env(f"n{i}", sanitized_content={"text": f"node {i}"}, project_id="P",
                               relation_ids=[hub]))
    jl = tmp_path / "c.jsonl"
    _write_jsonl(jl, items)
    store = _open_store(tmp_path, "m.sqlite")
    from src.storage.ingest import ingest_file
    ingest_file(store, jl)
    _checkpoint_and_close(store)
    return open_readonly(tmp_path / "m.sqlite")


def test_relation_cursor_query_binding(tmp_path):
    rs = _build_hub_corpus(tmp_path)
    cur = get_related(rs, "hub", direction="incoming", limit=1).next_cursor
    with pytest.raises(QueryError) as ei:
        get_related(rs, "hub", direction="outgoing", limit=1, cursor=cur)
    assert ei.value.code == CURSOR_QUERY_MISMATCH


def test_relation_cursor_limit_binding(tmp_path):
    rs = _build_hub_corpus(tmp_path)
    cur = get_related(rs, "hub", direction="incoming", limit=2).next_cursor
    with pytest.raises(QueryError) as ei:
        get_related(rs, "hub", direction="incoming", limit=1, cursor=cur)
    assert ei.value.code == CURSOR_LIMIT_MISMATCH


def test_relation_invalid_limit(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    with pytest.raises(QueryError) as ei:
        get_related(rs, "d1", limit=0)
    assert ei.value.code == INVALID_LIMIT


# ---- secret safety ----
def test_relation_output_no_secret(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    blob = json.dumps(dataclasses.asdict(get_related(rs, "d1")))
    assert SECRET not in blob


def test_scope_output_no_secret(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    blob = json.dumps([dataclasses.asdict(e) for e in list_project(rs, "P")])
    assert SECRET not in blob


# ---- TRUE READ-ONLY proof ----
RELATION_TABLES = ("zm_relations", "zm_scopes", "zm_artifacts")


def _relation_snapshot(rs, jsonl):
    # Snapshot expects a store with ._conn and .path; ReadonlyStore uses .conn/.path.
    class _Adapter:
        _conn = rs.conn
        path = rs.path
    return Snapshot(_Adapter(), jsonl)


def test_sqlite_unchanged_after_relation_queries(tmp_path):
    jl = _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    s0 = _relation_snapshot(rs, jl)
    get_related(rs, "p0")
    get_related(rs, "d1", direction="outgoing")
    get_related(rs, "d1", relation_type="derived_from")
    get_parent(rs, "c1")
    get_children(rs, "p0")
    get_artifacts(rs, "d1")
    list_project(rs, "P")
    list_profile(rs, "U")
    list_knowledge_space(rs, "KS")
    s1 = _relation_snapshot(rs, jl)
    # Derived-table + JSONL + schema + meta proof (from M3.1 Snapshot).
    s1.assert_unchanged(s0)
    # Explicitly prove the relation/scope/artifact tables are unchanged.
    for t in RELATION_TABLES:
        assert s1.counts.get(t) == s0.counts.get(t), f"{t} row count changed"


def test_relation_tables_unchanged(tmp_path):
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    before = {t: rs.conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"] for t in RELATION_TABLES}
    get_related(rs, "d1")
    after = {t: rs.conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"] for t in RELATION_TABLES}
    assert before == after


def test_jsonl_unchanged(tmp_path):
    jl = _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    h0 = hashlib.sha256(open(jl, "rb").read()).hexdigest()
    get_related(rs, "d1")
    h1 = hashlib.sha256(open(jl, "rb").read()).hexdigest()
    assert h0 == h1


# ---- exclusions: no LLM / network / real home / authz / M3.5+ / M4 ----
def test_no_real_hermes_home_writes_during_relations(tmp_path, monkeypatch):
    real_home = Path.home() / ".hermes"
    writes = {"n": 0}
    _orig_open = open

    def _blocked_open(path, *a, **k):
        p = Path(str(path))
        if real_home == p or real_home in p.parents:
            writes["n"] += 1
            raise AssertionError(f"write to real home: {path}")
        return _orig_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", _blocked_open)
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    get_related(rs, "d1")
    get_artifacts(rs, "d1")
    list_knowledge_space(rs, "KS")
    assert writes["n"] == 0


def test_no_authorization_behavior(tmp_path):
    """M3.4 honors caller-supplied scope filters only; no access-control logic."""
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    assert len(list_project(rs, "P")) == 3


def test_no_m3_5_behavior(tmp_path):
    """M3.4 exposes stored verification metadata but adds no trust/verification policy."""
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    for v in get_related(rs, "d1").items:
        assert hasattr(v.target, "verification_status")
        assert not hasattr(v, "trust_score")


def test_no_m4_behavior(tmp_path):
    """M3.4 does not route or write to project memory."""
    _ingest_relations_corpus(tmp_path)
    rs = open_readonly(tmp_path / "m.sqlite")
    res = get_related(rs, "d1")
    assert not hasattr(res, "routed_to")
