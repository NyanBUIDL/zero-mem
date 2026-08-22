"""M7.3 — deterministic evidence budget + token estimation.

No LLM, no network. Whole-item omission preferred over mid-claim truncation.
Stable ordering uses existing trustworthy metadata; no vector/learned scoring.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from .contracts import EvidenceItem, EvidenceRole, MemoryRoute
from .eligibility import EligibilityResult

DEFAULT_MAX_PRIMARY = 5
DEFAULT_MAX_SUPPORTING = 3
# Conservative chars/4 estimator; documented as estimate, not exact token count.
_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Explicit deterministic estimate (~chars/4). Documented as estimate only."""
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _item_text(item: Any) -> str:
    if isinstance(item, tuple):
        item = item[0]  # (EvidenceItem, EligibilityResult)
    parts = [
        str(item.evidence_id), item.resource_type, item.summary or "",
        item.source or "", item.lifecycle or "", item.verification or "",
    ]
    return " ".join(p for p in parts if p)


def _order_key(item: EvidenceItem, elig: EligibilityResult, route: Optional[MemoryRoute] = None) -> Tuple:
    """Stable deterministic ordering: primary first, then (in the PROJECT route only)
    active state records above other resource types, then verified, route-relevant,
    lifecycle strength, then (created_at, evidence_id) tie-break.

    Option B: in the PROJECT route, active M4 ``state`` records (current step / docker
    status) answer "current step / latest state" questions and must not be pushed out of
    the bounded set by same-timestamp decisions. The state-priority rank sits AFTER the
    primary/supporting role split (so the 5-primary / 3-supporting budget is preserved)
    but BEFORE the verified/lifecycle/tie-break ranks, so it applies within each role
    pool without reordering any non-PROJECT route.
    """
    role_rank = 0 if elig.as_primary else 1
    verified_rank = 0 if (item.verification or "").lower() in ("verified", "confirmed") else 1
    lifecycle_rank = 0 if (item.lifecycle or "").lower() == "active" else 1
    state_rank = 0 if (
        route is MemoryRoute.PROJECT
        and item.resource_type == "state"
        and (item.lifecycle or "").lower() == "active"
    ) else 1
    return (role_rank, state_rank, verified_rank, lifecycle_rank,
            item.created_at or "", item.evidence_id or "")


@dataclass
class BudgetSelection:
    primary: List[EvidenceItem]
    supporting: List[EvidenceItem]
    omitted_count: int
    estimated_tokens: int


def select_evidence(
    candidates: List[Tuple[EvidenceItem, EligibilityResult]],
    *,
    max_primary: int = DEFAULT_MAX_PRIMARY,
    max_supporting: int = DEFAULT_MAX_SUPPORTING,
    token_budget: int | None = None,
    route: Optional[MemoryRoute] = None,
) -> BudgetSelection:
    """Deterministic bounded selection. Returns primary/supporting lists, count of
    authorized eligible items omitted by the budget (NOT unauthorized items), and an
    estimated token total.

    `omitted_count` only reflects evidence the requester was already authorized to
    know existed (never leaks protected existence).

    `route` (optional) enables route-conditioned ordering (Option B: PROJECT route
    prioritizes active state records within their role pool). None preserves the
    default ordering for callers that do not carry a route.
    """
    # Split by intended role, then stable-sort each.
    primary_pool = [c for c in candidates if c[1].as_primary]
    supporting_pool = [c for c in candidates if not c[1].as_primary]
    primary_pool.sort(key=lambda c: _order_key(c[0], c[1], route))
    supporting_pool.sort(key=lambda c: _order_key(c[0], c[1], route))

    chosen_primary = primary_pool[:max_primary]
    chosen_supporting = supporting_pool[:max_supporting]

    # Whole-item omission if a token budget is given; prefer dropping a whole item.
    if token_budget is not None:
        kept_p, tok_p = _fit_token_budget(chosen_primary, token_budget, from_tail=True)
        remaining = token_budget - tok_p
        kept_s, tok_s = _fit_token_budget(chosen_supporting, remaining, from_tail=True)
        chosen_primary, chosen_supporting = kept_p, kept_s

    omitted = (len(primary_pool) - len(chosen_primary)) + (len(supporting_pool) - len(chosen_supporting))
    total_tokens = sum(estimate_tokens(_item_text(i)) for i in chosen_primary + chosen_supporting)
    return BudgetSelection(
        primary=[c[0] for c in chosen_primary],
        supporting=[c[0] for c in chosen_supporting],
        omitted_count=omitted,
        estimated_tokens=total_tokens,
    )


def _fit_token_budget(items: List[Tuple[EvidenceItem, EligibilityResult]], budget: int, *, from_tail: bool) -> Tuple[List[Tuple[EvidenceItem, EligibilityResult]], int]:
    """Drop whole items (from the least-important tail) until within budget."""
    ordered = list(items)
    kept: List[Tuple[EvidenceItem, EligibilityResult]] = []
    used = 0
    for c in ordered:
        cost = estimate_tokens(_item_text(c[0]))
        if used + cost > budget and kept:
            break
        kept.append(c)
        used += cost
    return kept, used
