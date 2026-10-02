"""The foreground sharing server (ADR-V170-05): one TCP port, TLS 1.3 only, two TLS personalities chosen by the SNI the
client announces (peeked from the ClientHello): ``zm-pair`` -> pairing endpoint, anything else -> mutual TLS with pinned peers.

Hard limits: 16 concurrent connections, 5 s to present a ClientHello, 15 s per request, 120 requests/minute/peer, pairing
failures 5/minute then every open invite is burned. Read-only: ``GET`` manifest / tombstones, ``POST`` fetch / pair; every other
method or path is refused. No exception text ever reaches a client.
"""
from __future__ import annotations

import base64
import binascii
import collections
import hashlib
import socket
import ssl
import threading
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qs

from . import (DEFAULT_PORT, PROTOCOL_VERSION, SNI_PAIR, ShareError, events as ev, httpio, protocol, tls)
from .grants import validate_grant_spec
from .identity import validate_peer_certificate
from .util import clean_label, is_lan_address, parse_ip

MAX_CONNECTIONS = 16
HELLO_SECONDS = 5.0
REQUEST_SECONDS = 15.0
PEER_RATE_PER_MINUTE = 120
PAIR_FAIL_LIMIT = 5
MAX_SERVE_SECONDS = 24 * 3600
DEFAULT_SERVE_SECONDS = 30 * 60
_REFUSAL_AUDIT_EVERY = 10.0


def check_bind(addr: str, *, allow_public_bind: bool, i_know_public: bool) -> str:
    """The literal address ``serve`` may bind. A non-LAN address (including 0.0.0.0 and ::) needs the setting AND the flag."""
    if not isinstance(addr, str) or parse_ip(addr) is None:
        raise ShareError("invalid_bind", "--bind must be an IP address")
    if is_lan_address(addr):
        return addr
    if allow_public_bind and i_know_public:
        return addr
    if allow_public_bind or i_know_public:
        raise ShareError("public_bind_refused", "a public bind needs BOTH [sharing] allow_public_bind = true and --i-know-this-is-public")
    raise ShareError("public_bind_refused", "refusing to bind a non-private address: sharing is LAN only "
                     "(a private, link-local or loopback address is required)")


class ShareServer:
    def __init__(self, node, *, bind: str, port: int = DEFAULT_PORT, duration: int = DEFAULT_SERVE_SECONDS,
                 i_know_public: bool = False, announce: bool = False, announce_to: Optional[str] = None) -> None:
        cfg = node.settings()
        node.require_active()
        self._node = node
        self._addr = check_bind(bind, allow_public_bind=cfg.allow_public_bind, i_know_public=i_know_public)
        if not 1 <= duration <= MAX_SERVE_SECONDS:
            raise ShareError("invalid_duration", "--for must be between 1 second and 24 hours")
        if not isinstance(port, int) or not 0 <= port <= 65535:
            raise ShareError("invalid_port", "invalid port")
        self._port = port
        self._duration = duration
        self._announce = announce
        self._announce_to = announce_to
        self._identity = node.identity()
        self._sock: Optional[socket.socket] = None
        self._threads: list = []
        self._stop = threading.Event()
        self._closed = False
        self._stopped = threading.Event()  # set only after serve_stop is audited (T25 / DEF-192)
        self._active = 0
        self._active_lock = threading.Lock()
        self._rates: dict = collections.defaultdict(collections.deque)
        self._pair_failures: collections.deque = collections.deque()
        self._ctx_lock = threading.Lock()
        self._pair_ctx = None
        self._peer_ctx: tuple = (None, None)
        self._refused = 0
        self._refused_flushed = time.monotonic()
        self._refused_lock = threading.Lock()
        self.started_at = 0.0
        self._discovery = None

    # ---------------------------------------------------------------- lifecycle
    @property
    def port(self) -> int:
        return self._port

    @property
    def address(self) -> str:
        return self._addr

    def start(self) -> "ShareServer":
        family = socket.AF_INET6 if ":" in self._addr else socket.AF_INET
        try:
            self._sock = socket.create_server((self._addr, self._port), family=family, backlog=32)
        except OSError:
            raise ShareError("bind_failed", f"cannot listen on {self._addr}:{self._port} (is another serve running?)") from None
        self._port = self._sock.getsockname()[1]
        self._sock.settimeout(0.5)
        self.started_at = time.monotonic()
        self._node.audit_event("serve_start", peer_id=self._identity.peer_id, bind=self._addr, port=self._port,
                               duration=self._duration)
        accept = threading.Thread(target=self._accept_loop, name="zm-share-accept", daemon=True)
        accept.start()
        self._threads.append(accept)
        if self._announce:
            from .discovery import Announcer

            cfg = self._node.settings()
            label = self._node.own_label() if cfg.announce_label else None
            self._discovery = Announcer(self._identity.peer_id, self._port, label=label, dest=self._announce_to)
            self._discovery.start()
        return self

    def serve_forever(self) -> None:
        end = self.started_at + self._duration
        while not self._stop.is_set() and time.monotonic() < end:
            self._stop.wait(0.25)
        self.stop()

    def stop(self) -> None:
        with self._ctx_lock:
            first = not self._closed
            self._closed = True
        if not first:
            # T25 / DEF-192: the accept loop's expiry thread and serve_forever both call stop(); the loser used to
            # return at once, so serve_forever() could return (and a caller read the audit) before serve_stop existed.
            if threading.current_thread() not in self._threads:
                self._stopped.wait(15.0)
            return
        try:
            self._shutdown()
        finally:
            self._stopped.set()

    def _shutdown(self) -> None:
        self._stop.set()
        if self._discovery is not None:
            self._discovery.stop()
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        for thread in self._threads:
            if thread is not threading.current_thread():
                thread.join(timeout=2.0)
        self._flush_refusals(force=True)
        try:
            self._node.audit_event("serve_stop", peer_id=self._identity.peer_id)
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> "ShareServer":
        return self.start()

    def __exit__(self, *_exc) -> None:
        self.stop()

    # ---------------------------------------------------------------- accept
    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            sock = self._sock
            if sock is None:
                return
            if time.monotonic() >= self.started_at + self._duration:
                threading.Thread(target=self.stop, name="zm-share-expire", daemon=True).start()
                return
            try:
                conn, addr = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with self._active_lock:
                if self._active >= MAX_CONNECTIONS:
                    conn.close()
                    continue
                self._active += 1
            thread = threading.Thread(target=self._guard, args=(conn, addr), name="zm-share-conn", daemon=True)
            thread.start()

    def _guard(self, conn, addr) -> None:
        try:
            self._handle(conn, addr)
        except Exception:  # noqa: BLE001 - one bad connection never stops the server
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass
            with self._active_lock:
                self._active -= 1

    # ---------------------------------------------------------------- TLS
    def _contexts(self):
        with self._ctx_lock:
            if self._pair_ctx is None:
                self._pair_ctx = tls.pair_context(self._identity)
            peers = self._node.log.active_peers()
            key = frozenset(p["fp"] for p in peers.values())
            if self._peer_ctx[0] != key:
                ders = [base64.b64decode(p["cert_der_b64"]) for p in peers.values()]
                self._peer_ctx = (key, tls.peer_context(self._identity, ders))
            return self._pair_ctx, self._peer_ctx[1]

    def _note_refusal(self) -> None:
        with self._refused_lock:
            self._refused += 1
        self._flush_refusals()

    def _flush_refusals(self, force: bool = False) -> None:
        with self._refused_lock:
            if not self._refused or (not force and time.monotonic() - self._refused_flushed < _REFUSAL_AUDIT_EVERY):
                return
            count, self._refused = self._refused, 0
            self._refused_flushed = time.monotonic()
        try:
            self._node.audit_event("tls_refused", count=count)
        except Exception:  # noqa: BLE001
            pass

    def _handle(self, conn: socket.socket, addr) -> None:
        sni = tls.peek_sni(conn, time.monotonic() + HELLO_SECONDS)
        pair_ctx, peer_ctx = self._contexts()
        pairing = sni == SNI_PAIR
        try:
            conn.settimeout(HELLO_SECONDS)
            sock = (pair_ctx if pairing else peer_ctx).wrap_socket(conn, server_side=True)
        except (ssl.SSLError, OSError, ValueError):
            self._note_refusal()
            return
        try:
            deadline = time.monotonic() + REQUEST_SECONDS
            peer = None
            if not pairing:
                der = tls.peer_der(sock)
                fp = hashlib.sha256(der).hexdigest() if der else None
                peer = next((p for p in self._node.log.active_peers().values() if fp and p["fp"] == fp), None)
                if peer is None:
                    self._note_refusal()
                    return
            try:
                req = httpio.read_request(sock, deadline=deadline, max_body=8 * 1024 if pairing else 64 * 1024)
            except httpio.HttpError as exc:
                httpio.send_response(sock, exc.status, protocol.dump_json({"error": exc.code}))
                return
            status, body, allow = (self._route_pair(req, addr) if pairing else self._route_peer(req, peer))
            httpio.send_response(sock, status, body, allow=allow)
        finally:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except (OSError, ssl.SSLError):
                pass

    # ---------------------------------------------------------------- routing
    @staticmethod
    def _err(status: int, code: str, allow: Optional[str] = None) -> tuple:
        return status, protocol.dump_json({"error": code}), allow

    def _route_peer(self, req, peer: dict) -> tuple:
        cfg = self._node.settings()
        if not cfg.sharing_active:
            return self._err(503, "sharing_disabled")
        known = {"/v1/manifest": "GET", "/v1/fetch": "POST", "/v1/tombstones": "GET"}
        allowed = known.get(req.path)
        if allowed is None:
            return self._err(404, "not_found")
        if req.method != allowed:
            return self._err(405, "method_not_allowed", allowed)
        live = self._node.log.peer(peer["peer_id"])  # revocation is checked again for every request
        if live is None or live["revoked_at"] is not None:
            return self._err(403, "revoked")
        now = time.monotonic()
        window = self._rates[peer["peer_id"]]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= PEER_RATE_PER_MINUTE:
            return self._err(429, "rate_limited")
        window.append(now)
        service = self._node.owner_service()
        try:
            if req.path == "/v1/manifest":
                doc = service.manifest(peer["peer_id"])
            elif req.path == "/v1/fetch":
                doc = service.fetch(peer["peer_id"], protocol.parse_fetch_request(req.body))
            else:
                query = parse_qs(req.query, keep_blank_values=True, max_num_fields=4)
                since = (query.get("since") or ["1970-01-01T00:00:00Z"])[0]
                after = (query.get("after") or [""])[0] or None
                doc = service.tombstones(peer["peer_id"], since, after)
            return 200, protocol.dump_json(doc), None
        except ShareError as exc:
            return self._err(400, exc.code)
        except Exception:  # noqa: BLE001 - includes an audit that could not be written: nothing is served then
            return self._err(500, "internal_error")

    # -- pairing ---------------------------------------------------------------------------
    def _pair_refused(self, addr, reason: str, status: int = 403, code: str = "pairing_refused") -> tuple:
        now = time.monotonic()
        self._pair_failures.append(now)
        while self._pair_failures and now - self._pair_failures[0] > 60:
            self._pair_failures.popleft()
        try:
            self._node.audit_event("pair_attempt", ok=False, reason=reason, remote=str(addr[0])[:64])
            if len(self._pair_failures) >= PAIR_FAIL_LIMIT:
                burned = self._node.invites().burn_open()
                if burned:
                    self._node.audit_event("pair_lockout", burned=burned)
        except Exception:  # noqa: BLE001
            pass
        return self._err(status, code)

    def _route_pair(self, req, addr) -> tuple:
        if req.path != "/v1/pair":
            return self._err(404, "not_found")
        if req.method != "POST":
            return self._err(405, "method_not_allowed", "POST")
        cfg = self._node.settings()
        if not cfg.sharing_active:
            return self._err(503, "sharing_disabled")
        now = time.monotonic()
        while self._pair_failures and now - self._pair_failures[0] > 60:
            self._pair_failures.popleft()
        if len(self._pair_failures) >= PAIR_FAIL_LIMIT:
            if self._node.invites().burn_open():
                try:
                    self._node.audit_event("pair_lockout", burned=1)
                except Exception:  # noqa: BLE001
                    pass
            self._pair_failures.append(now)
            return self._err(429, "locked")
        try:
            body = protocol.parse_pair_request(req.body)
            der = base64.b64decode(body["cert_der_b64"].encode("ascii"), validate=True)
            validate_peer_certificate(der)
            label = clean_label(body["label"])
        except (ShareError, binascii.Error, ValueError, UnicodeError):
            return self._pair_refused(addr, "malformed")
        status, record = self._node.invites().redeem(body["token"])
        if status != "ok":
            return self._pair_refused(addr, status)
        try:
            peer_id = self._node.register_peer(der, label, record, remote=str(addr[0])[:64])
        except ShareError as exc:
            return self._err(403, exc.code)
        except Exception:  # noqa: BLE001
            return self._err(500, "internal_error")
        doc = {"v": PROTOCOL_VERSION, "status": "paired", "peer_id": self._identity.peer_id,
               "label": record.get("label") or self._node.own_label(), "service_port": self._port}
        return 200, protocol.dump_json(doc), None
