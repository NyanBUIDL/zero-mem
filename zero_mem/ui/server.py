"""The control panel's HTTP server: loopback-only binding, session cookie, Host / Origin / CSRF checks, security headers.

This is a privileged local service (it can approve rules, grant write access and ingest files), so every request is
treated as hostile until proven otherwise:

* bind ONLY to a loopback literal (``127.0.0.1`` / ``::1``); anything else is refused before a socket exists, and a
  connection from a non-loopback peer is dropped;
* a random 256-bit one-time URL token is exchanged for an ``HttpOnly; SameSite=Strict`` session cookie (itself a separate
  256-bit secret, named per port so another local service cannot clobber it); all comparisons are constant time;
* strict ``Host`` allow-list (DNS rebinding), ``Origin`` / ``Referer`` check and a per-session CSRF token on every POST;
* POST for every mutation; no CORS headers; CSP ``default-src 'none'`` with a per-response nonce for the one inline style;
* bounded request line / headers (stdlib), body (1 MiB forms, 25 MiB uploads), socket timeout, total read deadline,
  maximum concurrent connections, idle shutdown.

Standard library only (``http.server`` + ``threading``). Handlers never raise a stack trace to the browser.
"""
from __future__ import annotations

import hmac
import ipaddress
import secrets
import socket
import socketserver
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional
from urllib.parse import parse_qsl, urlsplit

from .forms import FormData, FormError, parse_multipart, parse_urlencoded
from .render import error_page

MAX_FORM_BYTES = 1024 * 1024
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MULTIPART_OVERHEAD = 1024 * 1024
MAX_URL_CHARS = 4096
DEFAULT_MAX_CONNECTIONS = 32
DEFAULT_REQUEST_TIMEOUT = 15.0
FORM_DEADLINE = 30.0
UPLOAD_DEADLINE = 120.0
COOKIE_BASE = "zm_session"
LOOPBACK_NAMES = {"127.0.0.1": socket.AF_INET, "::1": socket.AF_INET6}


class PanelSecurityError(ValueError):
    """The requested configuration would weaken the panel's security (for example a non-loopback bind)."""


@dataclass
class Request:
    method: str
    path: str
    query: dict
    form: FormData = field(default_factory=FormData)
    files: dict = field(default_factory=dict)


@dataclass
class Response:
    status: int = 200
    body: bytes = b""
    content_type: str = "text/html; charset=utf-8"
    headers: list = field(default_factory=list)


def redirect(location: str, status: int = 303) -> Response:
    return Response(status=status, body=b"", headers=[("Location", location)])


def resolve_host(host: str) -> str:
    """The loopback literal to bind for ``host`` (``localhost`` means ``127.0.0.1``); anything else is refused."""
    if not isinstance(host, str):
        raise PanelSecurityError("the control panel binds only to a loopback address (127.0.0.1 or ::1)")
    value = host.strip().lower()
    if value == "localhost":
        return "127.0.0.1"
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise PanelSecurityError("the control panel binds only to a loopback address (127.0.0.1 or ::1)") from None
    if address.version == 4 and address == ipaddress.ip_address("127.0.0.1"):
        return "127.0.0.1"
    if address.version == 6 and address == ipaddress.ip_address("::1"):
        return "::1"
    raise PanelSecurityError("the control panel binds only to a loopback address (127.0.0.1 or ::1)")


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8", "replace"), b.encode("utf-8", "replace"))


class PanelServer(ThreadingHTTPServer):
    """Threaded loopback HTTP server holding the session secrets and the connection budget."""

    daemon_threads = True
    allow_reuse_address = False  # on Windows SO_REUSEADDR would let another process share the port
    request_queue_size = 16

    def __init__(self, host: str, port: int, route: Callable, *, idle_timeout: float = 3600.0,
                 max_connections: int = DEFAULT_MAX_CONNECTIONS, request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
                 log: Optional[Callable[[str], None]] = None) -> None:
        bound = resolve_host(host)
        if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65535:
            raise PanelSecurityError("the port must be between 0 and 65535")
        self.address_family = LOOPBACK_NAMES[bound]
        self.route = route
        self.idle_timeout = float(idle_timeout)
        self.request_timeout = float(request_timeout)
        self.token = secrets.token_urlsafe(32)               # 256-bit, single use, printed once
        self._cookie_secret = secrets.token_urlsafe(32)      # 256-bit session secret (never printed)
        self.csrf_token = secrets.token_urlsafe(32)
        self._token_used = False
        self._token_lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(max_connections)
        self._activity = time.monotonic()
        self._stopped_for_idle = False
        self._watch_stop = threading.Event()
        self.log = log or (lambda line: print(line, file=sys.stderr, flush=True))
        super().__init__((bound, port), PanelHandler)
        self.host = bound
        self.port = self.server_address[1]
        authority = f"[{bound}]" if ":" in bound else bound
        self.allowed_hosts = frozenset({f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"[::1]:{self.port}"})
        self.allowed_origins = frozenset({f"http://{h}" for h in self.allowed_hosts})
        self.cookie_name = f"{COOKIE_BASE}_{self.port}"
        self.base_url = f"http://{authority}:{self.port}/"

    # -- plumbing -------------------------------------------------------------------------------------
    def server_bind(self) -> None:
        # HTTPServer.server_bind calls socket.getfqdn (a reverse DNS lookup); a loopback server needs none.
        socketserver.TCPServer.server_bind(self)
        self.server_name = self.server_address[0]
        self.server_port = self.server_address[1]

    def entry_url(self) -> str:
        """The one-time URL to open (printed once by ``zero-mem ui``)."""
        return f"{self.base_url}?t={self.token}"

    def touch(self) -> None:
        self._activity = time.monotonic()

    def idle_seconds(self) -> float:
        return time.monotonic() - self._activity

    def process_request(self, request, client_address) -> None:
        try:
            peer = ipaddress.ip_address(client_address[0].split("%")[0])
            local = peer.is_loopback
        except (ValueError, IndexError, AttributeError):
            local = False
        if not local or not self._slots.acquire(blocking=False):
            try:
                if local:
                    request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def handle_error(self, request, client_address) -> None:  # never print a traceback with request data
        self.log("zero-mem ui: connection error (" + type(sys.exc_info()[1]).__name__ + ")")

    # -- credentials ----------------------------------------------------------------------------------
    def exchange_token(self, candidate: str) -> Optional[str]:
        """The session cookie value when ``candidate`` is the (unused) URL token, else ``None``."""
        with self._token_lock:
            if self._token_used or not _same(candidate, self.token):
                return None
            self._token_used = True
        return self._cookie_secret

    def cookie_ok(self, header: Optional[str]) -> bool:
        if not header:
            return False
        for part in header.split(";"):
            name, _sep, value = part.strip().partition("=")
            if name == self.cookie_name and _same(value.strip(), self._cookie_secret):
                return True
        return False

    def csrf_ok(self, candidate: Optional[str]) -> bool:
        return bool(candidate) and _same(candidate, self.csrf_token)

    # -- lifecycle ------------------------------------------------------------------------------------
    def start_idle_watch(self) -> threading.Thread:
        def watch() -> None:
            interval = min(1.0, max(0.05, self.idle_timeout / 4))
            while not self._watch_stop.wait(interval):
                if self.idle_seconds() > self.idle_timeout:
                    self._stopped_for_idle = True
                    self.log("zero-mem ui: stopping after the idle timeout")
                    self.shutdown()
                    return

        thread = threading.Thread(target=watch, name="zero-mem-ui-idle", daemon=True)
        thread.start()
        return thread

    def server_close(self) -> None:
        self._watch_stop.set()
        super().server_close()

    def serve(self) -> None:
        self.start_idle_watch()
        self.serve_forever(poll_interval=0.2)


class PanelHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # one request per connection: no keep-alive state to abuse
    server: PanelServer

    def setup(self) -> None:
        self.timeout = self.server.request_timeout
        super().setup()

    # -- quiet, secret-free logging ------------------------------------------------------------------
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return  # request lines can carry the one-time token; per-request logging happens in _finish without the query

    def version_string(self) -> str:
        return "zero-mem-ui"

    def send_error(self, code, message=None, explain=None) -> None:  # generic, never echoes request data
        try:
            self._send(self._plain(code), nonce=secrets.token_urlsafe(16))
        except OSError:
            pass

    # -- verbs ---------------------------------------------------------------------------------------
    def do_GET(self) -> None:
        self._serve("GET")

    def do_POST(self) -> None:
        self._serve("POST")

    def _other(self) -> None:
        self._send(self._plain(405), nonce=secrets.token_urlsafe(16), extra=[("Allow", "GET, POST")])

    do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = do_CONNECT = _other

    # -- core ----------------------------------------------------------------------------------------
    def _plain(self, code: int, message: Optional[str] = None) -> Response:
        texts = {400: "Bad request.", 401: "Not signed in. Open the one-time URL printed by zero-mem ui in the terminal.",
                 403: "Forbidden.", 404: "Not found.", 405: "Method not allowed.", 408: "Request timed out.",
                 411: "Length required.", 413: "That request is too large.", 415: "Unsupported content type.",
                 431: "Request headers too large.", 500: "Something went wrong. Nothing was shown to protect your data; "
                 "see the terminal running zero-mem ui.", 501: "Not supported.", 503: "Busy."}
        text = message or texts.get(code, "Request refused.")
        nonce = secrets.token_urlsafe(16)
        return Response(status=code, body=error_page("Error" if code != 401 else "Sign in required", text, nonce=nonce),
                        headers=[("X-Nonce", nonce)])

    def _serve(self, method: str) -> None:
        nonce = secrets.token_urlsafe(16)
        try:
            response = self._route(method, nonce)
        except _Refuse as refusal:
            response = self._plain(refusal.code, refusal.message)
        except Exception as exc:  # noqa: BLE001 - never a stack trace to the browser
            where = ""
            tb = exc.__traceback__
            while tb is not None and tb.tb_next is not None:
                tb = tb.tb_next
            if tb is not None:
                where = f" at {tb.tb_frame.f_code.co_filename.rsplit('/', 1)[-1].rsplit(chr(92), 1)[-1]}:{tb.tb_lineno}"
            self.server.log(f"zero-mem ui: {method} {urlsplit(self.path).path} failed ({type(exc).__name__}{where})")
            response = self._plain(500)
        self._send(response, nonce=nonce)

    def _route(self, method: str, nonce: str) -> Response:
        server = self.server
        host = (self.headers.get("Host") or "").strip().lower()
        if host not in server.allowed_hosts:  # DNS rebinding: the browser sends the attacker's name here
            raise _Refuse(403)
        if len(self.path) > MAX_URL_CHARS or not self.path.startswith("/"):
            raise _Refuse(400)
        parts = urlsplit(self.path)
        try:
            pairs = parse_qsl(parts.query, keep_blank_values=True, max_num_fields=50, encoding="utf-8", errors="strict")
        except (ValueError, UnicodeError):
            raise _Refuse(400) from None
        query = {}
        for key, value in pairs:
            query.setdefault(key, value)
        path = parts.path or "/"
        # one-time URL token -> session cookie, then a token-free URL
        if method == "GET" and path == "/" and "t" in query:
            secret = server.exchange_token(query["t"])
            if secret is None:
                raise _Refuse(403, "This link is not valid (it can be used only once). Restart zero-mem ui for a new one.")
            server.touch()
            return Response(status=303, headers=[
                ("Location", "/"),
                ("Set-Cookie", f"{server.cookie_name}={secret}; Path=/; HttpOnly; SameSite=Strict")])
        if not server.cookie_ok(self.headers.get("Cookie")):
            raise _Refuse(401)
        server.touch()
        request = Request(method=method, path=path, query=query)
        if method == "POST":
            self._check_origin()
            self._read_body(request)
            if not server.csrf_ok(request.form.get("csrf")):
                raise _Refuse(403, "The form's security token is missing or stale. Reload the page and try again.")
        return server.route(request, nonce, server.csrf_token)

    def _check_origin(self) -> None:
        origin = self.headers.get("Origin")
        if origin is not None:
            if origin.strip().lower() not in self.server.allowed_origins:
                raise _Refuse(403)
            return
        referer = self.headers.get("Referer")
        if referer:
            parts = urlsplit(referer)
            if f"{parts.scheme}://{parts.netloc}".lower() in self.server.allowed_origins:
                return
        raise _Refuse(403)  # a state-changing request must prove where it came from

    def _read_body(self, request: Request) -> None:
        if self.headers.get("Transfer-Encoding"):
            raise _Refuse(411)
        raw = self.headers.get("Content-Length")
        if raw is None or not raw.strip().isdigit() or len(raw.strip()) > 12:
            raise _Refuse(411)
        length = int(raw.strip())
        content_type = (self.headers.get("Content-Type") or "").strip()
        mime = content_type.split(";", 1)[0].strip().lower()
        if mime == "application/x-www-form-urlencoded":
            limit, deadline = MAX_FORM_BYTES, FORM_DEADLINE
        elif mime == "multipart/form-data":
            limit, deadline = MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD, UPLOAD_DEADLINE
        else:
            raise _Refuse(415)
        if length > limit:
            raise _Refuse(413)
        body = self._read_exact(length, time.monotonic() + deadline)
        try:
            if mime == "multipart/form-data":
                fields, files = parse_multipart(body, content_type, max_file_bytes=MAX_UPLOAD_BYTES)
                request.form, request.files = fields, files
            else:
                request.form = parse_urlencoded(body)
        except FormError as exc:
            raise _Refuse(413 if "too large" in str(exc) else 400, str(exc) + ".") from None

    def _read_exact(self, length: int, deadline: float) -> bytes:
        chunks, remaining = [], length
        while remaining > 0:
            if time.monotonic() > deadline:
                raise _Refuse(408)
            try:
                chunk = self.rfile.read(min(65536, remaining))
            except (socket.timeout, TimeoutError):
                raise _Refuse(408) from None
            if not chunk:
                raise _Refuse(400)
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    # -- output ---------------------------------------------------------------------------------------
    def _send(self, response: Response, *, nonce: str, extra: Optional[list] = None) -> None:
        headers = list(response.headers)
        for name, value in list(headers):
            if name == "X-Nonce":  # an error page built before the nonce was known carries its own
                nonce = value
                headers.remove((name, value))
        csp = ("default-src 'none'; style-src 'nonce-%s'; img-src 'self'; form-action 'self'; "
               "base-uri 'none'; frame-ancestors 'none'" % nonce)
        security = [
            ("Content-Security-Policy", csp), ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"),
            ("Cache-Control", "no-store"), ("Pragma", "no-cache"), ("X-Frame-Options", "DENY"),
            ("Cross-Origin-Opener-Policy", "same-origin"), ("Cross-Origin-Resource-Policy", "same-origin"),
        ]
        try:
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            for name, value in security + headers + (extra or []):
                self.send_header(name, value)
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(response.body)
        except (OSError, ValueError):
            pass


class _Refuse(Exception):
    def __init__(self, code: int, message: Optional[str] = None) -> None:
        super().__init__(code)
        self.code = code
        self.message = message
