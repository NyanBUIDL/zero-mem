"""T21 - tombstones for rule/decision/gotcha imports: withdraw a pending proposal; never silently delete approved memory."""
from __future__ import annotations

import pytest

pytest.importorskip("cryptography")

from tests.unit.t20_helpers import Site, pair  # noqa: E402
from zero_mem.learning import Reviewer  # noqa: E402
from zero_mem.memory import Memory  # noqa: E402
from zero_mem.share import client  # noqa: E402


@pytest.fixture
def world(tmp_path):
    owner, peer = Site(tmp_path, "owner"), Site(tmp_path, "peer")
    server = pair(owner, peer, grants=[{"space": "ks-shared"}])
    yield owner, peer, server
    server.stop()
    owner.close()
    peer.close()


def proposals(peer, status="all"):
    mem = Memory.open("peer-import", data_root=peer.root, settings_path=peer.settings)
    try:
        return mem.proposals(status)
    finally:
        mem.close()


@pytest.mark.parametrize("mtype", ["rule", "decision", "gotcha"])
def test_pending_proposal_is_withdrawn(world, mtype):
    owner, peer, _ = world
    res = owner.add("Never deploy on Fridays at all", mtype, name="nofri")
    assert client.pull(peer.node, "owner").proposed == 1
    assert [p["status"] for p in proposals(peer)] == ["pending"]
    assert owner.mem.forget(res.source_id).status == "forgotten"
    rep = client.pull(peer.node, "owner")
    assert rep.withdrawn == 1 and rep.revoke_proposed == [] and rep.tombstones_skipped == 0
    assert [p["status"] for p in proposals(peer)] == ["withdrawn"]
    again = client.pull(peer.node, "owner")
    assert again.withdrawn == 0 and again.proposed == 0


def test_approved_rule_is_never_silently_deleted(world):
    owner, peer, _ = world
    res = owner.add("Always write tests first", "rule", name="tdd")
    client.pull(peer.node, "owner")
    pid = proposals(peer, "pending")[0]["id"]
    approved = Reviewer(peer.node.layout, settings_path=peer.settings).approve(pid)
    assert approved.status == "approved"
    owner.mem.forget(res.source_id)
    rep = client.pull(peer.node, "owner")
    assert rep.withdrawn == 0 and rep.tombstoned == 0
    assert len(rep.revoke_proposed) == 1 and rep.revoke_proposed[0]["proposal_id"] == pid
    assert [p["status"] for p in proposals(peer)] == ["approved"]  # still approved, still active
    mem = peer.node.memory
    registry, _b = mem._corpus()
    registry.refresh()
    live = [r for r in registry.all_records() if r.external_ref == approved.external_ref]
    assert live and live[-1].lifecycle_status != "deleted"
    events = [e for e in peer.node.audit(200) if e["op"] == "import" and e.get("outcome") == "revoke_proposed"]
    assert len(events) == 1
    assert client.pull(peer.node, "owner").revoke_proposed == []  # reported once


def test_rejected_proposal_tombstone_is_harmless(world):
    owner, peer, _ = world
    res = owner.add("Use tabs everywhere", "gotcha", name="tabs")
    client.pull(peer.node, "owner")
    pid = proposals(peer, "pending")[0]["id"]
    assert Reviewer(peer.node.layout, settings_path=peer.settings).reject(pid).status == "rejected"
    owner.mem.forget(res.source_id)
    rep = client.pull(peer.node, "owner")
    assert (rep.withdrawn, rep.revoke_proposed, rep.tombstones_skipped) == (0, [], 0)
    assert [p["status"] for p in proposals(peer)] == ["rejected"]
