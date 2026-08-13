# Work Package: WP-18 — Documentation and Developer Experience

**ID:** WP-18

**Title:** Documentation and Developer Experience


**Status:** NOT STARTED

**Priority:** P2

**Categories:** Documentation, Developer Experience, Adoption

## Related Findings

F-005, F-007, F-011, F-013. Related ADRs: ADR-001, ADR-002, ADR-004.

## Read Scope

Read public-facing documentation, package metadata, approved WPs, ADRs, CLI/API contracts, and named source modules only to verify claims.

## Planning Write Scope

V1.1.0 RE-PLANNING: documentation only — `docs/`, this work package, and `AGENTS.md` where agent guidance changes. No executable example, package, test, or configuration write scope exists.

## Planning Files Allowed to Modify

`docs/**`, this work package, and `AGENTS.md` only.

## Proposed Implementation Write Scope

**PROPOSED FOR A FUTURE AUTHORIZATION ONLY.** A maintainer may authorize only the minimum subset of the entries under **Files / Modules to Inspect**, plus directly associated tests and benchmarks required by this package's acceptance criteria. Every allowed path must be named explicitly when implementation is authorized; all other paths remain forbidden.

## Forbidden Scope

`zero_mem/`, `src/`, `tests/`, `packaging/`, migrations, schemas, dependency metadata, runtime configuration, CI, and git tags.

## Objective

Publish accurate, task-oriented documentation and examples for installing, integrating, operating, troubleshooting, and migrating Zero-Mem v1.1.0.

## Why This Exists

The v1.1.0 program introduces a stable API, generic agent contracts, explicit runtime lifecycle, platform support rules, async guidance, recovery behavior, and migration procedures. Without documentation tied to those contracts, users will continue relying on private imports, integration-specific assumptions, and silent defaults.

## Current State on master

- [`README.md`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/README.md) and repository documentation describe current setup and usage.
- Operational examples may rely on internal `src.*` paths because the package exports only version metadata.
- Hermes is the primary concrete integration context.
- No unified v1.1.0 runbook yet covers freshness, multi-agent modes, async use, rollback, and diagnostics.

## Evidence

- **F-011:** no stable top-level operational API.
- **F-005:** installation guidance is not demonstrably cross-platform.
- **F-013:** troubleshooting does not sufficiently expose capture/lag failures.
- **F-007:** integration descriptor/version semantics require upgrade guidance.
- Documentation coverage and example execution on the supported matrix are **Needs verification**.

## Problems Found

- **F-011 — P1 roadmap / P2 current — Developer experience:** consumers are encouraged toward internal imports.
- **F-005 — P1 — Installation docs:** one platform path can be presented as universal.
- **F-013 — P2 — Troubleshooting:** users lack a decision path for disabled, stale, or failed memory.
- Generic integration, lifecycle, async, multi-agent, and migration examples are missing.

## Affected Components

- README and installation guide
- API reference and examples
- Hermes and generic agent integration guides
- Operations and recovery runbooks
- Migration and release notes
- Contributor workflow

## Files / Modules to Inspect

- [`README.md`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/README.md)
- Existing repository documentation directories
- Public API defined by WP-08
- CLI/status interfaces defined by WP-10 and WP-15
- This [`docs/v1.1.0/`](./) planning set

## Desired State

- A new user can install, set up, capture, retrieve, inspect health, and remove the package using only supported interfaces.
- Integration authors have a generic contract plus a separate Hermes guide.
- Sync and async examples include lifecycle and error handling.
- Multi-agent/profile modes and their safety limits are explicit.
- Operators have diagnosis, recovery, backup, migration, rollback, and data-location runbooks.
- Every executable example is tested against the release wheel.

## Constraints

- Documentation cannot finalize behavior before owning work-package contracts are approved.
- Examples must not use private `src.*` imports.
- Sample memories and telemetry must be synthetic and non-sensitive.
- Platform differences must follow the approved WP-09 matrix.

## Required Changes

1. Define documentation information architecture and owners.
2. Update README quick start around the stable package/CLI surface.
3. Add installation pages per supported environment.
4. Add API, sync/async, lifecycle, profile, and generic integration guides.
5. Add Hermes-specific guide without making Hermes a core requirement.
6. Add health, failure, recovery, migration, rollback, and uninstall runbooks.
7. Add contributor test/benchmark instructions.
8. Execute and link-check all examples in CI.

## Recommended Direction

Write task-oriented pages backed by small executable examples. Generate API reference from public types/signatures where possible, but hand-write conceptual and operational guidance. Draft pages in parallel, then lock them only after their owning work packages reach VERIFIED.

## Alternatives Considered

- **README only:** compact but cannot safely cover lifecycle, platform, and recovery complexity.
- **Generated API docs only:** accurate signatures but no operational decision support.
- **Hermes-only guide:** useful for one host but conflicts with agent-agnostic goals.

## Risks

- Examples can drift from the exact wheel.
- Copy-pasted platform commands can mutate the wrong profile if paths are unclear.
- Overpromising unsupported environments creates false compatibility claims.

## Compatibility Impact

Documentation marks deprecated internal imports and provides supported replacements. Existing guides must either be updated or clearly versioned as v1.0.0.

## Performance Impact

Guides must explain bounded retrieval/context settings and benchmark interpretation without promising unsupported universal latency numbers.

## Migration Impact

Migration documentation must include preflight, backup location, expected duration/space, activation, validation, rollback, and how to retain/remove old artifacts.

## Tests Required

### Existing Tests

- Existing doctests, CLI help tests, or documentation checks under [`tests/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/tests), if present; exact inventory is **Needs verification**.

### Missing Tests

- Execute every quick-start and code sample against the exact wheel.
- Link and anchor validation.
- CLI `--help`/documentation option consistency.
- Platform command validation in supported matrix environments.
- Redaction check for generated logs/status shown in docs.

### Regression Tests

- No v1.1.0 example imports `src.*` or another private module.
- Versioned v1.0.0 docs remain discoverable where retained.
- All referenced configuration fields exist in the WP-13 schema.

## Benchmarks Required

- Tutorial smoke-run time from clean install to first successful capture/retrieval.
- Documentation build/link-check duration only for CI capacity planning.
- No product performance claim may be published without a linked WP-16 result.

## Acceptance Criteria

- Quick start completes on every supported platform using the exact release wheel.
- 100% of executable examples pass in CI and use supported public APIs only.
- Documentation contains separate pages for install, API, generic integration, Hermes, sync/async, multi-agent, configuration, health, recovery, migration, rollback, and uninstall.
- Every documented command and configuration key is validated against the release candidate.
- Search/link checks report zero broken internal links and zero unapproved **Needs verification** claims in release-facing pages.

## Definition of Done

- Maintainer and fresh-user reviews are recorded.
- Examples and links pass in the release pipeline.
- V1.1.0 release notes identify breaking changes, deprecations, compatibility matrix, migration, known limitations, and rollback.
- WP-19 links the final documentation set.

## Dependencies

- WP-07 Hermes Integration
- WP-08 Agent-Agnostic API
- WP-09 Compatibility and Portability
- WP-10 Installation and Packaging
- WP-11 Sync and Async Execution
- WP-12 Multi-Agent Operation
- WP-13 Configuration
- WP-14 Reliability and Recovery
- WP-15 Observability
- WP-17 Migration

## Blocks

- WP-19 Release Readiness

## Out of Scope

- Marketing campaigns
- Translation/localization beyond approved release languages
- Undocumented private API tutorials
- Performance claims without reproducible evidence
