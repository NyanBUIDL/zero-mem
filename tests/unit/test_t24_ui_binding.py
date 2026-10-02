"""T24 finding 3 - the pull / grant confirmation is bound (HMAC, per-session secret) to the COMPLETE reviewed plan."""
from __future__ import annotations

import copy
import re

import pytest

pytest.importorskip("cryptography")

from tests.unit.test_t21_ui_sharing import World, peer_id, world  # noqa: E402,F401
from zero_mem.share.owner import OwnerService  # noqa: E402
from zero_mem.ui import sharing as ui_sharing  # noqa: E402

CHANGED = "owner changed the plan since you reviewed it"


def _id(html):
    return re.search(r'name="id" value="([^"]+)"', html).group(1)


def _setup(w):
    w.alice.add("first granted fact", "fact", name="one")
    w.pair()
    pid, owner_id = peer_id(w), w.alice.node.identity().peer_id
    w.alice.node.grant(pid, {"space": "ks-shared"})
    return pid, owner_id


def _tamper(monkeypatch, mutate):
    real = OwnerService.manifest

    def manifest(self, peer_id):
        doc = real(self, peer_id)
        mutate(doc["sources"][0])
        return doc

    real_fetch = OwnerService.fetch

    def fetch(self, peer_id, ids):  # a malicious owner is consistent: fetch repeats the altered entry
        doc = real_fetch(self, peer_id, ids)
        for src in doc["sources"]:
            mutate(src)
        return doc

    monkeypatch.setattr(OwnerService, "manifest", manifest)
    monkeypatch.setattr(OwnerService, "fetch", fetch)


def _imports(w, owner_id):
    return w.bob.node.log.imported_digest(owner_id, "x") is None and not w.bob.node.log.imported


@pytest.mark.parametrize("field,value", [
    ("ref", "mem://fact/substituted"),
    ("kind", "md"),
    ("size", None),
    ("type", None),
])
def test_changing_one_field_between_preview_and_confirm_is_refused(world, monkeypatch, field, value):
    w = world
    _pid, owner_id = _setup(w)
    _s, _h, plan = w.cb.post("/sharing/pull-plan", {"owner": owner_id})
    pull_id = _id(plan)

    def mutate(entry):
        if field == "size":
            entry["size"] = entry["size"] + 1
        elif field == "type":
            entry["memory_type"], entry["ref"] = "rule", "mem://rule/one"
        else:
            entry[field] = value

    _tamper(monkeypatch, mutate)
    _s, _h, body = w.cb.post("/sharing/pull-confirm", {"id": pull_id, "confirm": "1"})
    assert CHANGED in body, body[:400]
    assert not w.bob.node.log.imported
    assert "Pull finished" not in body


def test_unchanged_plan_is_accepted(world):
    w = world
    _pid, owner_id = _setup(w)
    _s, _h, plan = w.cb.post("/sharing/pull-plan", {"owner": owner_id})
    _s, _h, body = w.cb.post("/sharing/pull-confirm", {"id": _id(plan), "confirm": "1"})
    assert "Pull finished" in body and w.bob.node.log.imported


def test_old_confirmation_cannot_be_replayed_after_the_plan_changed(world):
    w = world
    _pid, owner_id = _setup(w)
    _s, _h, plan = w.cb.post("/sharing/pull-plan", {"owner": owner_id})
    old = _id(plan)
    w.alice.add("a second fact appears", "fact", name="two")
    _s, _h, body = w.cb.post("/sharing/pull-confirm", {"id": old, "confirm": "1"})
    assert CHANGED in body
    _s, _h, body = w.cb.post("/sharing/pull-confirm", {"id": old, "confirm": "1"})  # replay: consumed
    assert "Pull finished" not in body and not w.bob.node.log.imported


ROW = {"source_id": "s1", "ref": "mem://fact/a", "memory_type": "fact", "size": 3, "digest": "d" * 64, "kind": "txt",
       "action": "new", "reason": None}


def _plan(**over):
    row = {**ROW, **over}
    return {"rows": [row], "summary": {row["action"]: 1}, "invalid_entries": 0, "bytes": 3, "sources": 1}


@pytest.mark.parametrize("key,value", [("ref", "mem://fact/b"), ("memory_type", "rule"), ("kind", "md"), ("size", 4),
                                       ("digest", "e" * 64), ("action", "changed"), ("source_id", "s2")])
def test_signature_covers_every_row_field(key, value):
    secret = b"k" * 32
    base = ui_sharing._plan_signature(secret, "owner1", _plan())
    assert base == ui_sharing._plan_signature(secret, "owner1", copy.deepcopy(_plan()))
    assert base != ui_sharing._plan_signature(secret, "owner1", _plan(**{key: value}))
    assert base != ui_sharing._plan_signature(b"j" * 32, "owner1", _plan())  # secret-bound
    assert base != ui_sharing._plan_signature(secret, "owner2", _plan())  # owner-bound


def test_grant_confirm_refused_when_what_it_would_share_changed(world):
    w = world
    w.alice.add("first granted fact", "fact", name="one")
    w.pair()
    pid = peer_id(w)
    _s, _h, preview = w.ca.post("/sharing/grant-preview", {"peer": pid, "space": "ks-shared", "grant_expires": "30d"})
    token = _id(preview)
    w.alice.add("added after the preview", "fact", name="late")
    _s, _h, body = w.ca.post("/sharing/grant-confirm", {"id": token, "confirm": "1"})
    assert "changed since you previewed" in body
    assert w.alice.node.grants(None) == []
