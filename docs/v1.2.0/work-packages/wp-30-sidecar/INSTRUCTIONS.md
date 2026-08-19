# WP-30 Instructions

## Objective

Provide a bounded local sidecar/transport adapter with semantic parity to the WP-28 public API and WP-29 authorization boundary.

## Dependencies

- WP-28 Public API — VERIFIED.
- WP-29 Authorization — VERIFIED.
- WP-25 Runtime Ownership — VERIFIED.

## Scope

Deserialize and validate transport requests, propagate explicit identity, call the canonical client/dispatcher, serialize sanitized responses, and enforce request/response byte bounds, bounded concurrency/queue, and deadlines for local MCP/stdio/loopback use.

## Out of scope

SQL, JSONL, authorization policy, grant resolution, retrieval/ranking, context assembly, Hermes core changes, network service deployment, or alternate retrieval pipeline.

## Required invariants

- Sidecar is a thin adapter only; semantic parity with direct API.
- Authorization remains in canonical service before discovery.
- Identity is explicit and unchanged end-to-end.
- Request bytes, response bytes, concurrency, queue, and deadline are bounded.
- No raw exception, path, SQL, secret, or canonical storage exposure.
- Shutdown is bounded and does not block host termination indefinitely.

## Allowed changes

Existing `src/integration/mcp_wrapper.py`, `src/integration/hermes_read_adapter.py`, M6 transport contracts/errors/dispatcher, and focused sidecar tests/docs/evidence.

## Prohibited changes

Transport-local auth/ranking/SQL/retrieval, unbounded queues, infinite retry, hidden fallback, remote server publication, new dependency, or Hermes core modification.

## Escalation conditions

Escalate if semantic parity requires duplicating authorization/retrieval, if identity trust cannot be preserved, if a public network boundary is required, or if bounded shutdown cannot be guaranteed with current primitives.

## Completion conditions

Direct/sidecar parity, bounds, overload/deadline, identity, failure isolation, and restart evidence pass; independent review passes; state becomes `VERIFIED`.
