"""A strict, minimal HTTP/1.1 request/response layer over an already-authenticated TLS socket (standard library only).

Server side: bounded header block, bounded body, mandatory ``Content-Length`` for POST, no chunked encoding, no keep-alive,
total request deadline (slowloris). Client side: bounded response, ``Content-Length`` mandatory.
"""
from __future__ import annotations

import re
import socket
import ssl
import time
from dataclasses import dataclass, field
from typing import Optional

from . import ShareError

MAX_HEADER_BYTES = 8192
MAX_HEADERS = 32
MAX_TARGET = 512
_TOKEN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_REASONS = {200: "OK", 400: "Bad Request", 403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed",
            408: "Request Timeout", 411: "Length Required", 413: "Payload Too Large", 429: "Too Many Requests",
            431: "Request Header Fields Too Large", 500: "Internal Server Error", 501: "Not Implemented",
            503: "Service Unavailable"}


class HttpError(Exception):
    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


@dataclass
class Request:
    method: str
    path: str
    query: str
    headers: dict = field(default_factory=dict)
    body: bytes = b""


def _recv(sock, deadline: float, n: int = 4096) -> bytes:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise HttpError(408, "request_timeout")
    sock.settimeout(min(remaining, 5.0))
    try:
        return sock.recv(n)
    except socket.timeout:
        raise HttpError(408, "request_timeout") from None
    except (ssl.SSLError, OSError):
        raise HttpError(400, "connection_error") from None


def read_request(sock, *, deadline: float, max_body: int) -> Request:
    buf = b""
    while b"\r\n\r\n" not in buf:
        if len(buf) > MAX_HEADER_BYTES:
            raise HttpError(431, "headers_too_large")
        chunk = _recv(sock, deadline)
        if not chunk:
            raise HttpError(400, "connection_closed")
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    if len(head) > MAX_HEADER_BYTES:
        raise HttpError(431, "headers_too_large")
    try:
        lines = head.decode("ascii").split("\r\n")
    except UnicodeDecodeError:
        raise HttpError(400, "bad_request") from None
    parts = lines[0].split(" ")
    if len(parts) != 3 or parts[2] != "HTTP/1.1" or not re.fullmatch(r"[A-Z]{1,10}", parts[0]):
        raise HttpError(400, "bad_request_line")
    method, target = parts[0], parts[1]
    if not target.startswith("/") or len(target) > MAX_TARGET or any(ord(c) < 33 or ord(c) > 126 for c in target):
        raise HttpError(400, "bad_target")
    path, _, query = target.partition("?")
    headers: dict = {}
    if len(lines) - 1 > MAX_HEADERS:
        raise HttpError(431, "too_many_headers")
    for line in lines[1:]:
        name, sep, value = line.partition(":")
        if not sep or not _TOKEN.fullmatch(name) or line[:1] in (" ", "\t"):
            raise HttpError(400, "bad_header")
        name = name.lower()
        if name in headers:
            raise HttpError(400, "duplicate_header")
        headers[name] = value.strip()
    if "transfer-encoding" in headers:
        raise HttpError(501, "transfer_encoding_unsupported")
    length = 0
    if "content-length" in headers:
        if not re.fullmatch(r"\d{1,9}", headers["content-length"]):
            raise HttpError(400, "bad_content_length")
        length = int(headers["content-length"])
    elif method == "POST":
        raise HttpError(411, "length_required")
    if length > max_body:
        raise HttpError(413, "body_too_large")
    if method != "POST" and length:
        raise HttpError(400, "unexpected_body")
    body = rest
    while len(body) < length:
        chunk = _recv(sock, deadline, min(65536, length - len(body)))
        if not chunk:
            raise HttpError(400, "connection_closed")
        body += chunk
    if len(body) > length:
        raise HttpError(400, "pipelining_unsupported")
    return Request(method=method, path=path, query=query, headers=headers, body=body)


def send_response(sock, status: int, body: bytes, *, allow: Optional[str] = None) -> None:
    head = [f"HTTP/1.1 {status} {_REASONS.get(status, 'Error')}", "Content-Type: application/json",
            f"Content-Length: {len(body)}", "Connection: close", "Cache-Control: no-store", "X-Content-Type-Options: nosniff"]
    if allow:
        head.append(f"Allow: {allow}")
    try:
        sock.settimeout(10.0)
        sock.sendall(("\r\n".join(head) + "\r\n\r\n").encode("ascii") + body)
    except (OSError, ssl.SSLError):
        pass


# ---------------------------------------------------------------------------------------------
# client
# ---------------------------------------------------------------------------------------------
def request(sock, method: str, path: str, body: Optional[bytes] = None, *, max_response: int, timeout: float = 30.0) -> tuple:
    """Send one request, return ``(status, body bytes)``. Raises :class:`ShareError` on any protocol problem."""
    deadline = time.monotonic() + timeout
    head = [f"{method} {path} HTTP/1.1", "Host: zero-mem-share", "Accept: application/json", "Connection: close"]
    if body is not None:
        head += ["Content-Type: application/json", f"Content-Length: {len(body)}"]
    try:
        sock.settimeout(timeout)
        sock.sendall(("\r\n".join(head) + "\r\n\r\n").encode("ascii") + (body or b""))
    except (OSError, ssl.SSLError):
        raise ShareError("connection_failed", "the peer closed the connection (it may have revoked access)") from None
    buf = b""
    try:
        while b"\r\n\r\n" not in buf:
            if len(buf) > MAX_HEADER_BYTES:
                raise ShareError("invalid_response", "response headers too large")
            chunk = _recv(sock, deadline)
            if not chunk:
                raise ShareError("connection_failed", "the peer closed the connection (it may have revoked access)")
            buf += chunk
        head_b, _, rest = buf.partition(b"\r\n\r\n")
        lines = head_b.decode("ascii").split("\r\n")
        match = re.fullmatch(r"HTTP/1\.1 (\d{3})(?: .*)?", lines[0])
        if not match:
            raise ShareError("invalid_response", "malformed response")
        headers = {}
        for line in lines[1:]:
            name, _sep, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        if "transfer-encoding" in headers or not re.fullmatch(r"\d{1,9}", headers.get("content-length", "x")):
            raise ShareError("invalid_response", "unsupported response framing")
        length = int(headers["content-length"])
        if length > max_response:
            raise ShareError("response_too_large", "the peer's response exceeds the allowed size")
        data = rest
        while len(data) < length:
            chunk = _recv(sock, deadline, min(65536, length - len(data)))
            if not chunk:
                raise ShareError("connection_failed", "the peer closed the connection early")
            data += chunk
        return int(match.group(1)), data[:length]
    except HttpError:
        raise ShareError("connection_failed", "the peer timed out or closed the connection") from None
    except UnicodeDecodeError:
        raise ShareError("invalid_response", "malformed response") from None
