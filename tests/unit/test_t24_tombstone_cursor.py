"""T24 findings 1, 2 and 4 - tie-safe tombstone cursor, no cursor advance past an unapplied tombstone, all pending versions
of a learned source are withdrawn."""
from __future__ import annotations

import pytest

pytest.importorskip("cryptography")

from tests.unit.t20_helpers import Site, pair  # noqa: E402
from zero_mem.learning import Reviewer  # noqa: E402
from zero_mem.memory import Memory  # noqa: E402
from zero_mem.share import client, owner as owner_mod  # noqa: E402
from zero_mem.share.util import b64_decode_strict  # noqa: E402,F401

SECOND = "2031-05-06T07:08:09+00:00"


@pytest.fixture
def world(tmp_path):
    owner, peer = Site(tmp_path, "owner"), Site(tmp_path, "peer")
    server = pair(owner, peer, grants=[{"space": "ks-shared"}])
    yield owner, peer
    server.stop()
    owner.close()
    peer.close()


def _pid(peer):
    return peer.node.identity().peer_id


def _forget_at(monkeypatch, owner, res, stamp=SECOND):
    import src.corpus.registry as reg

    monkeypatch.setattr(reg, "_now", lambda: stamp)
    try:
        assert owner.mem.forget(res.source_id).status == "forgotten"
    finally:
        monkeypatch.undo()


def _page(service, peer, **kw):
    return service.tombstones(_pid(peer), kw.pop("since", "1970-01-01T00:00:00Z"), **kw)


# ------------------------------------------------------------------ finding 1
def test_same_second_tombstones_page_exactly_once(world, monkeypatch):
    owner, peer = world
    results = [owner.add(f"note number {i}", "fact", name=f"n{i}") for i in range(5)]
    for res in results:
        _forget_at(monkeypatch, owner, res)
    monkeypatch.setattr(owner_mod, "MAX_TOMBSTONES", 2)
    service = owner.node.owner_service()
    seen, after, since = [], None, "1970-01-01T00:00:00Z"
    for _ in range(10):
        page = _page(service, peer, since=since, after=after)
        seen += [t["source_id"] for t in page["tombstones"]]
        if not page["more"]:
            break
        after = page["next"]
    assert sorted(seen) == sorted(r.source_id for r in results)
    assert len(seen) == len(set(seen)) == 5


def test_client_applies_all_same_second_tombstones_with_small_pages(world, monkeypatch):
    owner, peer = world
    results = [owner.add(f"note number {i}", "fact", name=f"n{i}") for i in range(5)]
    assert client.pull(peer.node, "owner").stored == 5
    for res in results:
        _forget_at(monkeypatch, owner, res)
    monkeypatch.setattr(owner_mod, "MAX_TOMBSTONES", 2)
    assert client.pull(peer.node, "owner").tombstoned == 5


def test_tombstone_later_in_the_saved_cursor_second_is_not_missed(world, monkeypatch):
    owner, peer = world
    first = owner.add("first note", "fact", name="first")
    second = owner.add("second note", "fact", name="second")
    assert client.pull(peer.node, "owner").stored == 2
    _forget_at(monkeypatch, owner, first)
    assert client.pull(peer.node, "owner").tombstoned == 1
    _forget_at(monkeypatch, owner, second)  # same second as the saved cursor
    assert client.pull(peer.node, "owner").tombstoned == 1
    assert client.pull(peer.node, "owner").tombstoned == 0  # exactly once


def test_old_since_parameter_still_works(world, monkeypatch):
    owner, peer = world
    res = owner.add("some note", "fact", name="n")
    _forget_at(monkeypatch, owner, res)
    page = _page(owner.node.owner_service(), peer, since="2031-05-06T07:08:09Z")
    assert [t["source_id"] for t in page["tombstones"]] == [res.source_id]
    assert _page(owner.node.owner_service(), peer, since="2031-05-06T07:08:10Z")["tombstones"] == []


# ------------------------------------------------------------------ finding 2
def test_failed_tombstone_does_not_advance_the_cursor_and_retries_once(world, monkeypatch):
    owner, peer = world
    a = owner.add("note a", "fact", name="a")
    b = owner.add("note b", "fact", name="b")
    assert client.pull(peer.node, "owner").stored == 2
    _forget_at(monkeypatch, owner, a, "2031-05-06T07:08:09+00:00")
    _forget_at(monkeypatch, owner, b, "2031-05-06T07:08:11+00:00")
    real = peer.node.memory._operator_forget
    calls = {"n": 0}

    class Boom:
        status = "error"

    def flaky(ref):
        calls["n"] += 1
        return Boom() if calls["n"] == 1 else real(ref)

    monkeypatch.setattr(peer.node.memory, "_operator_forget", flaky)
    rep = client.pull(peer.node, "owner")
    assert rep.tombstoned == 0 and rep.tombstones_failed and rep.tombstones_failed[0]["ref"] == "mem://fact/a"
    assert "tombstones_failed" in rep.as_dict()
    rep2 = client.pull(peer.node, "owner")
    assert rep2.tombstoned == 2 and not rep2.tombstones_failed
    assert client.pull(peer.node, "owner").tombstoned == 0


# ------------------------------------------------------------------ finding 4
def _props(peer, status="all"):
    mem = Memory.open("peer-import", data_root=peer.root, settings_path=peer.settings)
    try:
        return mem.proposals(status)
    finally:
        mem.close()


def _change(owner, res_name, text):
    return owner.add(text, "rule", name=res_name)


def test_changed_rule_withdraws_the_previous_pending_proposal(world):
    owner, peer = world
    v1 = owner.add("Always write tests first please", "rule", name="tdd")
    client.pull(peer.node, "owner")
    v2 = owner.add("Always write tests first, then code", "rule", name="tdd")
    assert v2.source_id == v1.source_id
    client.pull(peer.node, "owner")
    statuses = sorted(p["status"] for p in _props(peer))
    assert statuses == ["pending", "withdrawn"]
    owner.mem.forget(v1.source_id)
    rep = client.pull(peer.node, "owner")
    assert rep.withdrawn == 1
    assert sorted(p["status"] for p in _props(peer)) == ["withdrawn", "withdrawn"]


def test_approved_v1_is_kept_while_v2_is_pending_then_revoke_proposed(world):
    owner, peer = world
    v1 = owner.add("Always write tests first please", "rule", name="tdd")
    client.pull(peer.node, "owner")
    pid1 = _props(peer, "pending")[0]["id"]
    assert Reviewer(peer.node.layout, settings_path=peer.settings).approve(pid1).status == "approved"
    owner.add("Always write tests first, then code", "rule", name="tdd")
    client.pull(peer.node, "owner")
    by_status = sorted(p["status"] for p in _props(peer))
    assert by_status == ["approved", "pending"]
    owner.mem.forget(v1.source_id)
    rep = client.pull(peer.node, "owner")
    assert rep.withdrawn == 1 and [r["proposal_id"] for r in rep.revoke_proposed] == [pid1]
    assert sorted(p["status"] for p in _props(peer)) == ["approved", "withdrawn"]
