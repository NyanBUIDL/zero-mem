# Work Package: WP-10 — Installation and Packaging

**ID:** WP-10

**Title:** Installation and Packaging


**Status:** NOT STARTED

**Priority:** P1

**Categories:** Packaging, Installation, Distribution

## Related Findings

F-005, F-007, F-011. Related ADRs: ADR-001, ADR-002, ADR-004.

## Read Scope

Read only package metadata, packaging scripts, CLI modules, integration descriptor material, and tests named in **Files / Modules to Inspect**.

## Planning Write Scope

V1.1.0 RE-PLANNING: documentation only — this work package, installation runbooks under `docs/`, and `TRACEABILITY.md`. No package, installer, CLI, dependency, or artifact write scope exists.

## Planning Files Allowed to Modify

This work package, installation runbook Markdown under `docs/`, and `TRACEABILITY.md` only.

## Proposed Implementation Write Scope

**PROPOSED FOR A FUTURE AUTHORIZATION ONLY.** A maintainer may authorize only the minimum subset of the entries under **Files / Modules to Inspect**, plus directly associated tests and benchmarks required by this package's acceptance criteria. Every allowed path must be named explicitly when implementation is authorized; all other paths remain forbidden.

## Forbidden Scope

`zero_mem/`, `src/`, `tests/`, `packaging/`, migrations, schemas, dependency metadata, runtime configuration, CI, and git tags.

## Objective

Deliver a repeatable, platform-aware installation, upgrade, verification, and removal experience for Zero-Mem v1.1.0.

## Why This Exists

The current repository mixes Python packaging with shell-driven setup and environment-specific integration steps. The audited installer assumes a POSIX virtual environment and the package does not yet expose a stable top-level operational API. Installation must become a controlled path into a verifiable runtime rather than a sequence of implicit repository operations.

## Current State on master

- [`pyproject.toml`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/pyproject.toml) defines the Python package and version constraints.
- [`packaging/install.sh`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/packaging/install.sh) performs repository-oriented setup with POSIX assumptions.
- [`zero_mem/commands_setup.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/commands_setup.py) and [`zero_mem/commands_doctor.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/commands_doctor.py) cover parts of initialization and validation.
- Hermes integration includes a descriptor tied to package metadata and version behavior.
- The public package surface is incomplete; operational callers may import internal `src.*` modules.

## Evidence

- **F-005:** installer hard-codes `venv/bin` and is not a native Windows installation path.
- **F-007:** Hermes descriptor compatibility is bound to an exact package version.
- **F-011:** no stable public operational API is exported from `zero_mem`.
- Audit setup timing was approximately **169 ms** and doctor timing **202 ms** on Windows/CPython 3.14; supported-platform timings are **Needs verification**.

## Problems Found

- **F-005 — P1 — Installation:** setup behavior is not portable or support-matrix driven.
- **F-007 — P1 — Integration packaging:** exact-version descriptor binding can invalidate a compatible upgrade.
- **F-011 — P1 roadmap / P2 current — API packaging:** examples and integrations can depend on internal module layout.
- Upgrade and uninstall behaviors are not specified as transactional operations.

## Affected Components

- Python wheel and source distribution
- Command-line entry points
- Setup, doctor, upgrade, backup, and removal commands
- Hermes adapter/descriptor installation
- Offline or air-gapped installation assets
- Release artifact generation

## Files / Modules to Inspect

- [`pyproject.toml`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/pyproject.toml)
- [`packaging/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/packaging)
- [`zero_mem/__init__.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/__init__.py)
- [`zero_mem/commands_setup.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/commands_setup.py)
- [`zero_mem/commands_doctor.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/commands_doctor.py)
- [`zero_mem/upgrade.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/upgrade.py)
- [`zero_mem/backup.py`](https://github.com/NyanBUIDL/zero-mem/blob/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/zero_mem/backup.py)
- Hermes integration files identified by WP-07

## Desired State

- A wheel is the primary install unit; repository scripts are optional wrappers.
- Setup and doctor are exposed through stable, documented commands.
- Platform-aware executable and data paths come from WP-09 and WP-13.
- Installation is idempotent and does not overwrite user data.
- Upgrade creates a recoverable checkpoint before mutation.
- Removal distinguishes package uninstall from explicit data deletion.

## Constraints

- Installation must work without importing private `src.*` paths.
- Existing v1.0.0 data must remain recoverable throughout upgrade.
- Hermes-specific setup must remain optional.
- Publishing to a public package index is **Needs verification** and requires owner approval.

## Required Changes

1. Define wheel/sdist build and metadata validation.
2. Define stable CLI entry points for setup, doctor, upgrade, backup, and status.
3. Replace hard-coded virtual-environment paths.
4. Make install/setup idempotent and safe with pre-existing data.
5. Version integration descriptors by compatible contract, not exact patch identity.
6. Add artifact integrity, clean-machine, upgrade, and uninstall tests.
7. Document offline installation requirements if supported.

## Recommended Direction

Use standard Python packaging as the source of truth and keep shell/PowerShell scripts as thin launchers. Build once, test the exact wheel in every release matrix job, and run all lifecycle tests against that artifact rather than an editable checkout.

## Alternatives Considered

- **Script-only distribution:** easy for repository users, but weak for provenance, rollback, and cross-platform behavior.
- **Container-only distribution:** reproducible, but does not satisfy local agent integration needs.
- **One monolithic installer:** can hide complexity, but increases platform-specific maintenance and trust requirements.

## Risks

- Package metadata, CLI behavior, and integration descriptors can drift.
- Uninstall logic can accidentally imply deletion of user memories.
- Editable-install tests can pass while wheel contents are incomplete.

## Compatibility Impact

Moving callers to a supported CLI/public API may deprecate internal imports. The deprecation window and compatibility shims are owned by WP-08 and WP-17.

## Performance Impact

Installation is not latency critical, but setup and doctor must remain suitable for interactive use. Regression thresholds are derived in WP-16; each command must avoid repeated full-corpus work.

## Migration Impact

The v1.1.0 installer must detect v1.0.0 state, invoke the WP-17 migration path, and preserve rollback artifacts. It must never interpret package uninstall as permission to erase stored data.

## Tests Required

### Existing Tests

- Existing setup, doctor, upgrade, backup, and integration tests under [`tests/`](https://github.com/NyanBUIDL/zero-mem/tree/78c4bb46b88b8ce9987c6882b24201e08b82a7f0/tests).

### Missing Tests

- Build and inspect wheel/sdist contents.
- Install exact wheel in clean supported environments.
- Repeat install and setup without duplication or data loss.
- Upgrade populated v1.0.0 fixtures.
- Package uninstall with data retained.
- Optional explicit data-removal flow with confirmation.
- Corrupt/incomplete artifact and interrupted setup behavior.

### Regression Tests

- Existing CLI options retain documented meanings.
- Hermes is not installed or modified when its optional integration is disabled.
- Doctor can identify package/runtime/config/schema versions after installation.

## Benchmarks Required

- Wheel build and install duration.
- Setup and doctor duration on each supported matrix row.
- Upgrade duration at the WP-16 corpus sizes.
- Artifact size and installed footprint, tracked release over release.

## Acceptance Criteria

- The exact release wheel passes the full lifecycle on every supported matrix row.
- A second setup run makes zero destructive changes and does not duplicate hooks or records.
- Unsupported environments fail before creating or modifying user state.
- Uninstall leaves user data intact unless an explicit, separately confirmed purge command is used.
- Artifact inspection confirms all required modules, migrations, descriptors, licenses, and typing metadata are present.
- All documented examples import only supported package paths.

## Definition of Done

- Release artifacts are reproducible from a tagged source revision.
- SHA-256 hashes and build provenance are recorded.
- Clean install, upgrade, rollback, and uninstall evidence is attached to WP-19.
- Public registry publication status is either completed or explicitly marked not part of v1.1.0.

## Dependencies

- WP-07 Hermes Integration
- WP-08 Agent-Agnostic API
- WP-09 Compatibility and Portability
- WP-13 Configuration
- WP-17 Migration for final upgrade implementation

## Blocks

- WP-18 Documentation and Developer Experience
- WP-19 Release Readiness

## Out of Scope

- Operating-system app-store distribution
- Automatic privileged system-wide installation
- Silent deletion of user data
- Public registry publication without explicit maintainer approval
