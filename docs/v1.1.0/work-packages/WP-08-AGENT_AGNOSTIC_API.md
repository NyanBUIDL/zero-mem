# Work Package: WP-08 — Agent-Agnostic Public API

**ID:** WP-08

**Title:** Agent-Agnostic Public API


**Status:** NOT STARTED

**Priority:** P1


**Categories:** ARCHITECTURE, INTEGRATION, DEVELOPER EXPERIENCE

## Related Findings

F-002, F-006, F-011, F-014. Related ADR: ADR-001.

## Canonical Requirements

REQ-ARCH-001/004/005, REQ-RETR-009/010, and REQ-API-001 through REQ-API-011 in `SPEC_TRACEABILITY.md`; canonical DOCX §§2.3, 5.1, 11.5, 13.1–13.3, 16.1, 18; ADR-001 and ADR-006; `INTERFACE_CONTRACT.md`.

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

Provide the small versioned transport-neutral lifecycle and capability API through which any agent can initialize, observe, sync, call the four canonical read capabilities, inspect health, and shut down without importing `src.*` or depending on Hermes.

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

The lifecycle method names require API review; the external capability names and semantics in `INTERFACE_CONTRACT.md` are mandatory: `zero_mem.search`, `zero_mem.get_trace`, `zero_mem.get_task_state`, and `zero_mem.get_decisions`.

## Constraints

No host-specific event names in core API. Explicit identity only. Typed sanitized errors. No mandatory async runtime, remote network, LLM, or heavyweight third-party dependency. A supported local sidecar binding is mandatory through WP-21 and must be a thin semantic peer, not a second implementation.

## Required Changes

1. Define public configuration, observation, retrieval, result, health, and error types.
2. Define idempotency, consistency, thread/process ownership, and shutdown semantics.
3. Wrap existing redaction/validation/storage/access/context paths.
4. Publish API version and compatibility policy.
5. Deprecate direct internal operational imports without immediate forced removal.
6. Freeze every purpose/input/output/scope/authorization/profile/space/provenance/error/empty/timeout/determinism/compatibility/test field in `INTERFACE_CONTRACT.md`.
7. Reserve the three canonical post-MVP capability names and return typed unavailable status until separately implemented.

## Recommended Direction

Start with one synchronous client and context manager. WP-11 adds async wrappers/worker guidance without changing core semantics. Keep low-level read APIs available only as explicitly advanced public interfaces if justified.

## Alternatives Considered

- CLI subprocess as only API: rejected for embedded agents.
- Remote HTTP/cloud service as mandatory: rejected. The canonical local sidecar/MCP binding is required and owned by WP-21.
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
- All four canonical capabilities pass direct/API/local-transport conformance and expose complete provenance, conflict, insufficiency, freshness, omitted-count, timeout, and deterministic-order semantics.
- Replacing Hermes with a generic fixture requires no core/storage/retrieval rewrite.

## Security / Privacy, Observability, and Rollback

The API accepts no caller-supplied grant/admin/raw-storage authority; explicit identity and WP-20 scope fields are validated, and authorization precedes influence. Health exposes lifecycle/watermarks/resources without content. Contract versions and compatibility aliases are reversible for the published window; rollback does not rewrite canonical data.

## Exit Gate and Traceability

Exit requires `INTERFACE_CONTRACT.md` approval, public-only generic lifecycle, four-capability conformance, negative/security/timeout/resource/performance tests, version/migration docs, and all mandatory REQ-API rows `COVERED`.

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

Framework-specific adapters, remote/cloud service protocol, broad admin APIs, post-MVP write/project capabilities, and mandatory native-async implementation. The local sidecar/MCP binding is in scope through WP-21.
