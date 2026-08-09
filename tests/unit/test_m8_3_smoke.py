"""M8.3 smoke test — verify wiring before the full focused suite."""

from src.m8.graph_access import GraphAccessService, GraphReadRequest

import tests.unit.test_m8_3_helpers as H


def test_smoke_authorized_seed_returns_subgraph():
    store = H.build_fixture()
    svc = GraphAccessService(H.make_service(store, "PR1"))
    req = GraphReadRequest(resource_id="ART-A", resource_type="artifact",
                           requesting_profile_id="PR1", project_id="P1")
    res = svc.read_subgraph(req)
    assert res.authorized is True
    assert res.resource_id == "ART-A"
    # Seed node present.
    ids = {n.resource_id for n in res.nodes}
    assert "ART-A" in ids
    # Authorized neighbour ART-A2 reachable via source_of.
    assert "ART-A2" in ids
    # Hidden DEC-B must NOT appear.
    assert "DEC-B" not in ids
    # Hidden continuation REQ-C reachable only through DEC-B must NOT appear.
    assert "REQ-C" not in ids
    store.close()


def test_smoke_denied_seed_no_graph_info():
    store = H.build_fixture()
    svc = GraphAccessService(H.make_service(store, "PR1"))
    req = GraphReadRequest(resource_id="DEC-B", resource_type="decision",
                           requesting_profile_id="PR1", project_id="P2")
    res = svc.read_subgraph(req)
    assert res.authorized is False
    assert res.nodes == ()
    assert res.edges == ()
    assert res.provenance == {}
    store.close()


if __name__ == "__main__":
    test_smoke_authorized_seed_returns_subgraph()
    test_smoke_denied_seed_no_graph_info()
    print("smoke ok")
