# Work Package: WP-13 — Configuration and Runtime Ownership

**ID:** WP-13

**Title:** Configuration and Runtime Ownership


**Status:** NOT STARTED

**Priority:** P1

**Categories:** Configuration, API, Safety

## Related Findings

F-005, F-006, F-007, F-012. Related ADR: ADR-004.

## Read Scope

Read only the path, bridge configuration, runtime, setup, doctor, and integration configuration modules named in **Files / Modules to Inspect**, plus ADR-004.

## Planning Write Scope

V1.1.0 RE-PLANNING: documentation only — this work package, ADR-004, `TRACEABILITY.md`, and configuration design notes. No configuration or environment behavior write scope exists.

## Planning Files Allowed to Modify

This work package, ADR-004, `TRACEABILITY.md`, and configuration design Markdown only.

## Proposed Implementation Write Scope

**PROPOSED FOR A FUTURE AUTHORIZATION ONLY.** A maintainer may authorize only the minimum subset of the entries under **Files / Modules to Inspect**, plus directly associated tests and benchmarks required by this package's acceptance criteria. Every allowed path must be named explicitly when implementation is authorized; all other paths remain forbidden.

## Forbidden Scope

`zero_mem/`, `src/`, `tests/`, migrations, schemas, dependency metadata, runtime configuration, CI, and git tags.

## Objective

Create one typed, validated, immutable configuration contract shared by setup, runtime, integrations, doctor, and migration.

## Why This Exists

Configuration currently spans environment variables, path helpers, bridge configuration, descriptors, and mutable runtime globals. Defaults may select a home-directory path that bridge safety logic rejects, and adapter construction can replace process-wide runtime state. These are architectural causes of several higher-level reliability and multi-agent failures.

## Current State on master

- [`src/integration/bridge_config.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration/bridge_config.py) defines integration configuration behavior.
- [`zero_mem/paths.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/paths.py) resolves XDG/home-based locations.
- [`src/integration/zero_mem_runtime.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration/zero_mem_runtime.py) holds mutable global runtime state.
- Bridge/Hermes configuration applies additional safety rules.
- Setup, doctor, and runtime do not yet prove that they consume one identical effective configuration.

## Evidence

- **F-006:** module-global runtime can be overwritten by adapter constructors.
- **F-012:** default capture roots and bridge rejection rules can conflict.
- **F-007:** descriptor/version coupling introduces another configuration source.
- Configuration precedence and Windows native-directory behavior are **Needs verification**.

## Problems Found

- **F-006 — P1 — Runtime ownership:** mutable global configuration causes cross-adapter interference.
- **F-012 — P2 — Configuration safety:** a generated default may fail downstream validation.
- **F-007 — P1 — Integration configuration:** exact package version is treated as an integration contract.
- No single schema defines defaults, precedence, validation, redaction, and serialization.

## Affected Components

- Paths and profiles
- Runtime construction
- Setup and doctor
- Capture, ingestion, retrieval, and context policies
- Hermes and generic agent adapters
- Migration and diagnostics

## Files / Modules to Inspect

- [`src/integration/bridge_config.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration/bridge_config.py)
- [`src/corpus/config.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/corpus/config.py)
- [`zero_mem/paths.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/paths.py)
- [`src/integration/zero_mem_runtime.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration/zero_mem_runtime.py)
- [`zero_mem/commands_doctor.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/commands_doctor.py)
- [`zero_mem/commands_setup.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/commands_setup.py)
- Integration configuration files identified by WP-07

## Desired State

- One typed configuration schema defines every supported option and default.
- Precedence is deterministic: explicit constructor/CLI, environment, config file, platform default; the final approved order is documented once.
- Runtime configuration is immutable after construction.
- All paths are normalized, validated, and checked before mutation.
- Secret-bearing fields are marked and redacted from diagnostics.
- Configuration has a schema version and migration path.

## Constraints

- Existing environment variables require a documented deprecation/migration path.
- Platform-native directories differ and must follow WP-09.
- Configuration validation must not read or log memory payloads.
- Unknown fields should not be silently ignored.

## Required Changes

1. Inventory every current configuration source and option.
2. Define the typed v1.1.0 schema, defaults, precedence, and validation errors.
3. Make runtime instances own immutable effective configuration.
4. Route setup, doctor, API, and integrations through the same loader.
5. Add redacted configuration inspection and provenance output.
6. Define v1.0.0 alias/deprecation and migration behavior.

## Recommended Direction

Use a frozen configuration object constructed by a single loader. Resolve and validate all inputs once, record each effective value’s non-secret source, and inject the resulting object into runtime/services. Keep environment variables as input adapters, not live mutable state.

## Alternatives Considered

- **Continue module globals:** low code churn but preserves isolation and testing failures.
- **Environment variables only:** simple deployment story but poor typing, discoverability, and per-runtime isolation.
- **Integration-specific configuration models:** flexible locally but guarantees drift across adapters.

## Risks

- Changing defaults may make existing data appear missing if path migration is unclear.
- Overly strict validation can break previously tolerated but valid deployments.
- Diagnostic output can leak sensitive values without field-level redaction.

## Compatibility Impact

Existing keys should map to new fields where semantics are unambiguous. Removed or ambiguous keys require actionable errors, documented replacements, and the WP-17 compatibility window.

## Performance Impact

Configuration loading and path validation occur once per runtime. Per-operation environment reads, file parsing, or path probing are prohibited.

## Migration Impact

V1.0.0 configuration must be detected, translated, previewed, and backed up before writing a v1.1.0 form. Path changes require explicit confirmation or a no-copy reference to the existing location.

## Tests Required

### Existing Tests

- Current config, path, setup, doctor, and integration configuration tests under [`tests/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/tests).

### Missing Tests

- Complete precedence table tests.
- Unknown, malformed, and deprecated key behavior.
- Secret redaction and effective-source reporting.
- Two runtime instances with conflicting settings.
- Platform-native defaults and path normalization.
- Read-only configuration and data directories.

### Regression Tests

- Current valid environment variables resolve to equivalent effective settings.
- Defaults accepted by setup are accepted by runtime and bridge validation.
- Configuration inspection never includes memory payloads or secret values.

## Benchmarks Required

- Cold and warm configuration-load time.
- Runtime construction cost with and without optional integration config.
- Verification that steady-state capture/retrieval performs zero configuration-file reparses.

## Acceptance Criteria

- A machine-readable schema covers 100% of supported configuration fields.
- A precedence test exists for every field that can come from multiple sources.
- Two simultaneous runtimes retain independent immutable configurations.
- Setup, doctor, runtime, and adapters report the same normalized paths for the same input.
- Unknown fields fail with field name, source, and corrective action.
- Redaction tests prove designated secrets never appear in diagnostic output.

## Definition of Done

- The schema and precedence contract are approved.
- All runtime construction paths use the central loader.
- V1.0.0 compatibility mappings are implemented and documented.
- WP-09, WP-12, WP-14, WP-15, and WP-17 consume the same configuration contract.

## Dependencies

- WP-01 Architecture
- WP-02 Core Boundaries

## Blocks

- WP-04 Storage implementation details
- WP-07 Hermes Integration
- WP-08 Agent-Agnostic API
- WP-09 Compatibility and Portability
- WP-11 Sync and Async Execution
- WP-12 Multi-Agent Operation
- WP-14 Reliability and Recovery
- WP-15 Observability
- WP-17 Migration

## Out of Scope

- Remote configuration services
- Dynamic live reconfiguration of an existing runtime
- Secret-management infrastructure
- Integration-specific hidden defaults
