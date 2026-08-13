# ADR-002: Hermes Is an Optional Adapter, Not the Core Contract

**Status:** PROPOSED

**Reconciliation:** RETAINED at exact master 78c4bb46b88b8ce9987c6882b24201e08b82a7f0; the one-commit post-tag delta does not change this ADR's code evidence. The decision remains proposed pending maintainer review.

## Context

The audited Hermes boundary can register capture without a configured writer, and its descriptor treats package-version equality as compatibility.

## Decision

Hermes will remain an optional adapter over the public lifecycle API. Registration must either own a configured persistence path or fail explicitly. Descriptor compatibility will be based on a versioned adapter/boundary contract, with package version retained for diagnostics.

## Why

This closes F-001 and F-007 without making Hermes a core dependency for other agent hosts.

## Consequences

- WP-07 owns host mapping, registration, and descriptor migration.
- WP-08 must expose the required public lifecycle operations.
- Optional integration failure must be visible without crashing unrelated agent work.

## Rejected Alternatives

- Allow registered hooks to silently drop events when a store is absent.
- Bind descriptor validity solely to package patch version.
