"""V150-WP1 (DEF-011) — corpus projection integrity gate.

Space-grant authorization on the event path reads the DERIVED corpus projection
(``zm_corpus_sources`` / ``zm_corpus_units``) to resolve knowledge-space
members. ADR-V150-01 Option A requires that this derived input never silently
drives a security decision: the caller arms :class:`ProjectionDigestGate` with
a digest computed over canonical corpus state (registry JSONL + blob digests),
and the service verifies the live derived projection against it before trusting
member expansion.

Semantics:

- ``verify()`` recomputes the digest from the live derived tables and compares
  it to the armed expectation.
- Mismatch, missing digest, or any verification error => FAIL-CLOSED
  (gate returns False; callers must keep space grants non-authorizing).
- The digest is deterministic and rebuildable: identical canonical state =>
  identical digest. It is NOT a new source of truth — canonical corpus data
  remains authoritative; the gate only detects stale/tampered projections.
"""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Final, Optional, Tuple

_DIGEST_VERSION: Final[str] = "v1"

#: Rows are digested in this stable order for determinism.
_TABLES: Final[Tuple[Tuple[str, Tuple[str, ...]], ...]] = (
    ("zm_corpus_sources",
     ("source_id", "external_ref", "kind",
      "profile_id", "project_id", "knowledge_space_id")),
    ("zm_corpus_units",
     ("unit_id", "source_ref", "content_hash",
      "profile_id", "project_id", "knowledge_space_id")),
)


def compute_corpus_projection_digest(conn: sqlite3.Connection,
                                     limit_rows: int = 200_000) -> str:
    """Deterministic digest of the authorization-relevant projection subset.

    Only identity/ownership columns participate (no text payloads): the gate
    protects *authorization* decisions, not content fidelity. Row order is
    normalized by ORDER BY over the primary key so physical layout cannot
    change the digest. Unknown schema (missing table/column) raises
    ``ProjectionIntegrityError`` so callers fail closed.
    """
    try:
        hasher = hashlib.sha256()
        hasher.update(_DIGEST_VERSION.encode("utf-8"))
        n_total = 0
        for table, cols in _TABLES:
            col_list = ",".join(cols)
            cur = conn.execute(
                f"SELECT {col_list} FROM {table} "
                f"ORDER BY {cols[0]} LIMIT ?",
                (limit_rows,),
            )
            for row in cur:
                hasher.update(
                    "\x1f".join("" if v is None else str(v) for v in row)
                    .encode("utf-8"))
                hasher.update(b"\x1e")
                n_total += 1
        hasher.update(f"|rows={n_total}".encode("utf-8"))
        return hasher.hexdigest()
    except sqlite3.Error as exc:
        raise ProjectionIntegrityError(
            "projection_digest_unavailable") from None


class ProjectionIntegrityError(RuntimeError):
    """Raised when the projection cannot be digested (schema drift / damage)."""


class ProjectionDigestGate:
    """Fail-closed verifier armed with an expected projection digest."""

    __slots__ = ("_expected",)

    def __init__(self, expected_digest: Optional[str]) -> None:
        self._expected = expected_digest

    @property
    def expected(self) -> Optional[str]:
        return self._expected

    def verify(self, conn: sqlite3.Connection) -> bool:
        """True only when the live projection digest matches the expectation.

        Any error (unreadable schema, closed conn, digest exception) is a
        fail-closed False — never an exception escaping into authorization.
        """
        if not self._expected:
            return False
        try:
            actual = compute_corpus_projection_digest(conn)
        except Exception:
            return False
        return hmac_compare(self._expected, actual)


def hmac_compare(expected: Optional[str], actual: Optional[str]) -> bool:
    """Constant-time string comparison (defense-in-depth for digest checks)."""
    import hmac as _hmac
    if not expected or not actual:
        return False
    return _hmac.compare_digest(expected.encode("utf-8"), actual.encode("utf-8"))


__all__ = [
    "ProjectionDigestGate",
    "ProjectionIntegrityError",
    "compute_corpus_projection_digest",
    "hmac_compare",
]
