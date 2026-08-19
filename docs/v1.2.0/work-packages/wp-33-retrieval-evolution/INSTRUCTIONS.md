# WP-33 Instructions

**WP:** WP-33 Retrieval Evolution
**Status:** PLANNING
**Dependencies:** WP-32 Context VERIFIED

## Objective

Measure the existing lexical/FTS retrieval baseline, then make only evidence-backed retrieval changes while preserving authorization-before-candidate-discovery, deterministic ordering, temporal correctness, and canonical/derived boundaries.

## Scope

- Define a reproducible labeled benchmark corpus and query set.
- Measure lexical precision/recall and latency/resource behavior at feasible corpus sizes.
- Identify concrete retrieval failure modes.
- Add hybrid/vector retrieval only if measured evidence and dependency/security review justify it.

## Out of scope

- Replacing JSONL canonical truth.
- Adding a vector database or cloud embedding service by default.
- Moving authorization after retrieval.
- Unversioned ranking weights or client-controlled ranking policy.
- Context assembly changes owned by WP-32.

## Required invariants

- Authorization precedes candidate discovery and similarity/ranking.
- Lexical baseline remains available and typed when optional derived indexes are missing/stale.
- Ranking and fusion are deterministic with explicit tie-breaks.
- Derived indexes are rebuildable and never canonical.
- Benchmark claims use measured results only.

## Escalation conditions

Escalate for a new dependency with material operational/security impact, a change to approved ranking semantics, unresolved leakage, or an unowned benchmark/corpus gap.

## Completion

A reproducible benchmark and measured baseline exist; any change is minimal, tested, documented, and independently reviewed; otherwise the lexical baseline may be retained as the verified result.
