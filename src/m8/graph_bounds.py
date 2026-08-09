"""M8.3 — frozen traversal bounds for authorization-first graph reads.

The values here are the EXACT defaults approved in plan-m8.md §7 ("Bounds and
cycles"). They are fixed ceilings, not caller-negotiable suggestions:

===============================  =====  ==================================
bound                            value  plan-m8.md wording
===============================  =====  ==================================
``MAX_TRAVERSAL_DEPTH``              2  maximum traversal depth: 2 relation
                                        hops
``MAX_FAN_OUT_PER_NODE``            20  maximum outgoing/incoming fan-out
                                        per authorized node: 20
``MAX_RESULT_NODES``                40  maximum returned graph nodes: 40
``MAX_RESULT_EDGES``                80  maximum returned edges: 80
``MAX_EXPANSIONS_PER_REQUEST``       1  maximum graph expansion attempts per
                                        request: 1 bounded expansion
===============================  =====  ==================================

A caller may NARROW a bound (ask for depth 1 instead of 2). A caller may never
widen one: a value above the fixed ceiling, a non-integer, or a negative value
is a contract violation and fails closed rather than being clamped silently.
Clamping a too-large request would hide a caller that believes it is getting an
unbounded read.

The historical-version bound from the same plan section (20 versions per
resource for an as-of response) is deliberately ABSENT: it belongs to M8.4
temporal reads, and M8.3 implements no temporal query behavior.

Bound-reached codes are sanitized, fixed strings. They are computed from
AUTHORIZED material only — an unauthorized node or edge can never cause a bound
code to appear, because unauthorized material is removed before any budget is
consumed (see :mod:`src.m8.graph_access`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

#: Maximum relation hops from the seed. Depth 0 returns the authorized seed only.
MAX_TRAVERSAL_DEPTH: Final[int] = 2

#: Maximum AUTHORIZED neighbours expanded per node, per direction.
MAX_FAN_OUT_PER_NODE: Final[int] = 20

#: Maximum nodes in one result.
MAX_RESULT_NODES: Final[int] = 40

#: Maximum edges in one result.
MAX_RESULT_EDGES: Final[int] = 80

#: One bounded expansion per request. There is no retry, no re-expansion, and
#: no "widen and try again" path.
MAX_EXPANSIONS_PER_REQUEST: Final[int] = 1

#: Sanitized bound-reached codes. They state that a FIXED limit stopped an
#: authorized expansion. They never carry a count of withheld material.
BOUND_MAX_DEPTH: Final[str] = "bound_max_depth"
BOUND_MAX_FAN_OUT: Final[str] = "bound_max_fan_out"
BOUND_MAX_NODES: Final[str] = "bound_max_nodes"
BOUND_MAX_EDGES: Final[str] = "bound_max_edges"

BOUND_CODES: Final[tuple[str, ...]] = (
    BOUND_MAX_DEPTH,
    BOUND_MAX_EDGES,
    BOUND_MAX_FAN_OUT,
    BOUND_MAX_NODES,
)


class GraphBoundsError(ValueError):
    """Sanitized bounds-contract violation.

    Names the offending bound and a stable reason code. It never echoes graph
    content, SQL, or caller payload.
    """

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"graph_bounds_error: {reason}: {field}")
        self.field = field
        self.reason = reason


def _validate_bound(value: Any, field: str, ceiling: int, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GraphBoundsError(field, "not_an_integer")
    if value < minimum:
        raise GraphBoundsError(field, "below_minimum")
    if value > ceiling:
        # Fail closed instead of clamping: a caller asking for more than the
        # approved ceiling must be told, not quietly served a smaller read.
        raise GraphBoundsError(field, "exceeds_fixed_ceiling")
    return value


@dataclass(frozen=True)
class GraphReadBounds:
    """Effective bounds for one graph read. Immutable and always validated."""

    max_depth: int = MAX_TRAVERSAL_DEPTH
    max_fan_out: int = MAX_FAN_OUT_PER_NODE
    max_nodes: int = MAX_RESULT_NODES
    max_edges: int = MAX_RESULT_EDGES

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_depth",
            _validate_bound(self.max_depth, "max_depth", MAX_TRAVERSAL_DEPTH, minimum=0),
        )
        object.__setattr__(
            self,
            "max_fan_out",
            _validate_bound(
                self.max_fan_out, "max_fan_out", MAX_FAN_OUT_PER_NODE, minimum=1
            ),
        )
        object.__setattr__(
            self,
            "max_nodes",
            _validate_bound(self.max_nodes, "max_nodes", MAX_RESULT_NODES, minimum=1),
        )
        object.__setattr__(
            self,
            "max_edges",
            _validate_bound(self.max_edges, "max_edges", MAX_RESULT_EDGES, minimum=0),
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "max_depth": self.max_depth,
            "max_edges": self.max_edges,
            "max_fan_out": self.max_fan_out,
            "max_nodes": self.max_nodes,
        }


#: The approved defaults, as a ready-made instance.
DEFAULT_BOUNDS: Final[GraphReadBounds] = GraphReadBounds()


__all__ = [
    "MAX_TRAVERSAL_DEPTH",
    "MAX_FAN_OUT_PER_NODE",
    "MAX_RESULT_NODES",
    "MAX_RESULT_EDGES",
    "MAX_EXPANSIONS_PER_REQUEST",
    "BOUND_MAX_DEPTH",
    "BOUND_MAX_FAN_OUT",
    "BOUND_MAX_NODES",
    "BOUND_MAX_EDGES",
    "BOUND_CODES",
    "GraphBoundsError",
    "GraphReadBounds",
    "DEFAULT_BOUNDS",
]
