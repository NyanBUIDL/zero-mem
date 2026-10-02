"""Invites (``zm1:`` codes) and the owner-side invite store (ADR-V170-05, section 5).

The code is ``zm1:`` + base64url(JSON ``{v, host, port, server_fp, token, expires, label}``). The token (32 random bytes) is shown
once and kept only as a salted HMAC; redeeming is single use, expiring, constant time and atomic across threads and processes.
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import INVITE_PREFIX, PROTOCOL_VERSION, ShareError
from .util import FP_RE, b64u_decode, b64u_encode, clean_label

MAX_INVITE_CHARS = 2048
MAX_INVITE_SECONDS = 24 * 3600
DEFAULT_INVITE_SECONDS = 600
MAX_ACTIVE_INVITES = 20
TOKEN_BYTES = 32
_STORE_NAME = "invites.json"
_LOCK = threading.RLock()


@dataclass(frozen=True)
class Invite:
    host: str
    port: int
    server_fp: str
    token: str
    expires: int
    label: str

    def encode(self) -> str:
        doc = {"v": PROTOCOL_VERSION, "host": self.host, "port": self.port, "server_fp": self.server_fp,
               "token": self.token, "expires": self.expires, "label": self.label}
        return INVITE_PREFIX + b64u_encode(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def parse_invite(code: object, *, now: Optional[float] = None, check_expiry: bool = True) -> Invite:
    """Strict parser of a ``zm1:`` code (closed schema, bounded sizes). Never echoes the code in errors."""
    if not isinstance(code, str):
        raise ShareError("invalid_invite", "not an invite code")
    code = code.strip()
    if not code.startswith(INVITE_PREFIX) or len(code) > MAX_INVITE_CHARS:
        raise ShareError("invalid_invite", "not a zm1: invite code")
    try:
        doc = json.loads(b64u_decode(code[len(INVITE_PREFIX):], max_len=MAX_INVITE_CHARS).decode("utf-8"))
    except (ValueError, UnicodeError, ShareError):
        raise ShareError("invalid_invite", "the invite code is damaged") from None
    if not isinstance(doc, dict) or set(doc) != {"v", "host", "port", "server_fp", "token", "expires", "label"}:
        raise ShareError("invalid_invite", "the invite code is not valid")
    host, port, fp, token, expires, label = (doc[k] for k in ("host", "port", "server_fp", "token", "expires", "label"))
    if doc["v"] != PROTOCOL_VERSION:
        raise ShareError("invalid_invite", "unsupported invite version")
    if (not isinstance(host, str) or not 1 <= len(host) <= 253 or any(ord(c) < 33 or ord(c) == 127 for c in host)
            or not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535
            or not isinstance(fp, str) or not FP_RE.fullmatch(fp)
            or not isinstance(expires, int) or isinstance(expires, bool) or expires < 0):
        raise ShareError("invalid_invite", "the invite code is not valid")
    try:
        raw = b64u_decode(token, max_len=128)
        label = clean_label(label)
    except ShareError:
        raise ShareError("invalid_invite", "the invite code is not valid") from None
    if not 16 <= len(raw) <= 64:
        raise ShareError("invalid_invite", "the invite code is not valid")
    if check_expiry and (now if now is not None else time.time()) >= expires:
        raise ShareError("invite_expired", "the invite has expired; ask the owner for a new one")
    return Invite(host=host, port=port, server_fp=fp, token=token, expires=expires, label=label)


def _hash(salt: bytes, token: str) -> bytes:
    return hmac.new(salt, token.encode("ascii"), hashlib.sha256).digest()


class InviteStore:
    """``<data root>/share/invites.json``: salted token hashes + state (never the token)."""

    def __init__(self, directory: Path, clock: Optional[Callable[[], float]] = None) -> None:
        self._dir = Path(directory)
        self._path = self._dir / _STORE_NAME
        self._clock = clock or time.time

    # -- plumbing --------------------------------------------------------------------------
    @contextlib.contextmanager
    def _locked(self):
        from src.storage.coordination import locked
        from src.storage.platform import lock_wait_seconds

        from .. import paths

        try:
            paths.ensure_lock_parent(self._dir / ".invites.lock", "share directory")
        except paths.SetupError:
            raise ShareError("invite_store_unusable", "the share directory is unusable") from None
        with _LOCK, locked(self._dir / ".invites.lock", mode="exclusive", timeout=lock_wait_seconds(30.0)):
            yield

    def _load(self) -> list:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [r for r in data.get("invites", []) if isinstance(r, dict)] if isinstance(data, dict) else []

    def _save(self, rows: list) -> None:
        from src.corpus._fsretry import retry_transient

        fd, tmp = tempfile.mkstemp(prefix=".invites.", suffix=".tmp", dir=str(self._dir))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(json.dumps({"invites": rows}, sort_keys=True).encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            if os.name != "nt":
                os.chmod(tmp, 0o600)
            retry_transient(lambda: os.replace(tmp, self._path))
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp)

    # -- operations ------------------------------------------------------------------------
    def create(self, *, host: str, port: int, server_fp: str, label: str, expires_in: int, grants: list) -> tuple:
        """``(Invite, invite_id)``; the token exists only in the returned :class:`Invite`."""
        if not 1 <= expires_in <= MAX_INVITE_SECONDS:
            raise ShareError("invalid_duration", "an invite lives between 1 second and 24 hours")
        token = b64u_encode(secrets.token_bytes(TOKEN_BYTES))
        salt = secrets.token_bytes(16)
        now = int(self._clock())
        invite_id = "inv-" + secrets.token_hex(6)
        with self._locked():
            rows = [r for r in self._load() if r.get("expires", 0) > now - 86400]
            active = [r for r in rows if r.get("status") == "open" and r.get("expires", 0) > now]
            if len(active) >= MAX_ACTIVE_INVITES:
                raise ShareError("too_many_invites", "too many open invites; wait for them to expire")
            rows.append({"invite_id": invite_id, "salt": b64u_encode(salt), "hash": b64u_encode(_hash(salt, token)),
                         "expires": now + expires_in, "status": "open", "created": now, "label": label, "grants": grants})
            self._save(rows)
        return Invite(host=host, port=port, server_fp=server_fp, token=token, expires=now + expires_in, label=label), invite_id

    def redeem(self, token: object) -> tuple:
        """Atomically consume the open invite matching ``token``: ``("ok", record)`` or ``(reason, None)`` where reason is
        ``malformed`` / ``unknown`` / ``expired`` / ``used`` / ``burned`` (audited; never shown to the peer)."""
        if not isinstance(token, str) or not 16 <= len(token) <= 128 or b64u_decode_safe(token) is None:
            return "malformed", None
        now = int(self._clock())
        with self._locked():
            rows = self._load()
            hit = None
            for row in rows:  # compare against EVERY row (no early exit on a match)
                try:
                    candidate = hmac.compare_digest(_hash(b64u_decode(row["salt"], max_len=64), token),
                                                    b64u_decode(row["hash"], max_len=64))
                except (KeyError, ShareError, TypeError):
                    candidate = False
                if candidate and hit is None:
                    hit = row
            if hit is None:
                return "unknown", None
            if hit.get("status") == "used":
                return "used", None
            if hit.get("status") == "burned":
                return "burned", None
            if hit.get("expires", 0) <= now:
                return "expired", None
            hit["status"] = "used"
            hit["used_at"] = now
            self._save(rows)
            return "ok", {k: hit[k] for k in ("invite_id", "label", "grants")}

    def has_open(self) -> bool:
        now = int(self._clock())
        with self._locked():
            return any(r.get("status") == "open" and r.get("expires", 0) > now for r in self._load())

    def burn_open(self) -> int:
        """Lock out every currently open invite for the rest of its life (brute-force response)."""
        now = int(self._clock())
        with self._locked():
            rows = self._load()
            burned = 0
            for row in rows:
                if row.get("status") == "open" and row.get("expires", 0) > now:
                    row["status"] = "burned"
                    burned += 1
            if burned:
                self._save(rows)
            return burned

    def list(self) -> list:
        with self._locked():
            return [{k: v for k, v in r.items() if k not in ("salt", "hash")} for r in self._load()]


def b64u_decode_safe(text: str):
    try:
        return b64u_decode(text, max_len=128)
    except ShareError:
        return None
