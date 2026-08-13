# Work Package: WP-08 — Agent-Agnostic Public API

**ID:** WP-08

**Title:** Agent-Agnostic Public API


**Status:** NOT STARTED

**Priority:** P1


**Categories:** ARCHITECTURE, INTEGRATION, DEVELOPER EXPERIENCE

## Related Findings

F-002, F-006, F-011, F-014. Related ADR: ADR-001.

## Read Scope

Read only the existing public package and internal components listed in **Files / Modules to Inspect**, their direct contracts, and ADR-001.

## Planning Write Scope

V1.1.0 RE-PLANNING: documentation only — this work package, ADR-001, `TRACEABILITY.md`, and public API design notes under `docs/v1.1.0/`. No package/module write scope exists.

## Planning Files Allowed to Modify

This work package, ADR-001, `TRACEABILITY.md`, and API design Markdown under `docs/v1.1.0/` only.

## Proposed Implementation Write Scope

**PROPOSED FOR A FUTURE AUTHORIZATION ONLY.** A maintainer may authorize only the minimum subset of the entries under **Files / Modules to Inspect**, plus directly associated tests and benchmarks required by this package's acceptance criteria. Every allowed path must be named explicitly when implementation is authorized; all other paths remain forbidden.

## Forbidden Scope

`zero_mem/`, `src/`, `tests/`, migrations, schemas, dependency metadata, runtime configuration, CI, and git tags.

## Objective

Provide a small versioned public API through which generic synchronous agents can initialize, observe, sync, retrieve, inspect health, and shut down without importing `src.*`.

## Why This Exists

V1.0.0 exports only `__version__`; operational integrations must understand internal envelope, storage, authorization, and lifecycle modules. This prevents low-friction adoption and makes internal changes breaking.

## Current State on master

Useful primitives exist across `src.capture`, `src.storage`, `src.access`, `src.retrieval`, and `src.integration.m7`, but no facade composes them. CLI setup/doctor are not a library lifecycle.

## Evidence

F-011 and F-002. Generic agent compatibility was scored 4/10 in the audit because adopters must invent composition and failure isolation.

## Problems Found

- ARCHITECTURE P1: no stable operational API.
- INTEGRATION P1: consistency/writer/read ownership left to each adapter.
- DEVELOPER EXPERIENCE P2: no minimal generic example or typed lifecycle errors.
- Sync/async-neutral event contract is missing.

## Affected Components

Package exports, runtime/configuration, capture, sync, retrieval, context, Hermes adapter, docs, versioning.

## Files / Modules to Inspect

- [`zero_mem/__init__.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/__init__.py)
- Proposed public `zero_mem/api.py` or `zero_mem/api/**` — **Needs verification** after API design approval.
- Existing [`src/capture/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/capture), [`src/storage/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/storage), [`src/access/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/access), [`src/retrieval/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/retrieval), and [`src/integration/m7/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration/m7).

## Desired State

An external agent uses only documented public types and methods similar to:

```text
ZeroMemClient.open(config)
client.session_start(...)
client.observe_message(...)
client.observe_tool_call(...)
client.sync()
client.retrieve(request)
client.health()
client.shutdown()
```

Exact names require API review; lifecycle semantics are mandatory.

## Constraints

No host-specific event names in core API. Explicit identity only. Typed sanitized errors. No mandatory async runtime, daemon, network, LLM, or third-party dependency.

## Required Changes

1. Define public configuration, observation, retrieval, result, health, and error types.
2. Define idempotency, consistency, thread/process ownership, and shutdown semantics.
3. Wrap existing redaction/validation/storage/access/context paths.
4. Publish API version and compatibility policy.
5. Deprecate direct internal operational imports without immediate forced removal.

## Recommended Direction

Start with one synchronous client and context manager. WP-11 adds async wrappers/worker guidance without changing core semantics. Keep low-level read APIs available only as explicitly advanced public interfaces if justified.

## Alternatives Considered

- CLI subprocess as only API: rejected for embedded agents.
- MCP/local HTTP as mandatory: rejected for V1.1 simplicity.
- Expose all internal classes publicly: rejected due to instability/complexity.

## Risks

Prematurely freezing a broad API, hiding necessary diagnostics, and accidental duplicate state ownership between facade and internals.

## Compatibility Impact

Additive public surface. Existing internal users need a migration guide and at least one compatibility window.

## Performance Impact

Facade overhead must be bounded and measured. Client should reuse owned resources rather than create per-call connections.

## Migration Impact

No canonical data change. Configuration and API version changes require WP-17 guidance.

## Tests Required

### Existing Tests

All subsystem tests validate delegated behavior.

### Missing Tests

Public-only generic agent fixture, lifecycle idempotency, typed errors, resource cleanup, two clients, disabled mode, stale-derived health.

### Regression Tests

Generic example cannot import `src`; enabled observe cannot silently drop data; shutdown releases writer/read resources.

## Benchmarks Required

Direct internal versus public API capture/sync/retrieve overhead; cold/warm client startup and 10k no-memory calls.

## Acceptance Criteria

- A clean generic Python fixture performs the full lifecycle using only `zero_mem` public imports.
- Public methods have documented idempotency, consistency, failure, and ownership semantics.
- No public operation requires knowledge of canonical file paths or SQLite schema.
- Public API version is independent from package patch version.
- Resource closure and fail-open/fail-closed behavior are tested.

## Definition of Done

- API contract approved, implemented, typed, and documented.
- Generic agent end-to-end test passes from installed wheel.
- Performance overhead recorded.
- Internal migration/deprecation notes published.

## Dependencies

WP-01, WP-02, WP-04 consistency design, WP-13 configuration design.

## Blocks

WP-07, WP-09, WP-11, WP-12, WP-18, WP-19.

## Out of Scope

Framework-specific adapters, remote service protocol, broad admin APIs, and mandatory async implementation.
