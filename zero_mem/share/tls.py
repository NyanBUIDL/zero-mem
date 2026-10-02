"""TLS 1.3 plumbing with pinned certificates (ADR-V170-05, section 4). Standard library ``ssl`` only.

* server, service port: ``CERT_REQUIRED`` with ONLY the paired, non-revoked peers' certificates as trust anchors;
* server, pairing endpoint: server authentication only (the joiner's certificate travels inside the request);
* client: no CA and no hostname checks (``CERT_NONE``) followed by an exact, constant-time SHA-256 pin comparison BEFORE any
  application byte is written.
"""
from __future__ import annotations

import hashlib
import hmac
import socket
import ssl
import time
from typing import Optional

from . import SNI_PEER, ShareError

_MIN = ssl.TLSVersion.TLSv1_3
MAX_CLIENT_HELLO = 16384 + 5


def _base_server(identity) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = _MIN
    ctx.maximum_version = ssl.TLSVersion.MAXIMUM_SUPPORTED
    ctx.load_cert_chain(str(identity.cert_path), str(identity.key_path))
    return ctx


def pair_context(identity) -> ssl.SSLContext:
    ctx = _base_server(identity)
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def peer_context(identity, peer_certs_der) -> ssl.SSLContext:
    """Mutual TLS: the presented client certificate must be one of ``peer_certs_der`` (paired, non-revoked)."""
    ctx = _base_server(identity)
    ctx.verify_mode = ssl.CERT_REQUIRED
    pem = "".join(ssl.DER_cert_to_PEM_cert(der) for der in peer_certs_der)
    if pem:
        ctx.load_verify_locations(cadata=pem)
    return ctx


def client_context(identity=None, *, maximum: Optional[ssl.TLSVersion] = None) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = _MIN
    if maximum is not None:
        ctx.maximum_version = maximum
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # no CA: authenticity comes from the pin below
    if identity is not None:
        ctx.load_cert_chain(str(identity.cert_path), str(identity.key_path))
    return ctx


def peer_der(tls: ssl.SSLSocket) -> Optional[bytes]:
    try:
        return tls.getpeercert(binary_form=True)
    except (ValueError, ssl.SSLError, OSError):
        return None


def peer_fingerprint(tls: ssl.SSLSocket) -> Optional[str]:
    der = peer_der(tls)
    return hashlib.sha256(der).hexdigest() if der else None


def connect_pinned(addr: str, port: int, expected_fp: str, *, identity=None, sni: str = SNI_PEER, timeout: float = 10.0,
                   context: Optional[ssl.SSLContext] = None) -> ssl.SSLSocket:
    """Connect, handshake (TLS 1.3 only) and verify the server certificate fingerprint; ``ShareError`` on any failure.

    Nothing is sent after the handshake until the pin matches; on mismatch the socket is closed."""
    ctx = context or client_context(identity)
    raw = None
    try:
        raw = socket.create_connection((addr, port), timeout=timeout)
        raw.settimeout(timeout)
        tls = ctx.wrap_socket(raw, server_hostname=sni)
    except (OSError, ssl.SSLError):
        if raw is not None:
            try:
                raw.close()
            except OSError:
                pass
        raise ShareError("connect_failed", "cannot establish a TLS 1.3 connection to the peer") from None
    fp = peer_fingerprint(tls)
    if fp is None or not hmac.compare_digest(fp.encode("ascii"), expected_fp.encode("ascii")):
        try:
            tls.close()
        except OSError:
            pass
        raise ShareError("pin_mismatch", "the peer's certificate does not match the pinned fingerprint; connection aborted")
    return tls


# ---------------------------------------------------------------------------------------------
# ClientHello SNI (server side)
# ---------------------------------------------------------------------------------------------
def parse_sni(hello: bytes) -> Optional[str]:
    """The server_name of a TLS ClientHello record, or ``None`` (not TLS / no SNI / malformed). Bounds-checked."""
    try:
        if len(hello) < 5 or hello[0] != 0x16:
            return None
        pos = 5
        if hello[pos] != 0x01:
            return None
        pos += 4  # handshake type + 3-byte length
        pos += 2 + 32  # client_version + random
        pos += 1 + hello[pos]  # session id
        pos += 2 + int.from_bytes(hello[pos:pos + 2], "big")  # cipher suites
        pos += 1 + hello[pos]  # compression methods
        end = pos + 2 + int.from_bytes(hello[pos:pos + 2], "big")
        pos += 2
        end = min(end, len(hello))
        while pos + 4 <= end:
            ext_type = int.from_bytes(hello[pos:pos + 2], "big")
            ext_len = int.from_bytes(hello[pos + 2:pos + 4], "big")
            pos += 4
            if ext_type == 0 and ext_len >= 5:
                list_end = pos + 2 + int.from_bytes(hello[pos:pos + 2], "big")
                cur = pos + 2
                while cur + 3 <= min(list_end, pos + ext_len):
                    name_type = hello[cur]
                    name_len = int.from_bytes(hello[cur + 1:cur + 3], "big")
                    if name_type == 0:
                        return hello[cur + 3:cur + 3 + name_len].decode("ascii")
                    cur += 3 + name_len
                return None
            pos += ext_len
    except (IndexError, UnicodeDecodeError):
        return None
    return None


def peek_sni(sock: socket.socket, deadline: float) -> Optional[str]:
    """Peek (``MSG_PEEK``, nothing consumed) at the first TLS record until it is complete or ``deadline`` passes."""
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        sock.settimeout(min(remaining, 0.5))
        try:
            data = sock.recv(MAX_CLIENT_HELLO, socket.MSG_PEEK)
        except socket.timeout:
            continue
        except OSError:
            return None
        if not data:
            return None
        if data[0] != 0x16:
            return None
        if len(data) >= 5:
            need = 5 + int.from_bytes(data[3:5], "big")
            if need > MAX_CLIENT_HELLO:
                return None
            if len(data) >= need:
                return parse_sni(data[:need])
        time.sleep(0.005)
