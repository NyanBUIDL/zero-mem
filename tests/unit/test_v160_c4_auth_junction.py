"""V1.6.0 C4 RED-first — authorization: union read + per-row grant qua junction.

ADR-V160-01 sec7 (plan C4; DEF-034 -> V1.6.0):
- per-row space authorization uses the multi-KS junction (correlated EXISTS,
  never a direct JOIN -> no duplication); grant ∩ row.ks != empty authorizes;
- request KS list = UNION; NULL/empty KS is never space-grant authorized;
- cursor fingerprint binds the canonicalized (sorted+dedup) KS set;
- matrix NULL/legacy/global/local/grant is behavioral; DEF-028 regression kept.

RED on current tree: _ks_predicate filters the SINGULAR denormalized
zm_meta.knowledge_space_id (PRIMARY-KS) and _scope_allows checks only the
singular value, so a multi-KS event [A,B] (PRIMARY A) is NOT authorized by a
grant/filter for B — it must be (junction EXISTS finds B).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest

from src.access import AccessRequest, ReasonCode
from src.access import grant_events, resolver
from src.access.authorized_read import AuthorizedReadService, _scope_allows
from src.access.contracts import AllowedScope
from src.retrieval.db import open_readonly
from src.retrieval.models import QueryError
from src.storage.ingest import ingest_file
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from tests.unit.test_m3_query import _checkpoint_and_close, _make_env, _write_jsonl
from tests.unit.test_v160_c2_junction import _insert_legacy_meta


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _build(tmp_path, items, name="c4.sqlite", grants=()):
    """Write store: ingest canonical (junction populated) + persistent space grants."""
    jl = tmp_path / f"{name}.jsonl"
    _write_jsonl(jl, items)
    store = SQLiteStore(SQLiteStoreConfig(path=tmp_path / name))
    store.ensure_schema()
    ingest_file(store, jl)
    for gid, subject, target in grants:
        grant_events.project_grant_event(
            store._conn, grant_events.AccessGrantEvent(
                grant_id=gid, subject_profile=subject, operation="READ",
                target_type="knowledge_space", target_id=target, op="create"))
        store._conn.commit()
    _checkpoint_and_close(store)
    return str(tmp_path / name)


def _svc(db_path, requester="PR1"):
    ro = open_readonly(Path(db_path))
    grants = resolver.resolve_read_grants(ro.conn, requester)
    return ro, AuthorizedReadService(ro, requester, grant_conn=ro.conn), grants


def _standard_items():
    """Multi-KS / legacy / unscoped / cross-profile event set."""
    return [
        _make_env("ev1", profile_id="PR1", project_id="P",
                  knowledge_space_ids=["A", "B"]),          # PRIMARY A, multi-KS
        _make_env("ev2", profile_id="PR1", project_id="P",
                  knowledge_space_id="legacy-ks"),           # legacy singular
        _make_env("ev3", profile_id="PR1", project_id="P"),  # no ks (NULL)
        _make_env("ev4", profile_id="PR1", project_id="P",
                  knowledge_space_ids=[]),                   # explicit empty
        _make_env("ev5", profile_id="PR2", project_id="P",
                  knowledge_space_ids=["B"]),                # cross-profile in B
        _make_env("ev6", profile_id="PR2", project_id="P",
                  knowledge_space_ids=["C"]),                # cross-profile in C
        _make_env("ev7", profile_id=None, project_id="P",
                  knowledge_space_ids=["B"]),                # NULL-profile in B
        _make_env("ev8", profile_id=None, project_id="P"),   # NULL-profile NULL-ks
    ]


GRANT_B = [("GB", "PR1", "B")]
GRANT_AB = [("GA", "PR1", "A"), ("GB", "PR1", "B")]
GRANT_LEGACY = [("GL", "PR1", "legacy-ks")]


class TestC4JunctionAuthorization:
    def test_query_multi_ks_authorized_by_non_primary_grant(self, tmp_path):
        """RED core: ev1 [A,B] (PRIMARY A) must be returned by a grant/filter for B."""
        db = _build(tmp_path, _standard_items(), grants=GRANT_B)
        ro, svc, grants = _svc(db)
        try:
            res = svc.query_events(AccessRequest(
                operation="READ", requesting_profile_id="PR1",
                knowledge_space_ids=["B"]), grants=grants)
            assert res.allowed is True
            ids = {v.event_id for v in res.items}
            assert "ev1" in ids, (
                "multi-KS event [A,B] must be authorized by space B via the "
                "junction (current RED: singular PRIMARY-KS A misses it)")
            assert "ev5" in ids, "cross-profile space grant must authorize ev5 (B)"
            assert "ev6" not in ids, "space C not granted"
            assert "ev2" not in ids, "legacy-ks not in granted space B"
            assert "ev3" not in ids, "NULL ks never space-grant authorized"
            assert "ev4" not in ids, "empty ks never space-grant authorized"
            assert "ev8" not in ids, "NULL-profile NULL-ks not space-grant authorized"
        finally:
            ro.close()

    def test_get_event_multi_ks_authorized_by_non_primary_grant(self, tmp_path):
        db = _build(tmp_path, _standard_items(), grants=GRANT_B)
        ro, svc, grants = _svc(db)
        try:
            res = svc.get_event(AccessRequest(
                operation="READ", requesting_profile_id="PR1",
                knowledge_space_ids=["B"]), "ev1", grants=grants)
            assert res.allowed is True, (
                "get_event must authorize multi-KS [A,B] under space B "
                "(current RED: boundary violation on singular PRIMARY-KS A)")
            assert res.items and res.items[0].event_id == "ev1"
            # negative: caller has NO grant for C -> ev1 [A,B] has no
            # intersection with the requested space C
            res2 = svc.get_event(AccessRequest(
                operation="READ", requesting_profile_id="PR1",
                knowledge_space_ids=["C"]), "ev1", grants=[])
            assert not (res2.allowed and res2.items), (
                "ev1 [A,B] has no intersection with requested space C")
        finally:
            ro.close()

    def test_get_trace_multi_ks(self, tmp_path):
        items = [
            _make_env("tr1-e1", trace_id="TR1", profile_id="PR1", project_id="P",
                      knowledge_space_ids=["A", "B"]),
            _make_env("tr1-e2", trace_id="TR1", profile_id="PR1", project_id="P",
                      knowledge_space_ids=["B"]),
        ]
        db = _build(tmp_path, items, grants=GRANT_B)
        ro, svc, grants = _svc(db)
        try:
            res = svc.get_trace(AccessRequest(
                operation="READ", requesting_profile_id="PR1",
                knowledge_space_ids=["B"]), "TR1", grants=grants)
            assert res.allowed is True
            ids = {v.event_id for v in res.items}
            assert "tr1-e1" in ids and "tr1-e2" in ids
        finally:
            ro.close()

    def test_union_request_no_duplicate(self, tmp_path):
        """UNION [A,B] must return the [A,B] event EXACTLY once (EXISTS, not JOIN)."""
        db = _build(tmp_path, _standard_items(), grants=GRANT_AB)
        ro, svc, grants = _svc(db)
        try:
            res = svc.query_events(AccessRequest(
                operation="READ", requesting_profile_id="PR1",
                knowledge_space_ids=["A", "B"]), grants=grants)
            ids = [v.event_id for v in res.items]
            assert ids.count("ev1") == 1, "multi-KS event must appear exactly once"
        finally:
            ro.close()

    def test_grant_intersection_nonempty_semantics(self, tmp_path):
        db = _build(tmp_path, _standard_items(), grants=GRANT_B)
        ro, svc, grants = _svc(db)
        try:
            ok = svc.get_event(AccessRequest(
                operation="READ", requesting_profile_id="PR1",
                knowledge_space_ids=["B"]), "ev1", grants=grants)
            assert ok.allowed and ok.items
            res = svc.query_events(AccessRequest(
                operation="READ", requesting_profile_id="PR1",
                knowledge_space_ids=["C"]), grants=[])
            assert "ev1" not in {v.event_id for v in res.items}
        finally:
            ro.close()

    def test_null_and_empty_ks_not_grant_authorized(self, tmp_path):
        db = _build(tmp_path, _standard_items(), grants=GRANT_B)
        ro, svc, grants = _svc(db)
        try:
            res = svc.query_events(AccessRequest(
                operation="READ", requesting_profile_id="PR1",
                knowledge_space_ids=["B"]), grants=grants)
            ids = {v.event_id for v in res.items}
            assert "ev3" not in ids and "ev4" not in ids, (
                "NULL/empty KS rows must never be space-grant authorized")
        finally:
            ro.close()

    def test_legacy_singular_grant(self, tmp_path):
        db = _build(tmp_path, _standard_items(), grants=GRANT_LEGACY)
        ro, svc, grants = _svc(db)
        try:
            res = svc.query_events(AccessRequest(
                operation="READ", requesting_profile_id="PR1",
                knowledge_space_ids=["legacy-ks"]), grants=grants)
            ids = {v.event_id for v in res.items}
            assert "ev2" in ids, "legacy singular event must be grant-authorized"
        finally:
            ro.close()

    def test_pagination_no_skip_no_dup_multi_ks(self, tmp_path):
        items = [
            _make_env(f"m{i}", profile_id="PR1", project_id="P",
                      knowledge_space_ids=["A", "B"] if i % 2 else ["B"])
            for i in range(10)
        ]
        db = _build(tmp_path, items, grants=GRANT_AB)
        ro, svc, grants = _svc(db)
        try:
            seen = []
            cursor = None
            for _ in range(6):
                res = svc.query_events(AccessRequest(
                    operation="READ", requesting_profile_id="PR1",
                    knowledge_space_ids=["A", "B"]), grants=grants,
                    limit=3, cursor=cursor)
                seen.extend(v.event_id for v in res.items)
                cursor = res.next_cursor
                if cursor is None:
                    break
            assert len(seen) == len(set(seen)) == 10, (
                "pagination must not skip or duplicate multi-KS events")
        finally:
            ro.close()

    def test_cursor_fingerprint_binds_canonical_ks_set(self, tmp_path):
        """Fingerprint binds the KS filter canonicalized (sorted + dedup):
        [B,A] and [A,B] are the same query; [A] is a different query."""
        db = _build(tmp_path, _standard_items(), grants=GRANT_AB)
        ro, svc, grants = _svc(db)
        try:
            res = svc.query_events(AccessRequest(
                operation="READ", requesting_profile_id="PR1",
                knowledge_space_ids=["B", "A"]), grants=grants, limit=2)
            assert res.next_cursor is not None, "need a cursor to test binding"
            res2 = svc.query_events(AccessRequest(
                operation="READ", requesting_profile_id="PR1",
                knowledge_space_ids=["A", "B"]), grants=grants, limit=2,
                cursor=res.next_cursor)
            assert res2.allowed is True, "same canonical KS set must reuse the cursor"
            with pytest.raises(QueryError) as ei:
                svc.query_events(AccessRequest(
                    operation="READ", requesting_profile_id="PR1",
                    knowledge_space_ids=["A"]), grants=grants, limit=2,
                    cursor=res.next_cursor)
            assert "cursor" in str(ei.value.code).lower()
        finally:
            ro.close()

    def test_scope_allows_multi_ks_set(self):
        grant = AllowedScope(operation="READ", allowed_profile_ids=[],
                             allowed_knowledge_space_ids=["B"], is_grant=True)
        assert _scope_allows(grant, None, "PR2", "P",
                             row_knowledge_space_ids=["A", "B"]) is True
        assert _scope_allows(grant, None, "PR2", "P",
                             row_knowledge_space_ids=["A"]) is False
        assert _scope_allows(grant, None, "PR2", "P",
                             row_knowledge_space_ids=()) is False
        assert _scope_allows(grant, None, "PR2", "P",
                             row_knowledge_space_ids=None) is False

    def test_matrix_null_legacy_global_local_grant(self, tmp_path):
        """Behavioral matrix: (profile NULL/non-NULL) x (ks NULL/empty/list/legacy)
        across global / local / space-grant reads."""
        db = _build(tmp_path, _standard_items(),
                    grants=GRANT_B + GRANT_LEGACY)
        ro, svc, grants = _svc(db)
        try:
            # --- global default read (implicit, own profile + NULL-profile rows) ---
            g = svc.query_events(AccessRequest(
                operation="READ", requesting_profile_id="PR1"))
            gids = {v.event_id for v in g.items}
            assert {"ev1", "ev2", "ev3"} <= gids
            assert "ev8" in gids, "NULL-profile NULL-ks visible under global read"
            assert "ev5" not in gids, "PR2 not visible under own-profile global read"
            # --- local read (include_global=False) ---
            l = svc.query_events(AccessRequest(
                operation="READ", requesting_profile_id="PR1",
                include_global=False))
            lids = {v.event_id for v in l.items}
            assert "ev3" in lids and "ev8" not in lids, (
                "local read: own profile yes, NULL-profile no")
            # --- space-grant read (grant B only; legacy grant excluded so the
            # union-of-scopes cannot pull legacy content into the B result) ---
            g_b = [g for g in grants if g.target_id == "B"]
            b = svc.query_events(AccessRequest(
                operation="READ", requesting_profile_id="PR1",
                knowledge_space_ids=["B"]), grants=g_b)
            bids = {v.event_id for v in b.items}
            assert {"ev1", "ev5", "ev7"} <= bids, (
                "grant B: multi-KS [A,B], cross-profile B, NULL-profile B")
            assert not ({"ev2", "ev3", "ev4", "ev6", "ev8"} & bids), (
                "grant B must not include legacy-ks / NULL / empty / space-C / NULL-ks")
            # --- legacy grant only ---
            g_leg = [g for g in grants if g.target_id == "legacy-ks"]
            leg = svc.query_events(AccessRequest(
                operation="READ", requesting_profile_id="PR1",
                knowledge_space_ids=["legacy-ks"]), grants=g_leg)
            assert {v.event_id for v in leg.items} == {"ev2"}
        finally:
            ro.close()


class TestC4FailClosedJunction:
    """C4 review follow-up (P1): the junction is the ONLY authorization source
    for event-path space grants — a singular zm_meta.knowledge_space_id with NO
    junction row must NOT authorize (fail-closed). Proper legacy is v12 -> v13
    migration (junction backfill), never direct-seeded v13 rows."""

    def test_singular_no_junction_fail_closed(self, tmp_path):
        """RED on HEAD fdda95f: a row with zm_meta.knowledge_space_id='A' but NO
        junction row must NOT be authorized by a grant for A (junction missing/
        corrupt -> fail-closed; the pre-fix OR singular fallback leaks it)."""
        db = _build(tmp_path, [
            _make_env("evA", profile_id="PR1", project_id="P",
                      knowledge_space_id="A"),
        ], grants=GRANT_B)
        # simulate a missing/corrupt junction: delete all junction rows
        s = SQLiteStore(SQLiteStoreConfig(path=Path(db)))
        s.ensure_schema()
        s._conn.execute("DELETE FROM zm_event_spaces")
        s._conn.commit()
        _checkpoint_and_close(s)
        ro, svc, grants = _svc(db)
        try:
            res = svc.query_events(AccessRequest(
                operation="READ", requesting_profile_id="PR1",
                knowledge_space_ids=["A"]), grants=grants)
            assert "evA" not in {v.event_id for v in res.items}, (
                "junction missing -> fail-closed: singular zm_meta ks must NOT "
                "authorize (current RED: OR singular fallback leaks it)")
            gev = svc.get_event(AccessRequest(
                operation="READ", requesting_profile_id="PR1",
                knowledge_space_ids=["A"]), "evA", grants=grants)
            assert not (gev.allowed and gev.items), (
                "get_event must fail closed when the junction row is missing")
        finally:
            ro.close()

    def test_legacy_v12_upgrade_authorizes_via_junction(self, tmp_path):
        """Proper legacy compatibility: build schema v12, insert a singular row,
        run the migration runner up to v13 — the junction is BACKFILLED and the
        grant authorizes via the junction (never via the singular fallback)."""
        db_path = tmp_path / "legacy.sqlite"
        store = SQLiteStore(SQLiteStoreConfig(path=db_path))
        store.ensure_schema()
        store.downgrade_to(12, note="test")
        _insert_legacy_meta(store, "leg-1", "legacy-ks")
        store._conn.commit()
        assert store.ensure_schema() == 13, "migration runner must reach v13"
        _checkpoint_and_close(store)
        # grant for legacy-ks on the migrated store
        s2 = SQLiteStore(SQLiteStoreConfig(path=db_path))
        s2.ensure_schema()
        grant_events.project_grant_event(
            s2._conn, grant_events.AccessGrantEvent(
                grant_id="GL", subject_profile="PR1", operation="READ",
                target_type="knowledge_space", target_id="legacy-ks", op="create"))
        s2._conn.commit()
        _checkpoint_and_close(s2)
        ro, svc, grants = _svc(str(db_path))
        try:
            res = svc.query_events(AccessRequest(
                operation="READ", requesting_profile_id="PR1",
                knowledge_space_ids=["legacy-ks"]), grants=grants)
            ids = {v.event_id for v in res.items}
            assert "leg-1" in ids, (
                "v12->v13 migration must backfill the junction so the grant "
                "authorizes via the junction")
        finally:
            ro.close()
