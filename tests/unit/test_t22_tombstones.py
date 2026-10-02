"""T22 finding 3 - /v1/tombstones must not name items the peer could never have received (secret sensitivity, outside the
grant, unsafe or secret-looking refs)."""
from __future__ import annotations

import pytest

pytest.importorskip("cryptography")

from tests.unit.t20_helpers import SECRET_TOKEN, Site, pair  # noqa: E402


@pytest.fixture
def world(tmp_path):
    owner, peer = Site(tmp_path, "owner"), Site(tmp_path, "peer")
    owner.prov.grant_write("claude", space="ks-team", basis="t")
    server = pair(owner, peer)
    yield owner, peer
    server.stop()
    owner.close()
    peer.close()


def _pid(peer):
    return peer.node.identity().peer_id


def _inject(owner, ref, *, space="ks-shared", content=b"harmless text", **kw):
    registry, blobs = owner.mem._corpus()
    return registry.register_source_with_blob(
        content=content, external_ref=ref, kind="txt", knowledge_space_id=space, profile_id="claude",
        custom_meta={"memory_type": "fact"}, blob_store=blobs, **kw)


def _forget(owner, rec):
    assert owner.mem.forget(rec.source_id).status == "forgotten"


def _tomb_refs(owner, peer):
    return [t["ref"] for t in owner.node.owner_service().tombstones(_pid(peer), "1970-01-01T00:00:00Z")["tombstones"]]


def test_a_forgotten_normal_item_in_the_grant_is_still_reported(world):
    owner, peer = world
    owner.node.grant(_pid(peer), {"space": "ks-shared"})
    res = owner.add("ordinary", "fact", name="ok")
    owner.mem.forget(res.source_id)
    assert _tomb_refs(owner, peer) == ["mem://fact/ok"]


def test_forgotten_secret_sensitivity_item_is_not_listed(world):
    owner, peer = world
    owner.node.grant(_pid(peer), {"space": "ks-shared"})
    rec = _inject(owner, "mem://fact/prod-db-password-notes", sensitivity="secret")
    _forget(owner, rec)
    assert "prod-db-password-notes" not in str(owner.node.owner_service().tombstones(_pid(peer), "1970-01-01T00:00:00Z"))
    assert _tomb_refs(owner, peer) == []


def test_forgotten_item_outside_the_grant_is_not_listed(world):
    owner, peer = world
    owner.node.grant(_pid(peer), {"space": "ks-shared"})
    res = owner.add("team only", "fact", name="teamonly")
    other = _inject(owner, "mem://fact/other-space", space="ks-team")
    _forget(owner, other)
    owner.mem.forget(res.source_id)
    assert _tomb_refs(owner, peer) == ["mem://fact/teamonly"]


def test_forgotten_item_with_a_secret_looking_ref_is_not_listed(world):
    owner, peer = world
    owner.node.grant(_pid(peer), {"space": "ks-shared"})
    rec = _inject(owner, "mem://fact/" + SECRET_TOKEN)
    _forget(owner, rec)
    assert _tomb_refs(owner, peer) == []
    assert SECRET_TOKEN not in str(owner.node.owner_service().tombstones(_pid(peer), "1970-01-01T00:00:00Z"))
