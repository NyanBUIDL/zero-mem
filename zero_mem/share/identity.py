"""The per-memory sharing identity: a self-signed ECDSA P-256 certificate (ADR-V170-05, section 3).

The ONLY module of the package that needs the optional ``cryptography`` dependency; it is imported lazily and a missing
package raises :class:`~zero_mem.share.ShareDependencyError` (``pip install "zero-mem[share]"``). Files live in
``<data root>/share/`` (directory 0700, key 0600 where the OS enforces mode bits; on Windows the directory inherits the user
profile ACL - see the ADR). ``peer_id`` = first 20 hex of SHA-256(DER); the full SHA-256 is the pinned fingerprint.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import ssl
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import paths
from . import ShareDependencyError, ShareError

CERT_NAME = "identity.crt"
KEY_NAME = "identity.key"
CERT_VALID_DAYS = 365 * 20
MAX_CERT_DER_BYTES = 2048


@dataclass(frozen=True)
class Identity:
    peer_id: str
    fingerprint: str
    cert_der: bytes
    cert_path: Path
    key_path: Path


def crypto():
    """The ``cryptography`` modules (lazy); raises :class:`ShareDependencyError` when it is not installed."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
    except ImportError:
        raise ShareDependencyError() from None
    return x509, hashes, serialization, ec, NameOID


def fingerprint_of_der(der: bytes) -> str:
    return hashlib.sha256(der).hexdigest()


def peer_id_of_der(der: bytes) -> str:
    return fingerprint_of_der(der)[:20]


def share_dir(layout) -> Path:
    path = Path(layout.data_root) / "share"
    paths.ensure_private_dir(path, "share directory")
    return path


def _generate(label: str):
    x509, hashes, serialization, ec, NameOID = crypto()
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, label[:60] or "zero-mem")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=CERT_VALID_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return key_pem, cert.public_bytes(serialization.Encoding.PEM)


def _write_private(path: Path, data: bytes) -> None:
    from src.corpus._fsretry import retry_transient

    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            os.chmod(tmp, 0o600)
        retry_transient(lambda: os.replace(tmp, path))
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp)


def load_identity(layout) -> "Identity | None":
    directory = Path(layout.data_root) / "share"
    cert_path, key_path = directory / CERT_NAME, directory / KEY_NAME
    if not (cert_path.is_file() and key_path.is_file()):
        return None
    try:
        der = ssl.PEM_cert_to_DER_cert(cert_path.read_text(encoding="ascii"))
    except (OSError, ValueError, UnicodeError):
        raise ShareError("identity_unreadable", "the sharing identity files are unreadable or corrupt") from None
    return Identity(peer_id_of_der(der), fingerprint_of_der(der), der, cert_path, key_path)


def ensure_identity(layout, label: str = "zero-mem") -> Identity:
    """The identity of this memory, created on first use (race safe across processes)."""
    from src.storage.coordination import locked

    existing = load_identity(layout)
    if existing is not None:
        return existing
    crypto()  # a missing dependency must fail before anything is written
    directory = share_dir(layout)
    with locked(directory / ".identity.lock", mode="exclusive", timeout=30.0):
        existing = load_identity(layout)
        if existing is not None:
            return existing
        key_pem, cert_pem = _generate(label)
        _write_private(directory / KEY_NAME, key_pem)
        _write_private(directory / CERT_NAME, cert_pem)
    created = load_identity(layout)
    if created is None:  # pragma: no cover - defensive
        raise ShareError("identity_unreadable", "the sharing identity could not be created")
    return created


def rotate_identity(layout, label: str = "zero-mem") -> tuple:
    """Replace the identity with a fresh key pair; ``(old Identity | None, new Identity)``. The caller (``ShareNode``) first
    ends every pairing that depended on the old one. The private key is NOT encrypted: there is no secret store without
    adding a dependency, and a key the program must read unattended cannot be protected by a passphrase it would need to ask for."""
    from src.storage.coordination import locked

    crypto()
    directory = share_dir(layout)
    with locked(directory / ".identity.lock", mode="exclusive", timeout=30.0):
        old = load_identity(layout)
        key_pem, cert_pem = _generate(label)
        _write_private(directory / KEY_NAME, key_pem)
        _write_private(directory / CERT_NAME, cert_pem)
    new = load_identity(layout)
    if new is None:  # pragma: no cover - defensive
        raise ShareError("identity_unreadable", "the sharing identity could not be created")
    return old, new


def validate_peer_certificate(der: bytes) -> None:
    """A joiner's certificate must be a small, valid, currently valid, self-signed ECDSA P-256 certificate."""
    x509, hashes, _serialization, ec, _name = crypto()
    if not isinstance(der, (bytes, bytearray)) or not 100 <= len(der) <= MAX_CERT_DER_BYTES:
        raise ShareError("invalid_certificate", "unacceptable certificate")
    try:
        cert = x509.load_der_x509_certificate(bytes(der))
        public = cert.public_key()
        if not isinstance(public, ec.EllipticCurvePublicKey) or not isinstance(public.curve, ec.SECP256R1):
            raise ValueError("curve")
        if cert.issuer != cert.subject:
            raise ValueError("not self-signed")
        public.verify(cert.signature, cert.tbs_certificate_bytes, ec.ECDSA(cert.signature_hash_algorithm))
        now = datetime.now(timezone.utc)
        if cert.not_valid_before_utc > now + timedelta(days=2) or cert.not_valid_after_utc < now:
            raise ValueError("validity")
    except Exception:
        raise ShareError("invalid_certificate", "unacceptable certificate") from None
