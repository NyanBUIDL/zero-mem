# ADR-005: Bounded, Authorization-First Retrieval

**Status:** PROPOSED

**Reconciliation:** RETAINED at exact master 78c4bb46b88b8ce9987c6882b24201e08b82a7f0; the one-commit post-tag delta does not change this ADR's code evidence. The decision remains proposed pending maintainer review.

## Context

Corpus candidate discovery can fetch all rows before Python-side authorization/ranking, and lower-level memory FTS returns chronological rather than context-relevance ordering.

## Decision

V1.1.0 context-facing retrieval will bound candidate discovery, apply authorization as early as the data model safely permits, and expose deterministic ordering/currentness semantics. Fallbacks that cannot be bounded must be explicit and diagnosable.

## Why

This addresses F-008 and F-009 while preserving existing access-policy invariants.

## Consequences

- WP-05 owns query/policy/ordering design.
- WP-06 owns bounded context projection and token behavior.
- WP-16 must measure candidate count, latency, memory, and correctness.

## Rejected Alternatives

- Rely only on final result limits after unbounded candidate materialization.
- Push authorization after context assembly.
