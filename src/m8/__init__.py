"""M8 — frozen contracts and derived-index foundation (M8.1).

This package contains ONLY the M8.1 contract freeze and the minimal derived
schema-v9 foundation. It deliberately contains NO graph projection (M8.2), NO
authorization-first traversal (M8.3), NO temporal query behavior (M8.4), NO
calibration scoring (M8.5), and NO M7 EvidenceSet integration (M8.6).

Architectural invariants (AGENTS.md, ARCHITECTURE.md, plan-m8.md §5/§7/§8/§9):

- Canonical storage is append-only JSONL plus versioned artifacts. Every M8
  structure defined here is DERIVED, disposable, and rebuildable. No M8 table
  is canonical truth.
- A derived relation is metadata, never a verified fact. Relation existence,
  node degree, and centrality carry no authority.
- A newer timestamp is not more correct. No recency-wins semantics exist here.
- A calibration score is evidence-ordering metadata. It never grants access,
  verifies a claim, resolves a conflict, or promotes lifecycle.
- M5 remains the sole authorization authority. Nothing in this package makes,
  caches, widens, or infers an access decision.
- `resource_type` identity is preserved end-to-end (permanent M6.6 invariant).
- Zero LLM calls and zero external network calls.
"""

from __future__ import annotations

from typing import Final

#: Frozen contract version for the M8.1 freeze. Bumped only by an approved
#: later increment that changes a frozen contract shape.
M8_CONTRACT_VERSION: Final[str] = "m8.1"

#: Derived SQLite schema version introduced by the M8.1 foundation.
M8_SCHEMA_VERSION: Final[int] = 9

__all__ = ["M8_CONTRACT_VERSION", "M8_SCHEMA_VERSION"]
