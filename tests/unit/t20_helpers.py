"""Helpers for the T20 peer-sharing tests (not collected). Two isolated data roots, real TLS on loopback."""
from __future__ import annotations

import socket
import ssl
from pathlib import Path

from tests.unit.t5_memory_helpers import SECRET_TOKEN  # noqa: F401  (re-exported)
from zero_mem.memory import Memory
from zero_mem.provisioning import Provisioner
from zero_mem.share.node import ShareNode
from zero_mem.share.server import ShareServer


class Site:
    """One machine: data root + settings file + a ShareNode + an agent Memory that can write ks-shared."""

    def __init__(self, root: Path, name: str, *, settings: str = "[sharing]\nenabled = true\n") -> None:
        self.root = root / name
        self.settings = root / f"{name}.settings.toml"
        self.settings.write_text(settings, encoding="utf-8")
        self.node = ShareNode.open(self.root, settings_path=self.settings, label=name)
        self.prov = Provisioner(self.node.layout, operator="tester")
        self.prov.add_agent("claude")
        self.prov.grant_write("claude", space="ks-shared", basis="test")
        self.mem = Memory.open("claude", data_root=self.root, settings_path=self.settings)

    def add(self, text, mtype="fact", name=None, scope="shared", **kw):
        res = self.mem._owner_add(text, mtype, name=name, scope=scope, **kw)
        assert res.status in ("created", "updated", "unchanged"), res
        return res

    def set_settings(self, text: str) -> None:
        self.settings.write_text(text, encoding="utf-8")

    def close(self) -> None:
        self.mem.close()
        self.node.close()


def pair(owner: Site, peer: Site, grants=None, *, port=0, duration=120):
    """Start owner's server, pair peer via a real invite; returns the running ShareServer."""
    from zero_mem.share import client

    server = ShareServer(owner.node, bind="127.0.0.1", port=port, duration=duration).start()
    invite = owner.node.create_invite(host="127.0.0.1", port=server.port, grants=grants if grants is not None else [])
    client.join(peer.node, invite.encode(), peer.node.own_label())
    return server


def raw_tls(port: int, *, cert=None, sni="zm-peer", maximum=None, send: bytes = b""):
    """Open a client TLS 1.3 connection WITHOUT pin checks (for attack tests); returns the SSLSocket."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    if maximum is not None:
        ctx.maximum_version = maximum
    if cert is not None:
        ctx.load_cert_chain(str(cert.cert_path), str(cert.key_path))
    s = ctx.wrap_socket(socket.create_connection(("127.0.0.1", port), timeout=5), server_hostname=sni)
    if send:
        s.sendall(send)
    return s


def http(sock, method="GET", path="/v1/manifest", body=b"", headers=""):
    req = f"{method} {path} HTTP/1.1\r\nHost: x\r\n{headers}"
    if body or method == "POST":
        req += f"Content-Length: {len(body)}\r\n"
    sock.sendall((req + "\r\n").encode() + body)
    data = b""
    while True:
        try:
            chunk = sock.recv(65536)
        except (ssl.SSLError, OSError):
            break
        if not chunk:
            break
        data += chunk
    head, _, rest = data.partition(b"\r\n\r\n")
    status = int(head.split(b" ")[1]) if head else 0
    return status, rest


def foreign_identity(tmp_path: Path):
    """A second, unpaired identity (different data root)."""
    from zero_mem.memory_layout import Layout
    from zero_mem.share.identity import ensure_identity

    layout = Layout.resolve(tmp_path / "stranger")
    layout.ensure()
    return ensure_identity(layout, "stranger")
