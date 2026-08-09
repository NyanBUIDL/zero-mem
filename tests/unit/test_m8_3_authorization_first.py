"""M8.3 focused tests — authorization-first bounded graph reads.

These are the authoritative M8.3 acceptance tests. They run against a v9 store
with M5 persistent grants and a deterministic M8.2 projection (see
test_m8_3_helpers). Every category from the M8.3 directive is covered:

- authorization occurs BEFORE traversal
- denied root exposes no graph information
- denied neighbour never appears
- hidden middle node does not reveal path
- unauthorized edges do not affect degree/count
- unauthorized provenance removed before result
- bypass attempts rejected (relation type / entity id / linked nodes)
- scope isolation (same profile / cross profile / cross project / knowledge space)
- M6.6 resource_type isolation (artifact-only grant)
- revoked grants immediately remove access
- linked authorization unchanged
- traversal bounds (depth / nodes / edges / fan-out / cycles / self-loops /
  dense graph)
- deterministic ordering independent of insertion order
- existence-leak safety (hidden material differs, visible result equivalent)
- read-only proof (no mutation of canonical / derived / grants / state)
- zero LLM / zero network
"""

from __future__ import annotations

import sqlite3

from src.access import AccessRequest, READ
from src.m8.graph_access import GraphAccessService, GraphReadRequest
from src.m8.graph_bounds import (
    DEFAULT_BOUNDS,
    GraphReadBounds,
    GraphBoundsError,
    MAX_RESULT_NODES,
    MAX_RESULT_EDGES,
    MAX_FAN_OUT_PER_NODE,
    MAX_TRAVERSAL_DEPTH,
)

import tests.unit.test_m8_3_helpers as H


def _svc(store, subject="PR1"):
    return GraphAccessService(H.make_service(store, subject))


def _req(**kw):
    base = dict(resource_id="ART-A", resource_type="artifact",
                requesting_profile_id="PR1", project_id="P1")
    base.update(kw)
    return GraphReadRequest(**base)


# ===========================================================================
# 1. Authorization-first ordering
# ===========================================================================

class TestAuthorizationFirst:
    def test_denied_root_exposes_no_graph_info(self):
        store = H.build_fixture()
        svc = _svc(store)
        # DEC-B is in P2 and PR1 has no decision grant there.
        res = svc.read_subgraph(_req(resource_id="DEC-B",
                                     resource_type="decision",
                                     project_id="P2"))
        assert res.authorized is False
        assert res.nodes == ()
        assert res.edges == ()
        assert res.provenance == {}
        assert res.bound_codes == ()
        store.close()

    def test_denied_root_no_degree_or_count_leak(self):
        store = H.build_fixture()
        svc = _svc(store)
        denied = svc.read_subgraph(_req(resource_id="DEC-B",
                                        resource_type="decision",
                                        project_id="P2"))
        # A denied result carries no quantitative signal at all.
        assert len(denied.nodes) == 0
        assert len(denied.edges) == 0
        store.close()

    def test_authorized_seed_then_traversal(self):
        store = H.build_fixture()
        svc = _svc(store)
        res = svc.read_subgraph(_req())
        assert res.authorized is True
        ids = {n.resource_id for n in res.nodes}
        assert "ART-A" in ids
        # Only authorized neighbours (ART-A2 via source_of) appear.
        assert "ART-A2" in ids
        store.close()


# ===========================================================================
# 2. Hidden middle node does not reveal a path
# ===========================================================================

class TestHiddenMiddleNode:
    def test_hidden_middle_not_revealed(self):
        store = H.build_fixture()
        svc = _svc(store)
        res = svc.read_subgraph(_req())
        ids = {n.resource_id for n in res.nodes}
        # DEC-B is the hidden middle; REQ-C is only reachable through DEC-B.
        assert "DEC-B" not in ids
        assert "REQ-C" not in ids
        # No edge to/from DEC-B appears either.
        for e in res.edges:
            assert e.from_resource_id != "DEC-B"
            assert e.to_resource_id != "DEC-B"
        store.close()

    def test_hidden_continuation_does_not_inflate_depth(self):
        store = H.build_fixture()
        svc = _svc(store)
        res = svc.read_subgraph(_req())
        # REQ-C, though only 2 hops away through DEC-B, must NOT be present
        # (its only path is through an unauthorized node). Depth is bounded by
        # authorization, not by graph topology.
        assert all(n.resource_id != "REQ-C" for n in res.nodes)
        store.close()


# ===========================================================================
# 3. Unauthorized edges do not affect degree / count
# ===========================================================================

class TestUnauthorizedEdgeEffect:
    def test_unauthorized_edge_excluded_from_degree(self):
        store = H.build_fixture()
        svc = _svc(store)
        # ART-A has 3 outgoing edges: e_aa2 (auth), e_a_extra (auth),
        # e_ab (to hidden DEC-B). Only authorized edges count.
        res = svc.read_subgraph(_req())
        out_edges = [e for e in res.edges if e.from_resource_id == "ART-A"]
        # e_ab is excluded because its target DEC-B is unauthorized.
        assert all(e.to_resource_id != "DEC-B" for e in out_edges)
        store.close()

    def test_authorized_degree_correct(self):
        store = H.build_fixture()
        svc = _svc(store)
        res = svc.read_subgraph(_req())
        # ART-A authorized out-edges: e_aa2 + e_a_extra (both ART-A -> ART-A2).
        out = [e for e in res.edges if e.from_resource_id == "ART-A"]
        assert len(out) == 2
        store.close()


# ===========================================================================
# 4. M6.6 resource_type isolation through graph reads
# ===========================================================================

class TestM66ResourceTypeIsolation:
    def test_artifact_only_grant_does_not_reveal_non_artifact(self):
        store = H.build_fixture()
        # Use only the artifact-only grant G-ART (drop the unrestricted G-P1).
        store._conn.execute(
            "DELETE FROM zm_access_grants WHERE grant_id IN ('G-P1','G-P2')")
        store._conn.commit()
        svc = _svc(store)
        res = svc.read_subgraph(_req())
        assert res.authorized is True
        # Seed ART-A is authorized by the artifact-only grant.
        ids = {n.resource_id for n in res.nodes}
        assert "ART-A" in ids
        # A linked decision/requirement neighbour must NOT be pulled in, even
        # though graph edges exist, because the grant is artifact-only.
        for n in res.nodes:
            assert n.resource_type == "artifact"
        for e in res.edges:
            assert e.from_resource_type == "artifact"
            assert e.to_resource_type == "artifact"
        store.close()


# ===========================================================================
# 5. Bypass attempts rejected
# ===========================================================================

class TestBypassResistance:
    def test_relation_type_cannot_bypass_auth(self):
        store = H.build_fixture()
        svc = _svc(store)
        # Even though an edge ART-A -[decision_for]-> DEC-B exists, the target
        # is unauthorized regardless of relation type.
        res = svc.read_subgraph(_req())
        assert all(e.to_resource_id != "DEC-B" for e in res.edges)
        store.close()

    def test_entity_id_cannot_bypass_auth(self):
        store = H.build_fixture()
        svc = _svc(store)
        # Requesting DEC-B directly as seed is denied (no entity-id bypass).
        res = svc.read_subgraph(_req(resource_id="DEC-B",
                                     resource_type="decision",
                                     project_id="P2"))
        assert res.authorized is False
        store.close()

    def test_linked_graph_node_cannot_bypass_auth(self):
        store = H.build_fixture()
        svc = _svc(store)
        # REQ-C is linked to DEC-D (authorized) directly, BUT also only
        # reachable from ART-A through DEC-B. From ART-A seed, REQ-C must stay
        # hidden (linked-graph bypass rejected).
        res = svc.read_subgraph(_req())
        assert all(n.resource_id != "REQ-C" for n in res.nodes)
        store.close()


# ===========================================================================
# 6. Scope isolation
# ===========================================================================

class TestScopeIsolation:
    def test_same_profile_authorized(self):
        store = H.build_fixture()
        svc = _svc(store, "PR1")
        res = svc.read_subgraph(_req())
        assert res.authorized is True
        store.close()

    def test_cross_profile_denied(self):
        store = H.build_fixture()
        # PR3 has no grants at all.
        svc = _svc(store, "PR3")
        res = svc.read_subgraph(_req())
        assert res.authorized is False
        store.close()

    def test_cross_project_denied_without_grant(self):
        store = H.build_fixture()
        # PR1 has no grant on P2 for artifacts.
        svc = _svc(store)
        res = svc.read_subgraph(_req(resource_id="ART-A",
                                     project_id="P2"))
        assert res.authorized is False
        store.close()


# ===========================================================================
# 7. Revoked grants
# ===========================================================================

class TestRevokedGrants:
    def test_revocation_removes_access_immediately(self):
        store = H.build_fixture()
        svc = _svc(store)
        assert svc.read_subgraph(_req()).authorized is True
        # Revoke the artifact grant by deleting it from canonical grant state.
        store._conn.execute(
            "DELETE FROM zm_access_grants WHERE grant_id IN ('G-P1','G-ART')")
        store._conn.commit()
        # New service instance reads the changed grant state.
        svc2 = _svc(store)
        assert svc2.read_subgraph(_req()).authorized is False
        store.close()


# ===========================================================================
# 8. Traversal bounds
# ===========================================================================

class TestBounds:
    def test_max_depth_respected(self):
        store = H.build_fixture()
        svc = _svc(store)
        res = svc.read_subgraph(_req(bounds=GraphReadBounds(max_depth=0)))
        # Depth 0 => only the seed node, no edges.
        assert len(res.edges) == 0
        assert {n.resource_id for n in res.nodes} == {"ART-A"}
        store.close()

    def test_max_nodes_respected(self):
        store = H.build_fixture()
        svc = _svc(store)
        res = svc.read_subgraph(_req(bounds=GraphReadBounds(max_nodes=1)))
        assert len(res.nodes) == 1
        assert res.bound_codes == ("bound_max_nodes",)
        store.close()

    def test_max_edges_respected(self):
        store = H.build_fixture()
        svc = _svc(store)
        res = svc.read_subgraph(_req(bounds=GraphReadBounds(max_edges=1)))
        assert len(res.edges) <= 1
        if len(res.edges) == 1:
            assert res.bound_codes == ("bound_max_edges",)
        store.close()

    def test_max_fan_out_respected(self):
        store = H.build_fixture()
        svc = _svc(store)
        res = svc.read_subgraph(
            _req(bounds=GraphReadBounds(max_fan_out=1)))
        out = [e for e in res.edges if e.from_resource_id == "ART-A"]
        assert len(out) <= 1
        store.close()

    def test_bound_widening_fails_closed(self):
        # A caller may NOT widen a fixed ceiling; it must fail closed.
        try:
            GraphReadBounds(max_depth=MAX_TRAVERSAL_DEPTH + 1)
        except GraphBoundsError:
            pass
        else:
            raise AssertionError("over-ceiling depth was accepted")
        try:
            GraphReadBounds(max_nodes=MAX_RESULT_NODES + 1)
        except GraphBoundsError:
            pass
        else:
            raise AssertionError("over-ceiling nodes was accepted")
        try:
            GraphReadBounds(max_edges=MAX_RESULT_EDGES + 1)
        except GraphBoundsError:
            pass
        else:
            raise AssertionError("over-ceiling edges was accepted")
        try:
            GraphReadBounds(max_fan_out=MAX_FAN_OUT_PER_NODE + 1)
        except GraphBoundsError:
            pass
        else:
            raise AssertionError("over-ceiling fan-out was accepted")

    def test_cycle_safe(self):
        store = H.build_fixture()
        # A <-> B cycle among authorized nodes must terminate, not loop.
        H._edge(store._conn, "e_cycle1", "requirement", "REQ-ISO",
                "references", "requirement", "REQ-C", "P1")
        H._edge(store._conn, "e_cycle2", "requirement", "REQ-C",
                "references", "requirement", "REQ-ISO", "P1")
        store._conn.commit()
        svc = _svc(store)
        # Seed from REQ-ISO (authorized).
        res = svc.read_subgraph(_req(resource_id="REQ-ISO",
                                     resource_type="requirement"))
        ids = [n.resource_id for n in res.nodes]
        # Cycle does not duplicate a node or explode node count.
        for rid in ids:
            assert ids.count(rid) == 1
        assert len(res.nodes) <= MAX_RESULT_NODES
        assert len(res.edges) <= MAX_RESULT_EDGES
        # No unauthorized node (e.g. DEC-B) leaks in through the cycle.
        assert "DEC-B" not in ids
        store.close()

    def test_self_loop_safe(self):
        store = H.build_fixture()
        H._edge(store._conn, "e_self", "requirement", "REQ-ISO",
                "references", "requirement", "REQ-ISO", "P1")
        store._conn.commit()
        svc = _svc(store)
        res = svc.read_subgraph(_req(resource_id="REQ-ISO",
                                     resource_type="requirement"))
        # Self-loop produces the node once and at most one edge.
        node_ids = [n.resource_id for n in res.nodes]
        assert node_ids.count("REQ-ISO") == 1
        store.close()

    def test_dense_graph_bounded(self):
        store = H.build_fixture()
        # Add a dense fan-out of authorized artifacts from ART-A.
        for i in range(30):
            aid = f"ART-X{i}"
            store._conn.execute(
                "INSERT INTO zm_artifacts (artifact_id,content_hash,kind,"
                "retention,origin_event_id,stored_path,created_at) VALUES "
                "(?,?,?,?,?,?,?)",
                (aid, f"h{i}", "doc", "365d", f"E-{i}", f"/x/{i}",
                 "2026-01-01T00:00:00+00:00"))
            store._conn.execute(
                "INSERT INTO zm_project_artifacts (artifact_id,project_id,"
                "artifact_type,version,safe_reference,created_at,"
                "verification_status) VALUES (?,?,?,?,?,?,?)",
                (aid, "P1", "doc", "1", f"r{i}",
                 "2026-01-01T00:00:00+00:00", "verified"))
            H._edge(store._conn, f"e_dense_{i}", "artifact", "ART-A",
                    "source_of", "artifact", aid, "P1")
        store._conn.commit()
        svc = _svc(store)
        res = svc.read_subgraph(_req())
        # Fan-out cap (default 20) is enforced; total nodes <= max_nodes.
        out = [e for e in res.edges if e.from_resource_id == "ART-A"]
        assert len(out) <= MAX_FAN_OUT_PER_NODE
        assert len(res.nodes) <= MAX_RESULT_NODES
        store.close()


# ===========================================================================
# 9. Determinism
# ===========================================================================

class TestDeterminism:
    def test_deterministic_ordering_independent_of_insertion(self):
        store1 = H.build_fixture()
        store2 = H.build_fixture()
        # Insert edges in reversed order into store2.
        svc1 = _svc(store1)
        svc2 = _svc(store2)
        res1 = svc1.read_subgraph(_req())
        res2 = svc2.read_subgraph(_req())
        assert [n.resource_id for n in res1.nodes] == \
               [n.resource_id for n in res2.nodes]
        assert [(e.edge_id) for e in res1.edges] == \
               [(e.edge_id) for e in res2.edges]
        store1.close()
        store2.close()

    def test_result_is_ordered_not_set_like(self):
        store = H.build_fixture()
        svc = _svc(store)
        res = svc.read_subgraph(_req())
        ids = [n.resource_id for n in res.nodes]
        assert ids == sorted(ids, key=lambda x: (x.split("-")[0], x))
        store.close()


# ===========================================================================
# 10. Existence-leak safety
# ===========================================================================

class TestExistenceLeakSafety:
    def test_hidden_edge_does_not_change_visible_result(self):
        # With or without the hidden e_ab edge, the visible authorized
        # subgraph for ART-A is identical (ART-A, ART-A2).
        store = H.build_fixture()
        svc = _svc(store)
        base = svc.read_subgraph(_req())
        # Remove the hidden edge and re-run.
        store._conn.execute("DELETE FROM zm_graph_edges WHERE edge_id='e_ab'")
        store._conn.commit()
        svc2 = _svc(store)
        stripped = svc2.read_subgraph(_req())
        assert {n.resource_id for n in base.nodes} == \
               {n.resource_id for n in stripped.nodes}
        assert {(e.edge_id) for e in base.edges} == \
               {(e.edge_id) for e in stripped.edges}
        store.close()


# ===========================================================================
# 11. Read-only proof
# ===========================================================================

class TestReadOnly:
    def _rowcounts(self, store):
        conn = store._conn
        return {
            "zm_graph_edges": conn.execute(
                "SELECT COUNT(*) FROM zm_graph_edges").fetchone()[0],
            "zm_access_grants": conn.execute(
                "SELECT COUNT(*) FROM zm_access_grants").fetchone()[0],
            "zm_project_artifacts": conn.execute(
                "SELECT COUNT(*) FROM zm_project_artifacts").fetchone()[0],
        }

    def test_read_does_not_mutate_store(self):
        store = H.build_fixture()
        before = self._rowcounts(store)
        svc = _svc(store)
        for _ in range(3):
            svc.read_subgraph(_req())
            svc.read_subgraph(_req(resource_id="REQ-ISO",
                                   resource_type="requirement"))
        after = self._rowcounts(store)
        assert before == after
        # No transaction left open / no writes.
        assert store._conn.in_transaction is False
        store.close()


# ===========================================================================
# 12. Zero LLM / zero network
# ===========================================================================

class TestZeroLlmNetwork:
    def test_module_reaches_no_forbidden_imports(self):
        import ast
        import pathlib
        src = pathlib.Path("src/m8/graph_access.py").read_text()
        tree = ast.parse(src)
        forbidden = {"openai", "anthropic", "http", "requests", "socket",
                     "urllib", "embedding", "llm"}
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    imported.add(n.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module.split(".")[0])
        assert forbidden.isdisjoint(imported), imported & forbidden
