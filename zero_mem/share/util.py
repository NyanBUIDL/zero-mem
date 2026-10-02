"""Small, dependency-free helpers: durations, LAN-address policy, labels, base64url, constant-time compare."""
from __future__ import annotations

import base64
import binascii
import hmac
import ipaddress
import re
import socket
from typing import Optional

from . import ShareError

_DURATION_RE = re.compile(r"^(\d{1,6})([smhd])$")
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@-]{0,39}$")
PEER_ID_RE = re.compile(r"^[0-9a-f]{20}$")
FP_RE = re.compile(r"^[0-9a-f]{64}$")
_PRIVATE_V4 = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "127.0.0.0/8"))
_PRIVATE_V6 = tuple(ipaddress.ip_network(n) for n in ("fc00::/7", "fe80::/10", "::1/128"))


def parse_duration(text: str, *, maximum: int, minimum: int = 1) -> int:
    """``10m`` / ``2h`` / ``30d`` / ``45s`` -> seconds, bounded."""
    match = _DURATION_RE.match(str(text).strip().lower())
    if not match:
        raise ShareError("invalid_duration", "use a number and a unit: 45s, 10m, 2h or 30d")
    seconds = int(match.group(1)) * _UNITS[match.group(2)]
    if seconds < minimum or seconds > maximum:
        raise ShareError("invalid_duration", f"the duration must be between {minimum} seconds and {maximum} seconds")
    return seconds


def clean_label(value: object, *, default: Optional[str] = None) -> str:
    """A short, printable ASCII label (letters, digits, space . _ @ -); anything else is refused (labels end up in
    briefs, evidence and audit lines and must never carry control or bidirectional characters)."""
    if value is None and default is not None:
        return default
    if not isinstance(value, str) or not LABEL_RE.fullmatch(value):
        raise ShareError("invalid_label", "a label is 1-40 characters: letters, digits, space and . _ @ -")
    return value


def b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64u_decode(text: str, *, max_len: int = 1 << 20) -> bytes:
    if not isinstance(text, str) or len(text) > max_len or not re.fullmatch(r"[A-Za-z0-9_-]*", text):
        raise ShareError("invalid_encoding", "not base64url")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError):
        raise ShareError("invalid_encoding", "not base64url") from None


def b64_decode_strict(text: object, *, max_bytes: int) -> bytes:
    """Standard base64 (validated alphabet and padding, bounded decoded size)."""
    if not isinstance(text, str) or len(text) > (max_bytes * 4) // 3 + 8:
        raise ShareError("invalid_encoding", "content is not valid base64 or too large")
    try:
        data = base64.b64decode(text.encode("ascii"), validate=True)
    except (binascii.Error, ValueError, UnicodeEncodeError):
        raise ShareError("invalid_encoding", "content is not valid base64") from None
    if len(data) > max_bytes:
        raise ShareError("invalid_encoding", "content is too large")
    return data


def consteq(a: str, b: str) -> bool:
    return hmac.compare_digest(str(a).encode("utf-8"), str(b).encode("utf-8"))


def _strip_scope(host: str) -> str:
    return host.split("%", 1)[0]


def parse_ip(host: str):
    try:
        return ipaddress.ip_address(_strip_scope(host.strip("[]")))
    except ValueError:
        return None


def is_lan_address(host: str) -> bool:
    """RFC1918, 169.254/16, 127/8, ::1, fc00::/7, fe80::/10 (an IPv4-mapped IPv6 address is judged as IPv4)."""
    ip = parse_ip(host)
    if ip is None:
        return False
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    nets = _PRIVATE_V4 if ip.version == 4 else _PRIVATE_V6
    return any(ip in net for net in nets)


def resolve_lan_host(host: str, port: int) -> str:
    """The literal LAN address to connect to: ``host`` may be an address or a name; every resolved address must be LAN."""
    if not isinstance(host, str) or not host or len(host) > 253 or any(ord(c) < 33 or ord(c) == 127 for c in host):
        raise ShareError("invalid_host", "invalid host")
    if parse_ip(host) is not None:
        if not is_lan_address(host):
            raise ShareError("not_lan_address", "refusing a non-private address: sharing is LAN only")
        return _strip_scope(host.strip("[]")) if "%" not in host else host.strip("[]")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise ShareError("unresolvable_host", "the host name cannot be resolved") from None
    addrs = [info[4][0] for info in infos]
    if not addrs or not all(is_lan_address(a) for a in addrs):
        raise ShareError("not_lan_address", "refusing a host that resolves to a non-private address: sharing is LAN only")
    return addrs[0]


def detect_lan_address() -> Optional[str]:
    """The machine's LAN IPv4 address (a UDP "connect" sends nothing), or ``None`` when it cannot be determined."""
    for target in ("10.255.255.255", "192.168.255.255", "172.31.255.255"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((target, 1))
                addr = sock.getsockname()[0]
            if is_lan_address(addr) and not addr.startswith("127."):
                return addr
        except OSError:
            continue
    return None
