# Work Package: WP-07 — Hermes Adapter Hardening

**ID:** WP-07

**Title:** Hermes Adapter Hardening


**Status:** NOT STARTED

**Priority:** P1


**Categories:** BUG, INTEGRATION, COMPATIBILITY, RELIABILITY

## Related Findings

F-001, F-007, F-013. Related ADR: ADR-002.

## Canonical Requirements

REQ-ARCH-002/003/005, REQ-CAP-001/002, and REQ-API-001 through REQ-API-008 in `SPEC_TRACEABILITY.md`; canonical DOCX §§2.3, 5.1, 10.1–10.2, 13.1–13.3, 18 stage 6; ADR-002 and ADR-006.

## Read Scope

Read only the Hermes integration modules named in **Files / Modules to Inspect**, public API contract material, and ADR-002.

## Planning Write Scope

V1.1.0 RE-PLANNING: documentation only — this work package, ADR-002, `TRACEABILITY.md`, and future Hermes runbooks under `docs/`. No host registration/code/configuration write scope exists.

## Planning Files Allowed to Modify

This work package, ADR-002, `TRACEABILITY.md`, and Hermes runbook Markdown under `docs/` only.

## Proposed Implementation Write Scope

**PROPOSED FOR A FUTURE AUTHORIZATION ONLY.** A maintainer may authorize only the minimum subset of the entries under **Files / Modules to Inspect**, plus directly associated tests and benchmarks required by this package's acceptance criteria. Every allowed path must be named explicitly when implementation is authorized; all other paths remain forbidden.

## Forbidden Scope

`zero_mem/`, `src/`, `tests/`, migrations, schemas, dependency metadata, runtime configuration, CI, and git tags.

## Objective

Deliver a thin, installable Hermes adapter whose successful registration guarantees a valid persistence/read/context path and whose failure cannot break Hermes.

## Why This Exists

The V1.0.0 descriptor CLI does not activate a plugin, `HermesBoundary` constructs capture registration without a store, hook coverage is partial, and the descriptor rejects any package-version mismatch.

## Current State on master

`zero_mem.hermes_integration` owns descriptor commands and `HermesBoundary`. `src.integration.hermes_registration` maps verified hooks; `hermes_read_adapter` exposes M6 tools; M7 injection registers `pre_llm_call`. All use plugin-context duck typing.

## Evidence

F-001 and F-007; supported/deferred hooks are enumerated in `bridge_config.py`. Release code imports no Hermes package, a strength to preserve.

## Problems Found

- BUG P1: capture hooks can register without persistence.
- INTEGRATION P1: CLI configures descriptor only; host activation is undocumented/incomplete.
- COMPATIBILITY P1: descriptor binds exact package version.
- RELIABILITY P2: fail-open errors are mostly in-memory and silent.
- Hook compatibility beyond Hermes v0.19.1: `Needs verification`.

## Affected Components

Hermes descriptor, plugin registration, capture, read tools, injection, doctor, packaging, migration.

## Files / Modules to Inspect

- [`zero_mem/hermes_integration.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/hermes_integration.py)
- [`src/integration/bridge_config.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration/bridge_config.py)
- [`src/integration/hermes_registration.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration/hermes_registration.py)
- [`src/integration/hermes_read_adapter.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration/hermes_read_adapter.py)
- [`src/integration/payload_mapping.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration/payload_mapping.py)
- [`src/integration/m7/injection_adapter.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration/m7/injection_adapter.py)

## Desired State

Hermes adapter imports only the public Zero-Mem API/client. Installation exposes a documented supported plugin entry point. Registration reports per-surface readiness; capture cannot be “registered” without a writer. Read tools call the same four canonical capabilities as a generic client through the embedded/local interface. Descriptor compatibility uses adapter, capability, and boundary versions, not exact package version.

## Constraints

No Hermes core edits, no secret reads, no identity inference, no raw SQL/JSONL/admin tools, and Hermes must continue when Zero-Mem is unavailable.

## Required Changes

1. Build adapter on WP-08 public lifecycle.
2. Define actual plugin activation/entry-point steps.
3. Make surface registration atomic or explicitly report partial readiness.
4. Version descriptor by contract and provide migration/revalidation.
5. Verify supported hook signatures against target Hermes versions.
6. Persist content-safe adapter diagnostics through WP-15.
7. Map every canonical capture class (session, message, tool, file, skill, task, decision/artifact/verification where observable) to a verified hook or an explicit public-observation fallback/capability-unavailable state; never claim unsupported coverage.
8. Define the integration matrix: capture/write path, read path, optional controlled-injection path, caller identity/authorization, deadline, retry, fail-open host behavior, fail-closed policy behavior, fallback, shutdown, and compatibility.

## Recommended Direction

Keep current mapping/read/injection logic where tests prove it. Replace composition and lifecycle ownership, not the verified security logic. Publish one adapter factory accepting a public client and explicit identity.

## Alternatives Considered

- Edit Hermes internals/config automatically: rejected.
- Bundle Hermes as a dependency: rejected.
- Keep descriptor-only integration: rejected as insufficient user experience.

## Risks

Hermes hook API drift, duplicate `pre_llm_call` registration, partial registration rollback, and descriptor migration mistakes.

## Compatibility Impact

Existing v0.19.1 behavior should remain supported. Additional Hermes versions require verified fixtures. Exact package-bound descriptors need a V1.1 migration path.

## Performance Impact

Measure per-hook capture overhead and pre-LLM retrieval/injection overhead. Disabled mode must perform no DB/file work.

## Migration Impact

Migrate/revalidate `hermes-integration.json` without losing project/profile identity. Preserve opt-in state and fail closed on unknown boundary versions.

## Tests Required

### Existing Tests

Hermes payload, registration, non-interference, failure isolation, read adapter, package integration, M7 injection.

### Missing Tests

Installed-wheel real activation, writer-backed capture-to-retrieval, descriptor package upgrade, partial registration cleanup, target Hermes version matrix.

### Regression Tests

Registered capture writes a canonical event; missing writer yields explicit unavailable status; package patch/minor upgrade does not invalidate compatible descriptor.

## Benchmarks Required

Session start, pre/post tool, session end, read tool, no-memory pre-LLM, memory-needed pre-LLM; cold/warm and failure paths.

## Acceptance Criteria

- A fresh Hermes installation can activate the adapter using documented supported steps.
- One captured fixture event is canonical, synced, authorized, and retrievable.
- Hermes continues unchanged when every Zero-Mem surface is unavailable.
- Adapter operational code imports only public Zero-Mem API modules.
- Descriptor survives compatible V1.0→V1.1 package upgrade.
- `zero_mem.search`, `zero_mem.get_trace`, `zero_mem.get_task_state`, and `zero_mem.get_decisions` produce the same results through Hermes and the generic client.
- Read timeout/unavailability performs no unsafe context injection and returns the documented empty/unavailable fallback; denial never falls back to broader scope.
- Enabled capture covers every declared canonical event class or emits an explicit unsupported-hook diagnostic; registration success never means silent drop.
- Hermes core source remains unchanged unless a future maintainer authorization explicitly names the minimum unavoidable file scope.

## Security / Privacy, Observability, and Rollback

Hermes supplies explicit caller/profile/project identity but cannot supply grants, trust flags, raw paths, or verification. Redaction precedes capture; read/write authorization remains core-owned. Per-surface readiness, hook/tool versions, last safe error, timeout/fallback, and capture/retrieval watermark are content-safe. Rollback unregisters/removes the adapter descriptor and restores compatible config while preserving all user data.

## Exit Gate and Traceability

Exit requires installed-wheel real activation, event-class coverage, capture→canonical→sync→read, four-capability parity, timeout/failure/security/migration/performance tests, no Hermes-core dependency in core, and all mapped requirements `COVERED`.

## Definition of Done

- End-to-end installed integration verified.
- Hook/tool/injection tests and benchmarks pass.
- Migration and removal paths verified.
- Compatibility matrix and operator guide updated.

## Dependencies

WP-02, WP-04, WP-06, WP-08, WP-13, WP-15, WP-20, WP-21.

## Blocks

WP-10 Hermes install docs, WP-16 integration gate, WP-19.

## Out of Scope

Hermes core modifications, unsupported internal hooks, automatic identity inference, and non-Hermes adapters.
