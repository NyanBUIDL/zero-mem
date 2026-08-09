"""M8.1 — frozen temporal metadata contract.

Freezes the representation of the two time dimensions M8 is permitted to use
(plan-m8.md §8), and nothing more:

- **Transaction / history time** — when the system recorded or observed a fact.
  Sourced from existing canonical fields (``created_at``, ``observed_at``) and
  the canonical append sequence. Diagnostic ``ingested_at`` is storage
  projection time and is explicitly NOT real-world validity.
- **Valid / effective time** — when a fact is asserted to hold in the world.
  Sourced ONLY from existing explicit fields (``effective_at``, ``valid_from``,
  ``valid_until``).

Hard rules enforced here:

- No invented timestamps. A missing value stays ``None`` — it is never
  backfilled from another dimension, from the append sequence, or from
  ``datetime.now()``.
- Malformed, non-string, or timezone-naive timestamps are REJECTED. They are
  not silently repaired, truncated, or assumed to be UTC.
- Normalization to UTC is for comparison only; the original canonical string is
  always preserved alongside it.
- Recency is not authority. This module deliberately exposes no "latest wins",
  "is_newer", or ordering-by-time helper. Selecting a winner by timestamp is
  forbidden M8 semantics; supersession and lifecycle remain authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Final, Optional

#: Frozen temporal-contract version.
TEMPORAL_CONTRACT_VERSION: Final[str] = "v1"

#: Transaction/history-time dimensions (when the system recorded something).
TRANSACTION_TIME_FIELDS: Final[tuple[str, ...]] = ("created_at", "observed_at")

#: Valid/effective-time dimensions (when a fact is asserted to hold).
VALID_TIME_FIELDS: Final[tuple[str, ...]] = ("effective_at", "valid_from", "valid_until")

#: Diagnostic-only dimension. Never real-world validity, never comparable to
#: valid time, never a supersession input.
DIAGNOSTIC_TIME_FIELDS: Final[tuple[str, ...]] = ("ingested_at",)


class TemporalError(ValueError):
    """Sanitized temporal-contract violation.

    Carries the offending field name and a short, newline-free echo of the
    rejected token only — never payload text or secrets.
    """

    def __init__(self, field: str, reason: str, value: object = None) -> None:
        detail = f"temporal_error: {reason}: {field}"
        if value is not None:
            token = str(value).replace("\n", " ").replace("\r", " ")
            if len(token) > 48:
                token = token[:48] + "...(truncated)"
            detail = f"{detail}: {token!r}"
        super().__init__(detail)
        self.field = field
        self.reason = reason


def _parse_iso8601(field: str, raw: str) -> datetime:
    """Parse a strict ISO-8601 timestamp that MUST carry an explicit offset."""
    if not isinstance(raw, str):
        raise TemporalError(field, "not_a_string")
    text = raw.strip()
    if not text or text != raw:
        # Leading/trailing whitespace is a malformed record, not something to
        # quietly clean up on the way into a derived index.
        raise TemporalError(field, "malformed_timestamp", raw)
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        raise TemporalError(field, "malformed_timestamp", raw) from None
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        # Timezone-naive values are ambiguous. Assuming UTC would be inventing
        # information the canonical record does not contain.
        raise TemporalError(field, "timezone_naive", raw)
    return parsed


@dataclass(frozen=True)
class NormalizedTimestamp:
    """An accepted timestamp: canonical original + UTC comparison form."""

    #: The exact string as stored canonically. Never rewritten.
    raw: str
    #: UTC-normalized ISO-8601 form, for comparison only.
    utc: str

    def as_datetime(self) -> datetime:
        return datetime.fromisoformat(self.utc)

    def to_dict(self) -> dict[str, str]:
        return {"raw": self.raw, "utc": self.utc}


def normalize_timestamp(field: str, value: Optional[str]) -> Optional[NormalizedTimestamp]:
    """Validate and UTC-normalize one timestamp.

    ``None`` in means ``None`` out: absence is preserved, never invented.
    Anything present but malformed or timezone-naive raises ``TemporalError``.
    """
    if value is None:
        return None
    parsed = _parse_iso8601(field, value)
    utc = parsed.astimezone(timezone.utc).isoformat()
    return NormalizedTimestamp(raw=value, utc=utc)


@dataclass(frozen=True)
class TemporalMetadata:
    """Frozen temporal envelope for one derived M8 record.

    Every field is optional because canonical sources genuinely differ in which
    clocks they carry (M4 decisions have ``effective_at`` and no ``created_at``;
    M2 events have ``created_at``/``observed_at`` and no validity interval).
    A dimension that the source does not have stays ``None``.

    This object is metadata. It expresses no precedence, no winner, and no
    truth: possessing a newer ``valid_from`` gives a record no authority over
    another (plan-m8.md §8 "Supersession and conflict").
    """

    created_at: Optional[NormalizedTimestamp] = None
    observed_at: Optional[NormalizedTimestamp] = None
    effective_at: Optional[NormalizedTimestamp] = None
    valid_from: Optional[NormalizedTimestamp] = None
    valid_until: Optional[NormalizedTimestamp] = None
    superseded_at: Optional[NormalizedTimestamp] = None
    ingested_at: Optional[NormalizedTimestamp] = None

    @property
    def has_transaction_time(self) -> bool:
        """True when at least one transaction/history-time dimension exists."""
        return self.created_at is not None or self.observed_at is not None

    @property
    def has_valid_time(self) -> bool:
        """True when at least one explicit valid/effective dimension exists.

        When this is False, an as-of query must return bounded insufficiency
        rather than synthesizing a validity interval (deferred to M8.4).
        """
        return (
            self.effective_at is not None
            or self.valid_from is not None
            or self.valid_until is not None
        )

    def to_dict(self) -> dict[str, Any]:
        """Deterministic serialization; absent dimensions serialize as ``None``."""
        return {
            "created_at": self.created_at.to_dict() if self.created_at else None,
            "observed_at": self.observed_at.to_dict() if self.observed_at else None,
            "effective_at": self.effective_at.to_dict() if self.effective_at else None,
            "valid_from": self.valid_from.to_dict() if self.valid_from else None,
            "valid_until": self.valid_until.to_dict() if self.valid_until else None,
            "superseded_at": self.superseded_at.to_dict() if self.superseded_at else None,
            "ingested_at": self.ingested_at.to_dict() if self.ingested_at else None,
            "temporal_contract_version": TEMPORAL_CONTRACT_VERSION,
        }


def build_temporal_metadata(
    *,
    created_at: Optional[str] = None,
    observed_at: Optional[str] = None,
    effective_at: Optional[str] = None,
    valid_from: Optional[str] = None,
    valid_until: Optional[str] = None,
    superseded_at: Optional[str] = None,
    ingested_at: Optional[str] = None,
) -> TemporalMetadata:
    """Build a validated temporal envelope from raw canonical strings.

    Fails closed on any malformed or timezone-naive value, and on an inverted
    ``valid_from`` / ``valid_until`` interval. It never repairs, reorders, or
    substitutes a value from another dimension.
    """
    metadata = TemporalMetadata(
        created_at=normalize_timestamp("created_at", created_at),
        observed_at=normalize_timestamp("observed_at", observed_at),
        effective_at=normalize_timestamp("effective_at", effective_at),
        valid_from=normalize_timestamp("valid_from", valid_from),
        valid_until=normalize_timestamp("valid_until", valid_until),
        superseded_at=normalize_timestamp("superseded_at", superseded_at),
        ingested_at=normalize_timestamp("ingested_at", ingested_at),
    )
    if metadata.valid_from is not None and metadata.valid_until is not None:
        if metadata.valid_until.as_datetime() < metadata.valid_from.as_datetime():
            raise TemporalError("valid_until", "inverted_validity_interval")
    return metadata


__all__ = [
    "TEMPORAL_CONTRACT_VERSION",
    "TRANSACTION_TIME_FIELDS",
    "VALID_TIME_FIELDS",
    "DIAGNOSTIC_TIME_FIELDS",
    "TemporalError",
    "NormalizedTimestamp",
    "TemporalMetadata",
    "normalize_timestamp",
    "build_temporal_metadata",
]
