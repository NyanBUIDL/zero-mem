"""M9.3 — deterministic grouping of AUTHORIZED conflicted records.

M4 is the sole conflict authority. This module does not *detect* conflicts: it
groups records that M4 already marked ``lifecycle_status='conflicted'`` so the
projection can present them together. Nothing here creates, resolves, ranks, or
scores a conflict (docs/plans/plan-m9.md §19).

The distinction that makes this honest:

* a **conflict** is two or more unresolved positions M4 recorded as conflicted;
* a **supersession** is an explicit authoritative replacement relationship.

They are never collapsed into one another. A superseded record is history with a
recorded successor; a conflicted record is a live disagreement with no winner.

**Grouping is a presentation join over an explicit canonical key, not an
inference.** Two decisions group only when M4 gave them the same non-null
``decision_key`` within the same project and scope — the very key M4's
active-uniqueness constraint uses, which is what made them a conflict in the
first place. A record whose key is NULL is deliberately never joined to anything
(M4 treats NULL keys as non-colliding), so it is presented as its own single-
position group rather than being merged with an unrelated record on a guess.

**Zero-influence, structurally.** The input to this module is the already-
authorized, already-eligible record set. A hidden position is not in that set,
so it cannot appear in a group, change a group's size, change a group's key,
change the ordering of positions, or cause a group to exist at all. Counts are
computed from the authorized list alone, so no aggregate can imply a hidden
sibling.

Pure functions over plain records. No store, no authorization, no filesystem,
no wall clock, zero LLM calls, zero network calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Final, List, Optional, Sequence, Tuple

from .contracts import ProjectionVocabularyError, validate_resource_type

#: The authoritative lifecycle value that marks an unresolved conflict. It is
#: read verbatim from M4; nothing in projection may assign it.
CONFLICTED_LIFECYCLE: Final[str] = "conflicted"

#: Grouping key used when a record carries no explicit canonical conflict key.
#: Such a record is grouped ALONE (the key is made unique by its own identity),
#: mirroring M4's rule that NULL keys never collide.
_UNKEYED: Final[str] = "\x00unkeyed"


def _attribute(record: Any, name: str) -> Any:
    return getattr(record, name, None)


def _text(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def is_conflicted(record: Any) -> bool:
    """True iff M4 recorded this record as conflicted. Never inferred."""
    return _attribute(record, "lifecycle_status") == CONFLICTED_LIFECYCLE


def _record_identity(record: Any, resource_type: str) -> Optional[str]:
    """The record's own canonical identifier for its resource type."""
    field = {
        "decision": "decision_id",
        "requirement": "requirement_id",
        "state": "state_key",
        "charter": "charter_id",
        "verification": "verification_id",
    }.get(resource_type)
    if field is None:
        return None
    return _text(_attribute(record, field))


def _conflict_key(record: Any, resource_type: str) -> str:
    """The explicit canonical key positions are grouped by.

    ONLY explicit M4 fields participate: the decision's ``decision_key``, or a
    project state's ``state_key``, each qualified by project and scope. There is
    no similarity match, no title comparison, no timestamp bucket, and no
    embedding — grouping is a join on a recorded key or it does not happen.
    """
    project = _text(_attribute(record, "project_id")) or ""
    scope = _text(_attribute(record, "scope")) or ""
    explicit: Optional[str] = None
    if resource_type == "decision":
        explicit = _text(_attribute(record, "decision_key"))
    elif resource_type == "state":
        explicit = _text(_attribute(record, "state_key"))
    if explicit is None:
        # Unkeyed: grouped alone, qualified by its own identity so it can never
        # be merged with another unkeyed record.
        identity = _record_identity(record, resource_type) or ""
        return f"{resource_type}|{project}|{scope}|{_UNKEYED}|{identity}"
    return f"{resource_type}|{project}|{scope}|{explicit}"


@dataclass(frozen=True)
class ConflictGroup:
    """One unresolved conflict: every AUTHORIZED position, no winner.

    ``positions`` is ordered deterministically by canonical identifier, NOT by
    recency, insertion order, calibration, score, or list position — an ordering
    that implied precedence would be a resolution by presentation. Position
    order carries no meaning and the renderer says so explicitly.
    """

    resource_type: str
    project_id: Optional[str]
    conflict_key: str
    display_key: Optional[str]
    positions: Tuple[Any, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "resource_type", validate_resource_type(self.resource_type)
        )
        if not isinstance(self.conflict_key, str) or not self.conflict_key:
            raise ProjectionVocabularyError("conflict_key")
        if not self.positions:
            raise ProjectionVocabularyError("conflict_positions")

    @property
    def position_count(self) -> int:
        """Number of AUTHORIZED positions. Never a total, never a hidden count."""
        return len(self.positions)


def group_conflicts(records: Sequence[Any], *,
                    resource_type: str) -> Tuple[ConflictGroup, ...]:
    """Group already-authorized conflicted records into deterministic groups.

    Only records M4 marked ``conflicted`` participate; every other record is
    ignored entirely (it is not a conflict, and projection must not turn it into
    one). Groups and the positions inside them are sorted by canonical
    identifier, so reversing the input produces byte-identical output.
    """
    validated_type = validate_resource_type(resource_type)
    buckets: Dict[str, List[Any]] = {}
    for record in records:
        if not is_conflicted(record):
            continue
        buckets.setdefault(_conflict_key(record, validated_type), []).append(record)

    groups: List[ConflictGroup] = []
    for key in sorted(buckets):
        positions = sorted(
            buckets[key],
            key=lambda item: (
                _record_identity(item, validated_type) or "",
                # Second component only breaks an exact-identity tie so the sort
                # is total; it never expresses precedence between positions.
                _text(_attribute(item, "source_event_id")) or "",
            ),
        )
        first = positions[0]
        display = None
        if validated_type == "decision":
            display = _text(_attribute(first, "decision_key"))
        elif validated_type == "state":
            display = _text(_attribute(first, "state_key"))
        groups.append(
            ConflictGroup(
                resource_type=validated_type,
                project_id=_text(_attribute(first, "project_id")),
                conflict_key=key,
                display_key=display,
                positions=tuple(positions),
            )
        )
    return tuple(groups)


def conflict_resource_id(group: ConflictGroup) -> str:
    """Stable canonical identifier for a conflict group's own note.

    Derived from the explicit grouping key, so the Conflict note's identity is
    reproducible across runs and independent of which position happens to sort
    first. It contains no hidden material because the key is built from the
    authorized positions' explicit canonical fields only.
    """
    if not isinstance(group, ConflictGroup):
        raise ProjectionVocabularyError("conflict_group")
    return group.conflict_key


__all__ = [
    "CONFLICTED_LIFECYCLE",
    "ConflictGroup",
    "is_conflicted",
    "group_conflicts",
    "conflict_resource_id",
]
