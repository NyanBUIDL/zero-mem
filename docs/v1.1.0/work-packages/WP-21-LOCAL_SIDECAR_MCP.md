# Work Package: WP-21 — Local Sidecar and MCP Interface

**ID:** WP-21

**Status:** NOT STARTED

**Priority:** P1

## Objective

Expose the transport-neutral Zero-Mem capability contract through a supported local sidecar binding, with MCP as the baseline V1.1.0 binding and identical semantics for any optional local HTTP/Unix-socket binding.

## Why

The canonical specification requires a sidecar retrieval interface and four MVP MCP capabilities. Exact master has a thin MCP wrapper but no packaged service lifecycle, public canonical names, endpoint threat boundary, or generic-client conformance gate.

## Canonical Requirements and Sources

REQ-API-001 through REQ-API-011 and relevant REQ-SEC/REQ-TEST rows in `SPEC_TRACEABILITY.md`; canonical DOCX §§4.2, 11.5, 13.1–13.3, 16.1, 17, 18; ADR-006; `INTERFACE_CONTRACT.md`.

## Scope

- MCP/local sidecar lifecycle, startup/readiness/shutdown, framing, version negotiation, deadlines, backpressure, local endpoint exposure, request/response limits, typed errors, and conformance.
- Bind `zero_mem.search`, `zero_mem.get_trace`, `zero_mem.get_task_state`, and `zero_mem.get_decisions` to WP-08.
- Preserve a compatibility path for exact-master M6 tools without making them the new canonical contract.
- Generic non-Hermes client fixture and Hermes client reuse.

## Out of Scope

Retrieval/ranking (WP-05), profile policy (WP-20), canonical storage (WP-04), Hermes hooks (WP-07), remote/cloud/multi-tenant service, and the post-MVP capabilities unless separately authorized.

## Dependencies

WP-02, WP-04, WP-05, WP-08, WP-11, WP-13, WP-14, WP-15, WP-20; ADR-006.

## Architecture Constraints

Transport contains no policy/storage/Hermes logic; local is not trusted; explicit identity and authorization are mandatory; service defaults are local-only and fail closed on remote/wildcard exposure; no mandatory LLM/network/external database; bounded queues, sizes, deadlines, and context.

## Files / Components Expected to Change

Future authorization may name the minimum subset of `src/integration/m6/**`, new public service/transport modules, CLI/config/status integration, packaging entry points, and direct tests/benchmarks. Exact paths require maintainer authorization.

## Files / Components That Must Not Change

Hermes core, unrelated retrieval/storage implementation, raw canonical records, or any executable path before authorization. Planning phase permits only `docs/**`.

## Implementation Tasks

1. Bind exact-master dispatcher semantics to `INTERFACE_CONTRACT.md` and canonical names.
2. Implement packaged local lifecycle and endpoint ownership with readiness/health.
3. Enforce identity, authorization handoff, size/deadline/concurrency limits, and safe errors.
4. Implement contract-version negotiation and legacy M6 compatibility aliases/migration.
5. Add generic client and Hermes client conformance against one server fixture.
6. Document setup, removal, timeout/fallback, and disabled/unavailable behavior.

## Acceptance Criteria

- All four MVP capabilities pass the full contract fields and scenarios in `INTERFACE_CONTRACT.md`.
- A clean non-Hermes client integrates through the local interface without importing `src.*` or changing core/storage/retrieval.
- Hermes uses the same capability contract; no Hermes-only service method exists.
- Remote/wildcard bind, missing identity, privilege fields, oversized payload, deadline breach, overload, and incompatible version fail deterministically and safely.
- Embedded/direct/MCP results are semantically identical for success, empty, deny, stale, conflict, timeout, and error fixtures.
- Disabled/unavailable sidecar never breaks the parent agent and never reports ready when persistence/retrieval prerequisites are absent.

## Negative and Regression Tests

Unauthorized local caller, endpoint spoof, request smuggling/framing errors, concurrent identities, cancellation, retry, oversized response, hidden-ID probing, unavailable DB/FTS, shutdown race, restart, no public listener, and exact-master M6 read-only/no-admin/no-write regression.

## Migration and Compatibility Impact

Version tool names and envelopes independently of package patch version. Map or deprecate ten existing M6 tool names with a documented window. Upgrade preserves descriptors/configuration and does not silently expose a network listener.

## Security / Privacy Impact

High-impact local API boundary. Enforce least privilege, local endpoint permissions/authentication, path safety, sanitized errors, secret-free logs, non-probing denial, and authorization-before-influence.

## Performance Impact and Benchmarks

Measure cold/warm startup, per-tool p50/p95/p99, serialization/framing overhead, queue wait, memory, concurrent requests, timeout cleanup, and context/token size at 1k/10k and approved large scale. Benchmark required before thresholds are frozen.

## Observability

Expose version, transport, endpoint class (not secret path/token), readiness, request counts by safe status, queue saturation, deadline/overload counts, latency stages, and active connections with bounded cardinality.

## Rollback

Stop/remove the service binding and restore the previous config/descriptor while retaining canonical data. Compatibility aliases permit client rollback; no rollback step deletes user memory.

## Exit Gate and Traceability

Exit requires ADR-006 approval, four-capability contract conformance, security/performance/lifecycle tests on every supported platform, generic and Hermes client E2E, migration/rollback proof, and all mandatory REQ-API rows `COVERED`.

## Planning and Implementation Authorization

This package is design-only in the current phase. Proposed source/test scopes are not authorization.
