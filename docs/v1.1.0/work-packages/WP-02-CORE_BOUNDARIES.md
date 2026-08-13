# Work Package: WP-02 — Core and Adapter Boundaries

**ID:** WP-02

**Title:** Core and Adapter Boundaries


**Status:** NOT STARTED

**Priority:** P1


**Categories:** ARCHITECTURE, INTEGRATION, MAINTAINABILITY

## Related Findings

F-001, F-002, F-006, F-007, F-011. Related ADRs: ADR-001 and ADR-002.

## Read Scope

Read only the modules named in **Files / Modules to Inspect**, public package metadata, and the relevant ADRs.

## Planning Write Scope

V1.1.0 RE-PLANNING: documentation only — this work package, `TRACEABILITY.md`, and ADR-001/ADR-002. No implementation write scope exists.

## Planning Files Allowed to Modify

This work package, `TRACEABILITY.md`, ADR-001, and ADR-002 only.

## Proposed Implementation Write Scope

**PROPOSED FOR A FUTURE AUTHORIZATION ONLY.** A maintainer may authorize only the minimum subset of the entries under **Files / Modules to Inspect**, plus directly associated tests and benchmarks required by this package's acceptance criteria. Every allowed path must be named explicitly when implementation is authorized; all other paths remain forbidden.

## Forbidden Scope

`zero_mem/`, `src/`, `tests/`, migrations, schemas, dependency metadata, runtime configuration, CI, and git tags.

## Objective

Enforce dependency directions so storage, policy, retrieval, and context logic remain host-independent while Hermes-specific behavior stays in a thin adapter.

## Why This Exists

The current core is conceptually host-independent, but operational APIs are under `src.*`, Hermes integration constructors mutate global runtime state, and release composition imports several internal adapters directly. A stable boundary is required before adding a generic API.

## Current State on master

Hermes-specific modules are concentrated under `src/integration/hermes_*`, `payload_mapping.py`, `bridge_config.py`, and `zero_mem/hermes_integration.py`. Core storage/retrieval generally does not import Hermes. `zero_mem.hermes_integration.HermesBoundary` directly imports internal integration modules at registration time.

## Evidence

- F-006: adapter constructors call `zero_mem_runtime.configure()` and overwrite process-global state.
- F-011: `zero_mem.__all__` exposes only `__version__`; integrations use internal modules.
- Hermes adapter uses plugin-context duck typing and no mandatory Hermes package import, which should be preserved.

## Problems Found

- No enforced public/internal module boundary.
- Runtime configuration is global rather than client-owned.
- Host adapter can instantiate incomplete core components.
- Hermes hook payload schema can leak into lifecycle design if reused as the generic event contract.

## Affected Components

`zero_mem`, `src.integration`, public packaging exports, tests importing internal modules.

## Files / Modules to Inspect

- [`src/integration/zero_mem_runtime.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration/zero_mem_runtime.py)
- [`src/integration/hermes_registration.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration/hermes_registration.py)
- [`src/integration/hermes_read_adapter.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration/hermes_read_adapter.py)
- [`src/integration/m7/injection_adapter.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration/m7/injection_adapter.py)
- [`zero_mem/hermes_integration.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/hermes_integration.py)
- [`zero_mem/__init__.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/__init__.py)

## Desired State

Dependencies flow `adapter -> public API -> core -> storage/retrieval`; never `core -> adapter`. Runtime/configuration is immutable and client-owned. Hermes payloads are translated to public observations before reaching core logic.

## Constraints

Preserve existing verified redaction, authorization, fail-open host behavior, and M7 context hardening. Avoid large file moves unless required to enforce imports.

## Required Changes

1. Define public core protocols/types independent of Hermes hook names.
2. Replace mutable global runtime ownership with an injected immutable runtime/client.
3. Make incomplete component construction impossible through public APIs.
4. Add import/dependency tests.
5. Establish internal API deprecation policy for direct `src.*` users.

## Recommended Direction

Create a public facade that wraps existing internals, then adapt Hermes to it. Retain old internal functions for one compatibility window where inexpensive. Enforce boundaries with static import tests rather than immediate directory churn.

## Alternatives Considered

- Rename all `src` packages immediately: rejected as high-risk and unnecessary.
- Keep global runtime but add locks: rejected; locking does not solve ownership/config conflict.

## Risks

Compatibility breakage for tests and undocumented direct users. Duplicate types can drift if translation is not centralized.

## Compatibility Impact

Public API is additive in V1.1.0. Internal calls may be deprecated but should not be removed without WP-17 disposition.

## Performance Impact

Facade and translation overhead must remain negligible relative to redaction/storage I/O.

## Migration Impact

No data migration. Runtime construction/configuration migration is required for Hermes and generic adopters.

## Tests Required

### Existing Tests

Hermes registration/read/injection tests, M1 non-interference, M5 authorization, M7 end-to-end.

### Missing Tests

Core import graph, conflicting runtime construction, two independent clients in one process, and public-only generic integration.

### Regression Tests

Constructing one disabled adapter cannot disable another client; core import scan rejects Hermes modules.

## Benchmarks Required

Public facade event translation and runtime lookup overhead for 10k no-op/observe calls.

## Acceptance Criteria

- Core package imports no `hermes_*`, `payload_mapping`, or host plugin module.
- Two clients with distinct immutable configurations coexist without changing each other.
- Hermes adapter uses only approved public API imports for operational calls.
- Public construction cannot produce registered capture with no writer/consistency policy.

## Definition of Done

- Boundary contract implemented and reviewed.
- Import/regression tests pass.
- Existing subsystem tests pass.
- API/deprecation documentation updated.
- Benchmark shows no material facade regression against WP-00 baseline.

## Dependencies

WP-00, WP-01.

## Blocks

WP-04, WP-07, WP-08, WP-11, WP-12, WP-13.

## Out of Scope

Storage algorithm changes, ranking redesign, remote service boundaries, and non-Hermes ecosystem adapters.
