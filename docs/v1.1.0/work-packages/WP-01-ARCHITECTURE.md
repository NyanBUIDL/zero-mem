# Work Package: WP-01 — Architecture Contract

**ID:** WP-01

**Title:** Architecture Contract


**Status:** NOT STARTED

**Priority:** P1


**Categories:** ARCHITECTURE, MAINTAINABILITY

## Related Findings

F-002, F-003, F-004, F-006, F-008, F-011, F-012. Related ADRs: ADR-001 through ADR-005.

## Canonical Requirements

REQ-ARCH-001 through REQ-ARCH-007 and REQ-STORE-001 through REQ-STORE-004 in `SPEC_TRACEABILITY.md`; canonical DOCX §§2.3, 3.3, 5, 9, 13, and 16; ADR-001 through ADR-008.

## Read Scope

Read only the modules named in **Files / Modules to Inspect**, their direct contracts, and the baseline architecture/data-flow maps.

## Planning Write Scope

V1.1.0 RE-PLANNING: documentation only — this work package, `MASTER_PLAN.md`, `TRACEABILITY.md`, and relevant ADRs. No implementation write scope exists.

## Planning Files Allowed to Modify

This work package, `MASTER_PLAN.md`, `TRACEABILITY.md`, and relevant ADRs only.

## Proposed Implementation Write Scope

**PROPOSED FOR A FUTURE AUTHORIZATION ONLY.** A maintainer may authorize only the minimum subset of the entries under **Files / Modules to Inspect**, plus directly associated tests and benchmarks required by this package's acceptance criteria. Every allowed path must be named explicitly when implementation is authorized; all other paths remain forbidden.

## Forbidden Scope

`zero_mem/`, `src/`, `tests/`, migrations, schemas, dependency metadata, runtime configuration, CI, and git tags.

## Objective

Approve the minimum V1.1.0 architecture contract that preserves the V1.0.0 canonical/derived model while introducing a stable public lifecycle and thin host adapters.

## Why This Exists

V1.0.0 has strong subsystem separation but no single operational composition. Documentation depicts append plus SQLite updates as one flow, while code implements separate capture and ingest paths. Architecture must decide ownership and consistency before code changes begin.

## Current State on master

Capture is implemented by `src.integration.hermes_registration`, `capture_adapter`, and `src.storage.jsonl_capture`. Derived projection is implemented separately by `src.storage.ingest`. Retrieval uses `src.retrieval` and `src.access`; context uses `src.integration.m7` and `src.m8`. Release lifecycle is in `zero_mem/*`.

## Evidence

- `RegistrationAdapter._observe()` persists only when a store was injected.
- `adapt_mapped_event()` ends at `store.append()`.
- `ingest_file()` is an explicit separate operation.
- `zero_mem/__init__.py` exports no operational API.
- `ARCHITECTURE.md` describes a more continuous flow than the runtime composition provides.

## Problems Found

- Responsibility for writer construction, projection scheduling, freshness, and shutdown is undefined.
- Host adapters can bypass or partially compose the core.
- Mutable process-global runtime configuration conflicts with multi-client use.
- Core versus adapter import boundaries are not enforced.

## Affected Components

Release package, capture, storage, retrieval, context, Hermes adapter, generic agent API, configuration, observability.

## Files / Modules to Inspect

- [`zero_mem/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem)
- [`src/integration/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration)
- [`src/storage/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/storage)
- [`src/retrieval/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/retrieval)
- [`src/access/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/access)
- [`src/corpus/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/corpus)

## Desired State

One public runtime/client owns configuration resolution, the composite canonical trace contract, projector/index consistency policy, read sessions, health, and shutdown. Adapters translate host events and call that API. A supported local sidecar binding exposes the same capabilities. Core modules import no Hermes-specific or transport-specific code. Append-first JSONL/artifacts/approved write-back records preserve replay provenance; canonical SQLite metadata/lifecycle is queryable; FTS/vector/graph/cache/Obsidian state is rebuildable.

## Constraints

No V2 rewrite. Preserve local-first operation, deterministic behavior, no mandatory network/model calls, and low dependency footprint. Keep existing internal implementations where they satisfy the approved interface.

## Required Changes

1. Approve component ownership and import direction.
2. Choose a V1.1 consistency mode set: at minimum `synchronous` and/or `explicit_sync`; queued mode requires evidence.
3. Define single-writer versus shared-writer architecture.
4. Define public API and adapter version boundaries.
5. Define health/freshness semantics.
6. Update architecture diagrams and ADRs before implementation.
7. Define profile/knowledge-space, local sidecar, Obsidian projection/write-back, and conflict ownership without duplicate contracts.

## Recommended Direction

Add a thin facade over existing modules first. Move code only when import-boundary tests prove it necessary. Use dependency tests to prohibit core imports from `hermes_*` modules.

## Alternatives Considered

- Remote/cloud service rewrite: rejected. A small local sidecar binding required by the canonical specification is in scope through WP-21.
- Keep host-owned composition undocumented: rejected because it caused F-001/F-002.
- Make SQLite/derived indexes the only canonical source and discard append-first replay provenance: rejected; it violates ADR-003 and recovery invariants.

## Risks

An overly broad facade can become a second implementation. An overly narrow facade will leave integrations dependent on `src.*`.

## Compatibility Impact

Existing internal callers must continue to work during V1.1.0 or receive a documented deprecation path.

## Performance Impact

Architecture must avoid adding mandatory background services or extra copies on hot paths.

## Migration Impact

No canonical format change is assumed. Any configuration/API versioning is routed to WP-17.

## Tests Required

### Existing Tests

M1–M10 subsystem tests and package acceptance tests.

### Missing Tests

Import-boundary tests, public-runtime lifecycle tests, and adapter-only dependency tests.

### Regression Tests

Boundary registration without persistence must fail or expose a deterministic unavailable state.

## Benchmarks Required

Facade overhead versus direct V1.0.0 calls for capture, sync, and retrieval.

## Acceptance Criteria

- Approved architecture identifies owner/interface/state for every major component.
- Zero-Mem core imports no Hermes-specific module.
- A single lifecycle object has explicit initialize/observe/sync/retrieve/health/shutdown ownership.
- The composite canonical and derived-state distinctions in ADR-003 are explicit, replayable, and migration-safe.
- WP-08/WP-21 own one agent interface; WP-07 owns only Hermes mapping; WP-20 owns profile modes; WP-22 owns Obsidian projection/write-back; WP-14 owns canonical conflict lifecycle.
- No unresolved circular dependency exists among work packages or modules.

## Security / Privacy, Observability, and Rollback

Architecture review must prove authorization-before-influence, redaction-before-persist, local-endpoint distrust, bounded evidence, and no cross-profile write escalation. Health ownership covers canonical/derived/projection watermarks and adapter/service readiness without content. Rollback restores the prior public/configuration/adapter contract and rebuilds disposable state without rewriting raw canonical history.

## Exit Gate and Traceability

Exit requires ADR-001 through ADR-008 reviewed together, an acyclic component/WP graph, complete canonical requirement ownership in `SPEC_TRACEABILITY.md`, negative boundary tests planned, and no unresolved BLOCKER in the alignment gap analysis.

## Definition of Done

- Architecture ADRs approved.
- Dependency graph and state ownership reviewed.
- Public/internal boundaries accepted by WP-02 and WP-08 owners.
- Migration and compatibility impacts recorded.

## Dependencies

WP-00.

## Blocks

WP-02 through WP-19 implementation decisions.

## Out of Scope

Detailed API signatures, storage optimization implementation, and ecosystem adapters beyond Hermes/generic Python.
