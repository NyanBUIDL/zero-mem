# Work Package: WP-17 — Migration from v1.0.0 to v1.1.0

**ID:** WP-17

**Title:** Migration from v1.0.0 to v1.1.0


**Status:** NOT STARTED

**Priority:** P1

**Categories:** Migration, Compatibility, Data Safety

## Related Findings

F-002, F-007, F-011, F-012. Related ADRs: ADR-001 through ADR-004.

## Canonical Requirements

REQ-MIG-001 through REQ-MIG-006 and REQ-STORE-005/006 in `SPEC_TRACEABILITY.md`; canonical DOCX §§9.3, 14.3–14.4, 16.4, 19; ADR-001 through ADR-008.

## Read Scope

Read only upgrade, backup, path, configuration, storage, public package, descriptor, and test material named in **Files / Modules to Inspect**.

## Planning Write Scope

V1.1.0 RE-PLANNING: documentation only — this work package, migration/rollback runbook drafts under `docs/`, and `TRACEABILITY.md`. No migration, schema, backup, configuration, or package write scope exists.

## Planning Files Allowed to Modify

This work package, migration/rollback runbook Markdown under `docs/`, and `TRACEABILITY.md` only.

## Proposed Implementation Write Scope

**PROPOSED FOR A FUTURE AUTHORIZATION ONLY.** A maintainer may authorize only the minimum subset of the entries under **Files / Modules to Inspect**, plus directly associated tests and benchmarks required by this package's acceptance criteria. Every allowed path must be named explicitly when implementation is authorized; all other paths remain forbidden.

## Forbidden Scope

`zero_mem/`, `src/`, `tests/`, `packaging/`, migrations, schemas, dependency metadata, runtime configuration, CI, and git tags.

## Objective

Provide a reversible, verifiable migration from Zero-Mem v1.0.0 data, configuration, integrations, and API usage to v1.1.0.

## Why This Exists

V1.1.0 changes architectural boundaries, configuration ownership, public APIs, storage lifecycle, integration contracts, and packaging. Even where canonical JSONL remains unchanged, derived state, descriptors, defaults, and callers can become incompatible. Upgrade must preserve user memories and offer a tested rollback path.

## Current State on master

- [`zero_mem/upgrade.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/upgrade.py) and [`zero_mem/backup.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/backup.py) provide existing upgrade/backup mechanisms.
- Canonical JSONL and derived SQLite have distinct lifecycles.
- Hermes descriptors can bind exact package versions.
- Public operational APIs are not stable at the package top level.
- Path defaults and runtime configuration are distributed across modules/integrations.

## Evidence

- **F-002:** no explicit canonical-to-derived consistency lifecycle.
- **F-007:** exact-version Hermes descriptor binding can break upgrade compatibility.
- **F-011:** callers can rely on private `src.*` APIs.
- **F-012:** path/default validation conflicts can make state appear relocated or invalid.
- The audited report did not prove an end-to-end populated v1.0.0 → v1.1.0 → rollback cycle; this is **Needs verification**.

## Problems Found

- **F-002 — P1 — Data migration:** derived state cannot be assumed current or authoritative.
- **F-007 — P1 — Integration migration:** descriptor compatibility is tied too tightly to package version.
- **F-011 — P1 roadmap / P2 current — API migration:** internal imports need a supported transition.
- **F-012 — P2 — Path migration:** changed resolution/validation can strand existing profiles.
- Schema/config/API migration order and rollback checkpoints are not defined.

## Affected Components

- Canonical JSONL and derived SQLite
- Configuration and profile paths
- Runtime/API construction
- Hermes descriptors/hooks
- Packaging and version metadata
- Backup, doctor, and status

## Files / Modules to Inspect

- [`zero_mem/upgrade.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/upgrade.py)
- [`zero_mem/backup.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/backup.py)
- [`src/integration/bridge_config.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/integration/bridge_config.py)
- [`zero_mem/paths.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/paths.py)
- [`src/storage/sqlite_store.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/src/storage/sqlite_store.py)
- [`zero_mem/__init__.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/__init__.py)
- Hermes integration files identified by WP-07

## Desired State

- Migration starts with read-only discovery and a human/machine-readable plan.
- A verified backup is created before the first mutation.
- Canonical v1.0.0 records are preserved byte-for-byte unless an explicit canonical format migration is approved.
- Derived state is migrated or rebuilt from canonical state with a verified watermark.
- Configuration and paths are translated without silently moving data.
- Integration descriptors and API imports have explicit compatibility/deprecation handling.
- Rollback is tested with populated, empty, stale-derived, and partially damaged fixtures.
- Existing profile/grant/access-mode configuration, local service/Hermes descriptors, M9 projection manifests/human edits, review candidates/write-back records, and Vault managed-root ownership migrate without silent scope or file changes.

## Constraints

- The v1.0.0 baseline is commit `79989f34ce3578f275a7b910c8a189896ce9ad57`.
- Canonical data must never be discarded because derived data is missing or inconsistent.
- Migration must be restartable and idempotent.
- A schema change not already approved in WP-04 requires separate design review.

## Required Changes

1. Inventory v1.0.0 data, schema, config, descriptor, and import forms.
2. Define migration stages, durable checkpoints, version markers, and idempotency keys.
3. Implement read-only preflight and disk-space/permission checks.
4. Create and verify backup before mutation.
5. Translate configuration and integration descriptors.
6. Rebuild or migrate derived state and compare logical record counts/identities.
7. Add rollback and interrupted-migration recovery.
8. Document internal-import deprecations and compatibility shims.
9. Migrate/validate the composite canonical contract, local interface contract version, profile modes, Obsidian projection/review state, and exact-master M6/M9 compatibility.

## Recommended Direction

Use a staged migration: discover → validate → plan → backup → migrate configuration/metadata → rebuild derived state → verify → activate. Keep the original canonical source and configuration backup until the user explicitly accepts the upgraded state. Prefer rebuilding disposable SQLite state over complex in-place transformation when benchmarks show it is practical.

## Alternatives Considered

- **In-place, no-backup upgrade:** faster but unacceptable for memory data.
- **Copy all data to new defaults automatically:** can duplicate large stores and make rollback/path ownership unclear.
- **Maintain all internal APIs indefinitely:** avoids caller changes but prevents a stable boundary and increases maintenance.

## Risks

- Insufficient disk space can leave both old and new state incomplete.
- Path normalization changes can target the wrong profile.
- Rebuilding from a malformed canonical tail can stop mid-migration.
- Exact-version integration metadata can disable capture after package upgrade.

## Compatibility Impact

V1.0.0 public/documented behavior receives either direct compatibility or a documented migration. Private imports may receive temporary shims only where low risk; shim removal dates must be explicit.

## Performance Impact

Migration duration is corpus-dependent. It must stream or batch rather than load the full corpus, report progress, and stay within a release-approved memory bound. Numeric time expectations come from WP-16 measurements.

## Migration Impact

This work package is the migration contract. It covers data, derived indexes, configuration, paths, descriptors, package/API consumers, backup, activation, and rollback.

## Tests Required

### Existing Tests

- Current upgrade, backup, config, storage, setup, and integration tests under [`tests/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/tests).

### Missing Tests

- Golden populated v1.0.0 fixtures at multiple corpus sizes.
- Empty profile, stale/missing derived DB, malformed tail, and non-default paths.
- Interrupted migration at every durable checkpoint.
- Insufficient disk space and read-only source/target.
- Descriptor/API compatibility and deprecation paths.
- Rollback followed by successful v1.0.0 read and subsequent retry.

### Regression Tests

- Canonical record hashes remain unchanged when no canonical format migration is approved.
- Logical record count and stable identities match before/after.
- Running migration twice produces no duplicate records or repeated descriptor entries.
- Existing non-default profile paths remain selected unless explicitly changed.
- Existing M9 managed/human files remain preserved; human edits become review candidates/conflicts rather than overwrite; projection can be rebuilt after migration.
- Local service/Hermes and generic clients negotiate the documented contract/alias window; unsupported versions fail before mutation.

## Security / Privacy, Observability, and Rollback

Preflight validates path/endpoint/profile/write/Vault boundaries and never logs secret configuration or note content. Progress exposes stage/watermark/counts safely. Rollback restores v1.0-readable canonical/config/descriptor/projection state and keeps approved append records; it never silently downgrades or purges user data.

## Exit Gate and Traceability

Exit requires populated/empty/stale/missing/corrupt/non-default/interrupted fixtures covering data, indexes, config, profiles, clients, Hermes, projection, review/write-back and rollback, with all REQ-MIG rows `COVERED`.

## Benchmarks Required

- Preflight, backup, derived rebuild, verification, and rollback time separately.
- Peak memory and temporary disk overhead at 1k, 5k, 10k, and release large-corpus scale.
- Restart time after interruption.
- Comparison of rebuild versus safe in-place derived migration if both are candidates.

## Acceptance Criteria

- Preflight makes zero mutations and reports source/target versions, paths, counts, required space, and planned actions.
- A verified backup exists before the first mutation.
- For all valid golden fixtures, canonical hashes and logical record identities match after migration.
- Every interruption checkpoint can resume or roll back without duplicate/lost records.
- Rollback restores a state readable by v1.0.0 and passes its approved smoke suite.
- Migration never changes a profile path without explicit user selection.

## Definition of Done

- Migration and rollback runbooks are approved.
- All fixture, interruption, idempotency, and data-integrity tests pass.
- Deprecations and compatibility windows are published.
- Exact release artifacts complete v1.0.0 → v1.1.0 → rollback qualification.

## Dependencies

- WP-00 Baseline
- WP-04 Storage
- WP-07 Hermes Integration
- WP-08 Agent-Agnostic API
- WP-09 Compatibility and Portability
- WP-13 Configuration
- WP-14 Reliability and Recovery
- WP-20 Profiles and Knowledge Spaces
- WP-21 Local Sidecar and MCP Interface
- WP-22 Obsidian Knowledge Workspace design

## Blocks

- WP-10 Installation and Packaging final lifecycle
- WP-16 Testing and Benchmarks final migration suite
- WP-18 Documentation and Developer Experience
- WP-19 Release Readiness

## Out of Scope

- Import from unrelated memory products
- Destructive canonical-format rewrite without separate approval
- Automatic deletion of backups
- Remote migration orchestration
