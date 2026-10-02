"""T20 - what an owner serves: default deny, grant filters, access-pipeline decisions, withheld sources, outgoing re-scan."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("cryptography")

from tests.unit.t20_helpers import SECRET_TOKEN, Site, pair  # noqa: E402
from zero_mem.share import ShareError  # noqa: E402


@pytest.fixture
def world(tmp_path):
    owner, peer = Site(tmp_path, "owner"), Site(tmp_path, "peer")
    owner.prov.grant_write("claude", space="ks-team", basis="t")
    owner.prov.grant_write("claude", project="proj-a", basis="t")
    owner.prov.grant_write("claude", project="proj-b", basis="t")
    owner.add("shared fact", "fact", name="f1")
    owner.add("shared skill text", "skill", name="s1")
    owner.add("team fact", "fact", name="tf", scope="shared")  # ks-shared again, different name
    owner.mem.add("team notes", "fact", name="team", scope="shared")
    owner.mem._owner_add("devlog entry a", "devlog", name="2026-10-01/a", scope="project", project_id="proj-a")
    owner.mem._owner_add("devlog entry b", "devlog", name="2026-10-01/b", scope="project", project_id="proj-b")
    owner.mem._owner_add("my private note", "fact", name="priv", scope="private")
    other = owner.node.memory  # unrelated profile writes private data too
    owner.prov.add_agent("other")
    from zero_mem.memory import Memory
    om = Memory.open("other", data_root=owner.root, settings_path=owner.settings)
    om.add("other profile private secret plan", "fact", name="otherpriv", scope="private")
    om.close()
    server = pair(owner, peer)
    yield owner, peer, server
    server.stop()
    owner.close()
    peer.close()


def peer_id(peer):
    return peer.node.identity().peer_id


def refs(owner, peer):
    return sorted(e["ref"] for e in owner.node.owner_service().manifest(peer_id(peer))["sources"])


def test_default_deny_serves_nothing(world):
    owner, peer, _ = world
    assert refs(owner, peer) == []


def test_space_grant_serves_only_that_space_never_private(world):
    owner, peer, _ = world
    owner.node.grant(peer_id(peer), {"space": "ks-shared"})
    got = refs(owner, peer)
    assert "mem://fact/f1" in got and "mem://skill/s1" in got
    assert not any("priv" in r or "otherpriv" in r or "devlog" in r for r in got)


def test_type_filter(world):
    owner, peer, _ = world
    owner.node.grant(peer_id(peer), {"space": "ks-shared", "types": ["skill"]})
    assert refs(owner, peer) == ["mem://skill/s1"]


def test_ref_prefix_filter(world):
    owner, peer, _ = world
    owner.node.grant(peer_id(peer), {"space": "ks-shared", "ref_prefixes": ["mem://fact/f"]})
    assert refs(owner, peer) == ["mem://fact/f1"]


def test_project_filter(world):
    owner, peer, _ = world
    owner.node.grant(peer_id(peer), {"projects": ["proj-a"]})
    assert refs(owner, peer) == ["mem://devlog/proj-a/2026-10-01/a"]


def test_grant_expiry(world):
    owner, peer, _ = world
    owner.node.grant(peer_id(peer), {"space": "ks-shared", "expires_in": 60})
    assert refs(owner, peer)
    future = datetime.now(timezone.utc) + timedelta(seconds=120)
    owner.node._clock = lambda: future
    owner.node._owner_service = None
    assert refs(owner, peer) == []
    assert owner.node.grants(peer_id(peer))[0:0] == []  # expired grants are not active


def test_revoke_one_grant_and_all(world):
    owner, peer, _ = world
    g1 = owner.node.grant(peer_id(peer), {"space": "ks-shared", "types": ["fact"]})
    g2 = owner.node.grant(peer_id(peer), {"space": "ks-shared", "types": ["skill"]})
    owner.node.revoke_grants(peer_id(peer), g1["grant_id"])
    assert refs(owner, peer) == ["mem://skill/s1"]
    with pytest.raises(ShareError):
        owner.node.revoke_grants(peer_id(peer), "sg-nope")
    owner.node.revoke_grants(peer_id(peer), None)
    assert refs(owner, peer) == []
    assert g2["grant_id"] not in [g["grant_id"] for g in owner.node.grants(peer_id(peer))]


@pytest.mark.parametrize("spec", [
    {}, {"types": ["fact"]}, {"space": "ks-peer-abc"}, {"space": "bad space"}, {"space": "ks-shared", "types": ["nope"]},
    {"space": "ks-shared", "ref_prefixes": ["../x"]}, {"space": "ks-shared", "expires_in": 5}, {"space": "ks-shared", "extra": 1},
])
def test_invalid_grants_refused(world, spec):
    owner, peer, _ = world
    with pytest.raises(ShareError):
        owner.node.grant(peer_id(peer), spec)


def test_forgotten_items_never_served(world):
    owner, peer, _ = world
    owner.node.grant(peer_id(peer), {"space": "ks-shared"})
    sid = [e["source_id"] for e in owner.node.owner_service().manifest(peer_id(peer))["sources"] if e["ref"] == "mem://fact/f1"][0]
    assert owner.mem.forget(sid).status == "forgotten"
    assert "mem://fact/f1" not in refs(owner, peer)


def test_pending_proposal_never_served(world):
    owner, peer, _ = world
    owner.node.grant(peer_id(peer), {"space": "ks-shared"})
    assert owner.mem.propose("always do the secret handshake", "rule", name="hs").status == "proposed"
    assert not any("hs" in r for r in refs(owner, peer))


def _inject(owner, content: bytes, ref: str, **kw):
    registry, blobs = owner.mem._corpus()
    return registry.register_source_with_blob(
        content=content, external_ref=ref, kind="txt", knowledge_space_id="ks-shared", profile_id="claude",
        custom_meta={"memory_type": "fact"}, blob_store=blobs, **kw)


def test_secret_sensitivity_never_served(world):
    owner, peer, _ = world
    owner.node.grant(peer_id(peer), {"space": "ks-shared"})
    _inject(owner, b"harmless text", "mem://fact/sens", sensitivity="secret")
    assert "mem://fact/sens" not in refs(owner, peer)


def test_outgoing_rescan_blocks_a_planted_secret_and_audits(world):
    owner, peer, _ = world
    owner.node.grant(peer_id(peer), {"space": "ks-shared"})
    _inject(owner, ("deploy key " + SECRET_TOKEN).encode(), "mem://fact/planted")
    manifest = owner.node.owner_service().manifest(peer_id(peer))
    assert "mem://fact/planted" not in [e["ref"] for e in manifest["sources"]]
    assert manifest["omitted"].get("scan_failed") == 1
    ids = [e["source_id"] for e in owner.node.owner_service().manifest(peer_id(peer))["sources"]]
    fetched = owner.node.owner_service().fetch(peer_id(peer), ["x" * 8] + ids)
    assert SECRET_TOKEN not in json.dumps(fetched)
    assert any(e["op"] == "skip_source" for e in owner.node.audit(200))


def test_oversize_source_is_omitted(world):
    owner, peer, _ = world
    owner.set_settings("[sharing]\nenabled = true\nmax_source_bytes = 10\n")
    owner.node.grant(peer_id(peer), {"space": "ks-shared"})
    m = owner.node.owner_service().manifest(peer_id(peer))
    assert all(e["size"] <= 10 for e in m["sources"]) and m["omitted"]["too_large"] >= 1


def test_fetch_only_serves_authorized_ids(world):
    owner, peer, _ = world
    owner.node.grant(peer_id(peer), {"space": "ks-shared", "types": ["skill"]})
    allowed = owner.node.owner_service().manifest(peer_id(peer))["sources"][0]["source_id"]
    registry, _b = owner.mem._corpus()
    registry.refresh()
    fact_id = next(r.source_id for r in registry.all_records() if r.external_ref == "mem://fact/f1")
    out = owner.node.owner_service().fetch(peer_id(peer), [allowed, fact_id])
    assert [s["source_id"] for s in out["sources"]] == [allowed] and out["missing"] == [fact_id]


def test_revoked_peer_gets_nothing_even_with_grants(world):
    owner, peer, _ = world
    owner.node.grant(peer_id(peer), {"space": "ks-shared"})
    owner.node.revoke_peer(peer_id(peer))
    assert refs(owner, peer) == []
    with pytest.raises(ShareError):
        owner.node.grant(peer_id(peer), {"space": "ks-shared"})


def test_peer_imported_copies_are_never_reshared(world):
    owner, peer, _ = world
    owner.node.grant(peer_id(peer), {"space": "ks-shared"})
    owner.node.memory._import_peer_source(content=b"copy", kind="txt", memory_type="fact", external_ref="peer://" + "a" * 20 + "/mem/fact/x",
                                          space="ks-peer-" + "a" * 20, provenance={"peer": "a" * 20})
    assert not any(r.startswith("peer://") for r in refs(owner, peer))


def test_manifest_and_fetch_are_audited_without_content(world):
    owner, peer, _ = world
    owner.node.grant(peer_id(peer), {"space": "ks-shared"})
    owner.node.owner_service().manifest(peer_id(peer))
    audit = json.dumps(owner.node.audit(200))
    assert '"manifest"' in audit and "shared fact" not in audit
