"""M9.2 — sensitivity + lifecycle eligibility for projection.

A single deterministic predicate over a record's OWN fields. It consults no
neighboring records, no recency, no calibration score, no graph centrality, no
assistant claim, and no request/memory text. That is what makes it immune to
unauthorized data and hostile prompt content (prompt §3, §4, §7.1, §15).

The closed vocabularies are imported from the VERIFIED M9.1 layer
(``src.projection.contracts``) and the M6.6 source of truth
(``src.m8.vocabulary.RESOURCE_TYPES``). This module adds only the eligibility
policy, not a new vocabulary.

Fail-closed rules (prompt §4):

* unknown/malformed ``sensitivity``  -> not eligible (fail closed);
* unknown/malformed ``ceiling``       -> not eligible (fail closed);
* memory/request text can NEVER raise the ceiling.

Default projection ceiling is ``internal`` (intentionally different from the M7
retrieval default ``private``): ``public`` and ``internal`` material is
eligible; ``private`` is excluded by default; ``secret`` is NEVER projected under
any ceiling.

Note: the sensitivity gate delegates to the VERIFIED M9.1 predicate
``is_projectable_sensitivity``, which already implements the secret/exclusion
and fail-closed ceiling behavior; this module adds only the lifecycle gate and
the resource-type guard.
"""

from __future__ import annotations

from typing import Final, Iterable

from src.m8.vocabulary import RESOURCE_TYPES
from src.project_memory.contracts import is_safe_reference

from .contracts import (
    DEFAULT_PROJECTION_SENSITIVITY_CEILING,
    is_projectable_sensitivity,
    validate_sensitivity_ceiling,
)

#: Lifecycle states that are PROJECTED (owner-approved policy, plan-m9.md §4).
#: ``raw``/``observed``/``candidate`` are excluded from generated projection.
#: ``deleted`` must never appear as current/active projected truth.
PROJECTED_LIFECYCLE: Final[set[str]] = {
    "confirmed", "active", "superseded", "conflicted", "archived",
}

#: Lifecycle states excluded from the generated projection entirely.
EXCLUDED_LIFECYCLE: Final[set[str]] = {"raw", "observed", "candidate", "deleted"}


def default_ceiling() -> str:
    """The M9 default projection ceiling (``internal``)."""
    return DEFAULT_PROJECTION_SENSITIVITY_CEILING


def is_authorized_resource_type(resource_type: str, ceiling: str) -> bool:
    """True only when ``resource_type`` is a known M6.6 type and ``ceiling`` is a

    known sensitivity ceiling. Unknown/malformed values fail closed (return
    False); the engine treats a non-OK ceiling as a hard stop.
    """
    if not isinstance(resource_type, str) or resource_type not in RESOURCE_TYPES:
        return False
    try:
        validate_sensitivity_ceiling(ceiling)
    except Exception:
        return False
    return True


#: Sentinel for "the record does not carry this dimension at all". It is kept
#: strictly distinct from "the record carries a value we cannot parse": the
#: former is a known property of the sensitivity-agnostic M4 substrate, the
#: latter is exactly the unknown/unparseable case plan-m9.md §11.2 requires to
#: fail closed. Collapsing the two is a fail-open hole.
_ABSENT: Final[object] = object()


def _sensitivity_of(record) -> object:
    """``_ABSENT`` when the dimension is not carried; the RAW value otherwise.

    A malformed value (non-string) is returned verbatim rather than folded to
    ``None``, so :func:`is_eligible` can reject it instead of mistaking it for
    an absent field.
    """
    raw = getattr(record, "sensitivity", _ABSENT)
    if raw is _ABSENT or raw is None:
        return _ABSENT
    return raw


def _lifecycle_of(record) -> object:
    """``_ABSENT`` when the dimension is not carried; the RAW value otherwise."""
    raw = getattr(record, "lifecycle_status", _ABSENT)
    if raw is _ABSENT or raw is None:
        return _ABSENT
    return raw


def is_eligible(record, *, ceiling: str, resource_type: str) -> bool:
    """Eligibility predicate over one authorized record.

    Authorization (M5) has already admitted the record; this answers only
    "should a record of this sensitivity and lifecycle be rendered at this
    ceiling?".

    Sensitivity gate (fail closed on any value the record actually CARRIES):
      * a record that CARRIES a sensitivity value is checked; ``secret``,
        above-ceiling, unknown, AND malformed (non-string) values are all
        excluded. A malformed value is unparseable, and an unparseable
        sensitivity is exactly the case plan-m9.md §11.2 requires to fail
        closed — it is never treated as "no sensitivity";
      * a record that carries NO sensitivity field (the M4 project-memory
        substrate is sensitivity-agnostic and does not persist per-record
        sensitivity) is NOT excluded on that basis — failing closed here would
        empty the entire projection. The content-level secret-pattern scan in
        the engine is the backstop for secret-shaped material that reaches the
        derived substrate (e.g. a verification's observed_result).
    Lifecycle gate (fail closed on malformed): ``raw``/``observed``/``candidate``/
    ``deleted`` excluded; a carried non-string lifecycle is unparseable and is
    excluded; M9 never promotes or changes lifecycle state.
    """
    if not is_authorized_resource_type(resource_type, ceiling):
        return False

    sensitivity = _sensitivity_of(record)
    if sensitivity is not _ABSENT:
        if not isinstance(sensitivity, str):
            return False  # carried but unparseable -> fail closed
        if not is_projectable_sensitivity(sensitivity, ceiling=ceiling):
            return False

    lifecycle = _lifecycle_of(record)
    if lifecycle is not _ABSENT:
        if not isinstance(lifecycle, str):
            return False  # carried but unparseable -> fail closed
        if lifecycle in EXCLUDED_LIFECYCLE:
            return False
        if lifecycle not in PROJECTED_LIFECYCLE:
            return False

    return True


def eligible_records(records: Iterable[object], *,
                     ceiling: str,
                     resource_type: str) -> tuple[object, ...]:
    """Filter an iterable of authorized records by eligibility only.

    Deterministic and side-effect free. Output preserves input order; the engine
    re-sorts for final stability.
    """
    return tuple(
        record for record in records if is_eligible(record, ceiling=ceiling,
                                                    resource_type=resource_type)
    )


def safe_artifact_refs(record) -> tuple[str, ...]:
    """Artifact references passing the VERIFIED M4 safe-reference guard.

    An absolute path, a traversal fragment, a raw transcript, or a
    secret-shaped value never reaches the vault as a reference (plan-m9.md
    §11.3.3). Reuses ``is_safe_reference`` rather than reimplementing it.
    """
    raw = getattr(record, "linked_artifact_ids", None)
    if not raw:
        return ()
    return tuple(ref for ref in str(raw).split(",") if is_safe_reference(ref))


__all__ = [
    "RESOURCE_TYPES",
    "default_ceiling",
    "PROJECTED_LIFECYCLE",
    "EXCLUDED_LIFECYCLE",
    "is_authorized_resource_type",
    "is_eligible",
    "eligible_records",
    "safe_artifact_refs",
]
