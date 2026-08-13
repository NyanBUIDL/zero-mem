"""M8.4 — authorization-first bounded as-of / history temporal reads.

This is the request-time read layer over the derived ``zm_temporal_index``
(M8.4 projection). Authorization is FIRST and mandatory:

    request (authorized seed scope + resource_type)
      -> normalize (resource_type / scope carried verbatim; M6.6 preserved)
      -> M5 authorize SEED  (AuthorizedReadService — sole authority)
      |     denied  -> empty result, no temporal info, no counts
      v
      -> read ONLY the authorized resource's own derived temporal row
      -> pure temporal predicate (as-of / history)
      -> bounded result

No search-then-authorize. A denied resource contributes nothing: no row, no
count, no earliest/latest timestamp, no revision count, no bound. Unauthorized
history does not exist as far as the result is concerned.

Temporal semantics (docs/plans/plan-m8.md §340, §342–§364):

- **Transaction / history time** = ``created_at`` — when the system recorded
  the resource. This is the ``transaction`` temporal dimension.
- **Valid / effective time** = ``effective_at`` / ``valid_from``–``valid_until``
  — explicit source declarations only. This is the ``valid`` temporal
  dimension. The two are NEVER silently conflated.

Bounded reads only:

- As-of returns at most ``MAX_HISTORY_VERSIONS`` facts from the resource's own
  derived temporal row (bounded; the resource is a single derived row, so a
  single fact normally, but the bound is enforced as policy).
- History is likewise bounded by ``MAX_HISTORY_VERSIONS`` and an optional
  temporal window.

No invented timestamps. Unknown time stays unknown; NULL is never treated as
epoch or infinity. Malformed request timestamps fail closed via the M8.1
temporal contract.

M4 lifecycle / supersession / conflict semantics remain authoritative. This
module never promotes an assistant claim, never resolves a conflict, never
selects truth by recency, and never derives supersession from a newer
timestamp. Explicit M4 supersession references are surfaced verbatim under
authorization as provenance, never as an authority decision.

Zero LLM. Zero network. No authorization decision is made here — the M5
``AuthorizedReadService`` is the sole authority and is *used*, never bypassed
or reimplemented.

The only sanctioned M8 consumer of ``src.access`` (alongside M8.3's
``graph_access.py``), per the same authorization-first contract that exempted
``graph_access.py`` from the M8.1 freeze.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Final, Mapping, Optional, Sequence, Tuple

from .temporal_contract import TemporalError, normalize_timestamp
from .temporal_projection import (
    PROJECTION_VERSION,
    TEMPORAL_TABLE,
    describe_temporal_projection,
)
from .vocabulary import RESOURCE_TYPES, validate_resource_type

# Sanctioned M5 imports — the sole authorization authority for temporal reads.
from src.access import AccessRequest, AuthorizedReadService
from src.access.contracts import READ

#: Bounded temporal read limits (docs/plans/plan-m8.md §7: "maximum historical versions
#: per resource for an as-of response: 20"). These are module constants and not
#: negotiable; any caller-supplied value above the ceiling fails closed.
MAX_HISTORY_VERSIONS: Final[int] = 20

#: The only authorization descriptor this read layer produces.
TEMPORAL_DESCRIPTOR = "m8_temporal_read"


class TemporalReadError(RuntimeError):
    """Sanitized temporal-read failure. Never contains raw SQL/payloads."""

    def __init__(self, reason: str, detail: str = "") -> None:
        message = f"temporal_read_error: {reason}"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)
        self.reason = reason


# Closed temporal dimension vocabulary (docs/plans/plan-m8.md §340). No other dimension is
# invented.
class TemporalDimension(str):
    TRANSACTION = "transaction"   # created_at
    VALID = "valid"               # effective_at / valid_from–valid_until

    @classmethod
    def validate(cls, value: str) -> str:
        if value not in (cls.TRANSACTION, cls.VALID):
            raise TemporalReadError("unknown_temporal_dimension", str(value)[:48])
        return value


@dataclass(frozen=True)
class TemporalReadRequest:
    """A typed, bounded temporal read request.

    ``requester`` is the profile performing the read (authorization subject).
    ``resource_type`` / ``resource_id`` identify the seed - only this resource's
    own derived temporal row is read. ``requesting_profile_id`` is forwarded to
    M5 verbatim (never inferred). ``project_id`` / ``knowledge_space_id`` are the
    explicit scope the caller asserts (mirrors M8.3's seed authorization); M5
    re-validates them, never trusts the caller. ``scope`` is an optional
    pre-built M5 ``AllowedScope``; when ``None`` the service composes the
    effective scope from the explicit project/space identifiers.
    """

    requester: str
    resource_type: str
    resource_id: str
    requesting_profile_id: Optional[str]
    project_id: Optional[str] = None
    knowledge_space_id: Optional[str] = None
    scope: Optional[Any] = None
    dimension: str = TemporalDimension.TRANSACTION
    as_of: Optional[str] = None
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    limit: int = MAX_HISTORY_VERSIONS

    def __post_init__(self) -> None:
        validate_resource_type(self.resource_type)
        if self.resource_type not in RESOURCE_TYPES:
            raise TemporalReadError("unknown_resource_type", self.resource_type)
        TemporalDimension.validate(self.dimension)
        # Caller may only TIGHTEN the bound, never widen it.
        if self.limit > MAX_HISTORY_VERSIONS:
            raise TemporalReadError("limit_exceeds_bound", str(self.limit))
        if self.limit < 1:
            raise TemporalReadError("limit_below_one", str(self.limit))
        # Validate request timestamps through the M8.1 contract; malformed
        # values fail closed rather than being normalized away.
        for name, value in (
            ("as_of", self.as_of),
            ("window_start", self.window_start),
            ("window_end", self.window_end),
        ):
            if value is not None:
                normalize_timestamp(name, value)
        if (self.window_start and self.window_end) and (
            normalize_timestamp("window_start", self.window_start).compare(
                normalize_timestamp("window_end", self.window_end)) > 0
        ):
            raise TemporalReadError("inverted_window",
                                    f"{self.window_start} > {self.window_end}")


@dataclass(frozen=True)
class TemporalReadResult:
    """A bounded, authorized temporal read result.

    When the seed is denied, every field is empty/absent and ``authorized`` is
    ``False``. No existence leak: denied rows contribute no metadata whatsoever.
    """

    authorized: bool
    resource_type: str
    resource_id: str
    dimension: str
    limit: int
    # Ordered temporal facts (always bounded by ``limit``).
    facts: Tuple[Mapping[str, Any], ...]
    # Deterministic provenance from the authorized row only.
    provenance: Mapping[str, Any]
    # Set when the bound was hit (result truncated by policy, not by existence).
    bound_code: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorized": self.authorized,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "dimension": self.dimension,
            "limit": self.limit,
            "facts": [dict(f) for f in self.facts],
            "provenance": dict(self.provenance),
            "bound_code": self.bound_code,
        }


# ---------------------------------------------------------------------------
# Pure temporal predicates
# ---------------------------------------------------------------------------

def _known_or_fail(ts: Optional[str]) -> Any:
    """Return a normalized ``datetime``, failing closed on malformed input.

    ``None`` (unknown time) is returned as ``None`` — never epoch, never
    infinity. Known values are the M8.1 canonical UTC form.
    """
    if ts is None:
        return None
    return normalize_timestamp("temporal_predicate", ts).as_datetime()


def _as_of_dimension_value(fact: Mapping[str, Any], dimension: str) -> Optional[str]:
    """Pick the explicit temporal field for the requested dimension.

    Transaction dimension -> ``created_at``. Valid dimension ->
    ``effective_at`` (or ``valid_from`` when no explicit effective_at exists,
    i.e. the earliest declared valid boundary). ``None`` means the resource has
    no known time on that dimension — unknown time stays unknown.
    """
    if dimension == TemporalDimension.TRANSACTION:
        return fact.get("created_at")
    # Valid dimension: prefer explicit effective_at, else valid_from boundary.
    eff = fact.get("effective_at")
    if eff is not None:
        return eff
    return fact.get("valid_from")


def as_of_match(fact: Mapping[str, Any], dimension: str, when: str) -> bool:
    """Pure predicate: is the fact valid/known at instant ``when``?

    Boundary semantics (inclusive lower, exclusive upper), matching the
    ``valid_from`` <= t < ``valid_until`` envelope and the transaction-time
    point ``created_at <= when`` for "known at" semantics:

    - transaction dimension: the resource is *known* at ``when`` iff
      ``created_at`` is known and ``created_at <= when``. A resource with
      unknown created_at never matches (unknown != epoch).
    - valid dimension: the resource is *valid* at ``when`` iff the explicit
      valid envelope covers it: ``valid_from <= when < valid_until``. Open
      lower bound (``valid_from`` is NULL) means "valid from the dawn of known
      time" -> lower satisfied. Open upper bound (``valid_until`` is NULL)
      means "valid indefinitely" -> upper satisfied. If the resource has NO
      explicit valid time at all, it does NOT match a valid-dimension as-of
      (valid time is unknown; we refuse to invent it).

    The two dimensions are never conflated: a transaction match does not imply
    a valid match and vice-versa.
    """
    when_i = _known_or_fail(when)
    if dimension == TemporalDimension.TRANSACTION:
        ca = fact.get("created_at")
        if ca is None:
            return False
        return _known_or_fail(ca) <= when_i
    # Valid dimension.
    eff = fact.get("effective_at")
    vf = fact.get("valid_from")
    vu = fact.get("valid_until")
    if eff is not None:
        # A point valid-time declaration: valid exactly at its instant.
        return _known_or_fail(eff) == when_i
    if vf is None and vu is None:
        # No explicit valid time: refuse to invent coverage.
        return False
    if vf is not None and _known_or_fail(vf) > when_i:
        return False
    if vu is not None and _known_or_fail(vu) <= when_i:
        return False
    return True


def within_window(fact: Mapping[str, Any], dimension: str,
                  start: Optional[str], end: Optional[str]) -> bool:
    """Pure predicate: does the fact's dimension value fall in [start, end)?

    ``None`` start => open lower bound. ``None`` end => open upper bound.
    A fact with unknown time on the dimension never falls in any explicit
    window (unknown is not min/max).
    """
    value = _as_of_dimension_value(fact, dimension)
    if value is None:
        return False
    v = _known_or_fail(value)
    if start is not None and v < _known_or_fail(start):
        return False
    if end is not None and v >= _known_or_fail(end):
        return False
    return True


# ---------------------------------------------------------------------------
# Authorization-first read
# ---------------------------------------------------------------------------

def _authorize_seed(
    service: AuthorizedReadService,
    requester: str,
    resource_type: str,
    resource_id: str,
    requesting_profile_id: Optional[str],
    project_id: Optional[str],
    knowledge_space_id: Optional[str],
    scope: Optional[Any],
) -> bool:
    """Authorize the SEED before any temporal read, via M5 solely.

    Mirrors the M8.3 authorization-first pattern exactly: build a typed
    ``AccessRequest`` and route it through the ``AuthorizedReadService`` facade,
    which composes the effective scope from persistent canonical grants (M5.4)
    and the base policy (M5.1). Returns True only when M5 grants read access to
    this exact (resource_type, resource_id) under the requester's effective
    scope. A deny yields no temporal metadata whatsoever.
    """
    ar = AccessRequest(
        operation=READ,
        requesting_profile_id=requesting_profile_id,
        project_ids=[project_id] if project_id is not None else None,
        knowledge_space_ids=(
            [knowledge_space_id] if knowledge_space_id is not None else None),
        resource_type=resource_type,
        resource_id=resource_id,
    )
    if resource_type in ("artifact", "project_artifact"):
        res = service.m4_artifacts(ar, project_id or "")
    elif resource_type == "decision":
        res = service.m4_decisions(ar, project_id or "")
    elif resource_type == "requirement":
        res = service.m4_requirements(ar, project_id or "")
    elif resource_type == "verification":
        res = service.m4_verifications(ar, project_id or "")
    else:  # event
        res = service.get_event(ar, resource_id)
    return (not getattr(res, "denied", True)) and bool(getattr(res, "items", []))


def read_temporal(
    conn: sqlite3.Connection,
    service: AuthorizedReadService,
    request: TemporalReadRequest,
) -> TemporalReadResult:
    """Authorization-first bounded temporal read.

    Authorization occurs BEFORE any derived row is read. On deny, the result is
    empty and exposes no temporal metadata (no count, no earliest/latest, no
    bound, no existence). On allow, only the seed's own derived temporal row is
    read and filtered by the explicit temporal predicate.
    """
    TemporalDimension.validate(request.dimension)

    authorized = _authorize_seed(
        service, request.requester, request.resource_type, request.resource_id,
        request.requesting_profile_id, request.project_id,
        request.knowledge_space_id, request.scope,
    )
    if not authorized:
        return TemporalReadResult(
            authorized=False,
            resource_type=request.resource_type,
            resource_id=request.resource_id,
            dimension=request.dimension,
            limit=request.limit,
            facts=(),
            provenance={},
            bound_code=None,
        )

    row = conn.execute(
        f"SELECT resource_type, resource_id, created_at, observed_at, "
        f"effective_at, valid_from, valid_until, superseded_at, "
        f"lifecycle_status, verification_status, profile_id, project_id, "
        f"knowledge_space_id, source_event_id, trace_id, provenance_hash "
        f"FROM {TEMPORAL_TABLE} "
        f"WHERE resource_type=? AND resource_id=?",
        (request.resource_type, request.resource_id),
    ).fetchone()
    if row is None:
        # Authorized but no derived temporal row: report the empty authorized
        # result without leaking anything about other resources.
        return TemporalReadResult(
            authorized=True,
            resource_type=request.resource_type,
            resource_id=request.resource_id,
            dimension=request.dimension,
            limit=request.limit,
            facts=(),
            provenance={
                "profile_id": None, "project_id": None,
                "knowledge_space_id": None, "source_event_id": None,
                "trace_id": None,
            },
            bound_code=None,
        )

    fact = {
        "resource_type": row["resource_type"],
        "resource_id": row["resource_id"],
        "created_at": row["created_at"],
        "observed_at": row["observed_at"],
        "effective_at": row["effective_at"],
        "valid_from": row["valid_from"],
        "valid_until": row["valid_until"],
        "superseded_at": row["superseded_at"],
        "lifecycle_status": row["lifecycle_status"],
        "verification_status": row["verification_status"],
    }

    facts: list[Mapping[str, Any]] = []
    if request.as_of is not None:
        if as_of_match(fact, request.dimension, request.as_of):
            facts.append(fact)
    elif request.window_start is not None or request.window_end is not None:
        if within_window(fact, request.dimension,
                         request.window_start, request.window_end):
            facts.append(fact)
    else:
        # No temporal predicate: return the single authorized derived row
        # (bounded to the limit). This is the "current bounded view", never an
        # unbounded history dump.
        facts.append(fact)

    # Bound enforcement (deterministic truncation; the resource is a single
    # derived row so normally 0 or 1 facts, but the limit is honored as policy).
    bound_code: Optional[str] = None
    if len(facts) > request.limit:
        facts = facts[: request.limit]
        bound_code = "temporal_limit"

    provenance = {
        "profile_id": row["profile_id"],
        "project_id": row["project_id"],
        "knowledge_space_id": row["knowledge_space_id"],
        "source_event_id": row["source_event_id"],
        "trace_id": row["trace_id"],
        "provenance_hash": row["provenance_hash"],
    }
    return TemporalReadResult(
        authorized=True,
        resource_type=request.resource_type,
        resource_id=request.resource_id,
        dimension=request.dimension,
        limit=request.limit,
        facts=tuple(facts),
        provenance=provenance,
        bound_code=bound_code,
    )


def describe_temporal_read() -> dict[str, Any]:
    """Introspectable description of the M8.4 temporal read layer."""
    return {
        "projection_version": PROJECTION_VERSION,
        "schema_version": 10,
        "source_table": TEMPORAL_TABLE,
        "derived": True,
        "authorization_first": True,
        "authorization_authority": "src.access.authorized_read.AuthorizedReadService",
        "temporal_dimensions": [TemporalDimension.TRANSACTION, TemporalDimension.VALID],
        "max_history_versions": MAX_HISTORY_VERSIONS,
        "invents_no_timestamp": True,
        "makes_authorization_decisions": False,
        "resolves_conflicts": False,
        "promotes_assistant_claim": False,
        "recency_is_not_authority": True,
    }


__all__ = [
    "MAX_HISTORY_VERSIONS",
    "TEMPORAL_DESCRIPTOR",
    "TemporalReadError",
    "TemporalDimension",
    "TemporalReadRequest",
    "TemporalReadResult",
    "as_of_match",
    "within_window",
    "read_temporal",
    "describe_temporal_read",
    "describe_temporal_projection",
]
