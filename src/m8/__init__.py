"""M8 — frozen contracts and derived-index foundation (M8.1) plus later increments.

M8.1 owns the contract freeze and the minimal derived schema-v9 foundation.
M8.2 projects the deterministic graph. M8.3 adds the authorization-first
bounded graph read layer (INTERNAL; not a new Hermes/M6 tool surface). M8.4
(temporal), M8.5 (calibration), and M8.6 (EvidenceSet integration) are NOT
implemented here yet.

Architectural invariants (AGENTS.md, docs/architecture/ARCHITECTURE.md, docs/plans/plan-m8.md §5/§7/§8/§9):

- Canonical storage is append-only JSONL plus versioned artifacts. Every M8
  structure defined here is DERIVED, disposable, and rebuildable. No M8 table
  is canonical truth.
- A derived relation is metadata, never a verified fact. Relation existence,
  node degree, and centrality carry no authority.
- A newer timestamp is not more correct. No recency-wins semantics exist here.
- A calibration score is evidence-ordering metadata. It never grants access,
  verifies a claim, resolves a conflict, or promotes lifecycle.
- M5 remains the sole authorization authority. Nothing in this package makes,
  caches, widens, or infers an access decision (M8.3 re-checks M5 at every
  traversal step).
- `resource_type` identity is preserved end-to-end (permanent M6.6 invariant).
- Zero LLM calls and zero external network calls.
"""

from __future__ import annotations

from typing import Final

#: Frozen contract version for the M8.1 freeze. Bumped only by an approved
#: later increment that changes a frozen contract shape.
M8_CONTRACT_VERSION: Final[str] = "m8.1"

#: Derived SQLite schema version. M8.1 introduced the schema-v9 foundation;
#: M10.4 (migrate_10) extends the derived store to v10 (additive corpus tables)
#: without altering any M8.1 structure. This tracks the current derived schema
#: version the M8 contracts are coherent with.
M8_SCHEMA_VERSION: Final[int] = 10

__all__ = ["M8_CONTRACT_VERSION", "M8_SCHEMA_VERSION"]
