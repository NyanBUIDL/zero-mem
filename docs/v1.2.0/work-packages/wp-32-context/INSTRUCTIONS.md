# WP-32 Instructions

**WP:** WP-32 Context
**Status:** PLANNING
**Dependencies:** WP-29 Authorization VERIFIED; WP-31 Hermes VERIFIED

## Objective

Provide deterministic, bounded context assembly from already-authorized evidence without mandatory LLM/network calls, scope leakage, provenance loss, freshness misrepresentation, or transcript mutation.

## In scope

- deterministic ordering and tie-breaks for authorized EvidenceSet items;
- explicit provenance and freshness metadata preservation;
- deterministic token/byte budget enforcement with whole-item omission or safe truncation;
- stable DATA-only envelope serialization;
- controlled integration with the existing M7/Hermes injection boundary;
- negative, budget, freshness, provenance, and restart regression tests.

## Out of scope

- authorization redesign or retrieve-then-filter behavior;
- new retrieval engines, vector stores, embeddings, or ranking evolution owned by WP-33;
- profile/knowledge-space/Obsidian projection owned by WP-34;
- canonical JSONL or SQLite schema changes;
- Hermes-core modifications;
- mandatory LLM calls.

## Required invariants

- Authorization occurs before candidate selection and context packing.
- `EXTERNAL_CURRENT` is never substituted with stale memory.
- Context is DATA-only and cannot become system/developer/user instruction.
- Provenance, lifecycle, verification, freshness, and source identity survive packing.
- Ordering is deterministic for identical authorized input.
- Context budgets are bounded and client inputs cannot raise governed ceilings.
- Canonical memory is read-only during assembly; no transcript/canonical write-back.
- Missing/stale derived state is represented explicitly, never silently claimed current.

## Allowed changes

WP-32-owned context assembly helpers, tests, bounded serialization metadata, and documentation. Reuse WP-29 authorization, existing M7 contracts/budget/envelope, and WP-31 integration boundaries.

## Prohibited changes

No auth bypass, raw SQL retrieval, new source of truth, unbounded queue/task, hidden fallback, arbitrary scoring weights, destructive migration, secret persistence, or deep Hermes-core edit.

## Escalation conditions

Escalate if the approved contract requires changing authorization order, canonical storage semantics, Hermes trust boundaries, a new dependency/engine, destructive migration, or an unowned scope gap.

## Completion

Planning package validated; focused functional/security/failure tests pass; isolated regression passes; independent fail-closed review passes; final Graphify is run on the local tree; evidence and project state record exact results; status becomes VERIFIED only then.
