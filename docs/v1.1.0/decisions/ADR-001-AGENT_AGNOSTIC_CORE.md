# ADR-001: Agent-Agnostic Core and Explicit Runtime Ownership

**Status:** PROPOSED

**Reconciliation:** RETAINED at exact master 78c4bb46b88b8ce9987c6882b24201e08b82a7f0; the one-commit post-tag delta does not change this ADR's code evidence. The decision remains proposed pending maintainer review.

## Context

V1.0.0 exposes operational behavior through internal modules and uses mutable process-global runtime configuration. This prevents a small, stable contract for non-Hermes agents and risks cross-client interference.

## Decision

V1.1.0 will define a small, versioned public lifecycle API with explicitly constructed runtime instances. Host adapters receive runtime handles; they do not mutate a process-global master runtime.

## Why

This directly addresses F-006 and F-011 and enables a generic agent integration without coupling callers to internal module layout.

## Consequences

- Public lifecycle, error, consistency, and close semantics must be documented and tested.
- Existing internal imports require a migration/deprecation plan.
- Adapter construction changes are scoped to WP-08 and dependent packages only after authorization.

## Rejected Alternatives

- Keep internal `src.*` modules as the external contract.
- Retain mutable module-global runtime as the universal configuration path.
