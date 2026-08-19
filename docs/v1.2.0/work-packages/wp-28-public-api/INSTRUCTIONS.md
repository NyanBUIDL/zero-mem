# WP-28 Instructions

## Objective

Define and verify the agent-agnostic, transport-neutral public Zero-Mem API contracts for lifecycle, capture, health, and the four read capabilities: `search`, `get_trace`, `get_task_state`, and `get_decisions`.

## Dependencies

- WP-25 Runtime Ownership — VERIFIED.
- WP-26 Projection — VERIFIED.

## Scope

- Stable public imports under `zero_mem`.
- Typed request/result/status/error contracts.
- Capability mapping and explicit unavailable behavior for capabilities not yet owned by a later WP.
- Synchronous and bounded asynchronous client lifecycle parity.
- Generic-agent contract tests and compatibility snapshots.

## Out of scope

Authorization implementation (WP-29), sidecar transport (WP-30), Hermes behavior (WP-31), context/ranking (WP-32), new storage schemas, and retrieval implementation.

## Required invariants

- Generic callers use only `zero_mem` public imports.
- No Hermes, `src`, SQL, filesystem, or transport details leak through the public contract.
- Identity is explicit; no inferred profile/project.
- Canonical capture success requires durable append evidence.
- Disabled, unconfigured, invalid, closed, timeout, and unavailable states are typed and deterministic.
- Public API version is independent of package patch version.

## Allowed changes

`zero_mem/api.py`, `zero_mem/core.py`, `zero_mem/__init__.py`, focused public API tests, and WP-28 documentation/evidence. Narrow compatibility fixes are allowed when directly required by contract tests.

## Prohibited changes

No authorization-after-retrieval, storage exposure, schema migration, new dependency, Hermes-specific semantics, sidecar transport, release publication, or future-WP retrieval implementation.

## Required inputs/outputs

Inputs are explicit config, identity, writer/client dependencies, typed requests, and bounded deadlines. Outputs are typed lifecycle results, capture results, capability results, health, and sanitized typed errors.

## Escalation conditions

Escalate if a canonical contract requires changing the Unified Specification/ADR, exposing storage, weakening durable receipt semantics, adding a dependency, or implementing WP-29+ behavior.

## Completion conditions

Planning package validated; public-only generic tests pass; four capability mappings are stable; negative/failure paths pass; relevant regression passes; independent review passes; evidence and project state record `VERIFIED`.
