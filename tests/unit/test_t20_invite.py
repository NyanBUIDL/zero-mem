"""T20 - invite codes and the invite store (no network; the store/parser need no cryptography)."""
from __future__ import annotations

import json

import pytest

from zero_mem.share import INVITE_PREFIX, ShareError
from zero_mem.share.invite import Invite, InviteStore, parse_invite
from zero_mem.share.util import b64u_encode

FP = "ab" * 32


def make(**kw):
    base = dict(host="192.168.1.5", port=47890, server_fp=FP, token=b64u_encode(b"x" * 32), expires=2_000_000_000, label="home")
    base.update(kw)
    return Invite(**base)


def test_roundtrip_and_prefix():
    inv = make()
    code = inv.encode()
    assert code.startswith(INVITE_PREFIX)
    assert parse_invite(code, now=1_000_000_000) == inv


@pytest.mark.parametrize("mutate", [
    lambda d: d.pop("token"), lambda d: d.update(extra=1), lambda d: d.update(v=2), lambda d: d.update(port=0),
    lambda d: d.update(port=True), lambda d: d.update(server_fp="zz"), lambda d: d.update(host="a b"),
    lambda d: d.update(label="bad\nlabel"), lambda d: d.update(token="!!"), lambda d: d.update(token="AAAA"),
    lambda d: d.update(expires="soon"),
])
def test_malformed_invites_rejected(mutate):
    doc = {"v": 1, "host": "10.0.0.2", "port": 1, "server_fp": FP, "token": b64u_encode(b"y" * 32), "expires": 2_000_000_000, "label": "x"}
    mutate(doc)
    code = INVITE_PREFIX + b64u_encode(json.dumps(doc).encode())
    with pytest.raises(ShareError) as exc:
        parse_invite(code, now=1)
    assert exc.value.code == "invalid_invite"


@pytest.mark.parametrize("code", ["", "zm2:abc", "zm1:", "zm1:" + "A" * 3000, None, 5, "zm1:not base64 !!"])
def test_garbage_codes(code):
    with pytest.raises(ShareError):
        parse_invite(code)


def test_expired_invite_refused():
    with pytest.raises(ShareError) as exc:
        parse_invite(make(expires=100).encode(), now=200)
    assert exc.value.code == "invite_expired"


def test_error_never_echoes_the_code():
    code = INVITE_PREFIX + b64u_encode(b"{not json")
    with pytest.raises(ShareError) as exc:
        parse_invite(code)
    assert code not in str(exc.value)


@pytest.fixture
def store(tmp_path):
    clock = {"t": 1000.0}
    s = InviteStore(tmp_path, clock=lambda: clock["t"])
    s.clock = clock
    return s


def test_token_is_256_bit_and_only_hashed_at_rest(store, tmp_path):
    inv, _ = store.create(host="h", port=1, server_fp=FP, label="l", expires_in=600, grants=[])
    from zero_mem.share.util import b64u_decode
    assert len(b64u_decode(inv.token)) == 32
    assert inv.token not in (tmp_path / "invites.json").read_text(encoding="utf-8")
    assert "hash" in (tmp_path / "invites.json").read_text(encoding="utf-8")


def test_single_use(store):
    inv, iid = store.create(host="h", port=1, server_fp=FP, label="l", expires_in=600, grants=[{"space": "ks-shared"}])
    status, rec = store.redeem(inv.token)
    assert status == "ok" and rec["invite_id"] == iid and rec["grants"] == [{"space": "ks-shared"}]
    assert store.redeem(inv.token) == ("used", None)


def test_expiry_wrong_and_malformed(store):
    inv, _ = store.create(host="h", port=1, server_fp=FP, label="l", expires_in=60, grants=[])
    assert store.redeem(b64u_encode(b"z" * 32))[0] == "unknown"
    assert store.redeem("short")[0] == "malformed"
    store.clock["t"] += 61
    assert store.redeem(inv.token)[0] == "expired"


def test_burn_open_kills_open_invites_only(store):
    a, _ = store.create(host="h", port=1, server_fp=FP, label="l", expires_in=600, grants=[])
    used, _ = store.create(host="h", port=1, server_fp=FP, label="l", expires_in=600, grants=[])
    assert store.redeem(used.token)[0] == "ok"
    assert store.burn_open() == 1
    assert store.redeem(a.token)[0] == "burned"
    b, _ = store.create(host="h", port=1, server_fp=FP, label="l", expires_in=600, grants=[])
    assert store.redeem(b.token)[0] == "ok"


def test_invite_lifetime_and_count_limits(store):
    with pytest.raises(ShareError):
        store.create(host="h", port=1, server_fp=FP, label="l", expires_in=86401, grants=[])
    for _ in range(20):
        store.create(host="h", port=1, server_fp=FP, label="l", expires_in=600, grants=[])
    with pytest.raises(ShareError) as exc:
        store.create(host="h", port=1, server_fp=FP, label="l", expires_in=600, grants=[])
    assert exc.value.code == "too_many_invites"


def test_concurrent_redeem_exactly_one_wins(store):
    import threading
    inv, _ = store.create(host="h", port=1, server_fp=FP, label="l", expires_in=600, grants=[])
    results = []
    threads = [threading.Thread(target=lambda: results.append(store.redeem(inv.token)[0])) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results).count("ok") == 1
