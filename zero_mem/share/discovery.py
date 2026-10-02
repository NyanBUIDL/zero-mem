"""LAN discovery (ADR-V170-05, section 8): a UDP announcement while ``serve --announce`` runs, and a listener for it.

The datagram is exactly ``{"zm":1,"svc":"zero-mem-share","peer_id":..,"port":..}`` (+ ``"label"`` only when the owner enabled
``[sharing] announce_label``). Never memory names or contents. Discovery grants nothing: finding a host only tells you where to
connect; pairing still needs an invite with a one-time token and the pinned certificate."""
from __future__ import annotations

import json
import socket
import threading
import time
from typing import Optional

from . import DISCOVERY_PORT, SERVICE_NAME
from .util import LABEL_RE, PEER_ID_RE, is_lan_address

ANNOUNCE_INTERVAL = 3.0
MAX_DATAGRAM = 512


def announcement(peer_id: str, port: int, label: Optional[str] = None) -> bytes:
    doc = {"zm": 1, "svc": SERVICE_NAME, "peer_id": peer_id, "port": port}
    if label:
        doc["label"] = label
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("ascii")


def parse_announcement(data: bytes, sender: str) -> Optional[dict]:
    """A validated announcement as ``{peer_id, host, port[, label]}``, or ``None`` (anything else is ignored)."""
    if len(data) > MAX_DATAGRAM or not is_lan_address(sender):
        return None
    try:
        doc = json.loads(data.decode("ascii"))
    except (ValueError, UnicodeError):
        return None
    if not isinstance(doc, dict) or doc.get("zm") != 1 or doc.get("svc") != SERVICE_NAME or set(doc) - {"zm", "svc", "peer_id", "port", "label"}:
        return None
    pid, port = doc.get("peer_id"), doc.get("port")
    if not isinstance(pid, str) or not PEER_ID_RE.fullmatch(pid) or not isinstance(port, int) or isinstance(port, bool) \
            or not 1 <= port <= 65535:
        return None
    out = {"peer_id": pid, "host": sender, "port": port}
    label = doc.get("label")
    if label is not None:
        if not isinstance(label, str) or not LABEL_RE.fullmatch(label):
            return None
        out["label"] = label
    return out


class Announcer:
    def __init__(self, peer_id: str, port: int, *, label: Optional[str] = None, dest: Optional[str] = None,
                 dest_port: int = DISCOVERY_PORT, interval: float = ANNOUNCE_INTERVAL) -> None:
        self._payload = announcement(peer_id, port, label)
        self._dest = (dest or "255.255.255.255", dest_port)
        self._interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> "Announcer":
        self._thread = threading.Thread(target=self._run, name="zm-share-announce", daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except OSError:
            return
        with sock:
            while not self._stop.is_set():
                try:
                    sock.sendto(self._payload, self._dest)
                except OSError:
                    pass  # no route / no broadcast on this network: keep trying quietly
                self._stop.wait(self._interval)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


def discover(timeout: float = 5.0, *, port: int = DISCOVERY_PORT, bind: str = "") -> list:
    """Listen for announcements for ``timeout`` seconds; returns de-duplicated ``[{peer_id, host, port[, label]}]``."""
    found: dict = {}
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((bind, port))
    except OSError:
        return []
    with sock:
        end = time.monotonic() + timeout
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            sock.settimeout(min(remaining, 0.5))
            try:
                data, addr = sock.recvfrom(MAX_DATAGRAM + 1)
            except socket.timeout:
                continue
            except OSError:
                break
            item = parse_announcement(data, addr[0])
            if item is not None:
                found[(item["peer_id"], item["host"], item["port"])] = item
    return sorted(found.values(), key=lambda i: (i["peer_id"], i["host"]))
