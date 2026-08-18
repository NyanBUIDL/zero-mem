# ADR-002: Hermes Is an Optional Adapter, Not the Core Contract

**Status:** PROPOSED

**Reconciliation:** RETAINED at exact master 78c4bb46b88b8ce9987c6882b24201e08b82a7f0; the one-commit post-tag delta does not change this ADR's code evidence. The decision remains proposed pending maintainer review.

## Context

The audited Hermes boundary can register capture without a configured writer, and its descriptor treats package-version equality as compatibility.

## Decision

Hermes will remain an optional client/adapter over the public lifecycle and capability API. It maps verified Hermes hooks to generic observations, invokes the four canonical read capabilities through the same embedded/local interface used by other agents, and never defines a competing contract. Registration must either own a configured persistence path or fail explicitly. Descriptor compatibility will be based on versioned adapter/boundary/capability contracts, with package version retained for diagnostics.

## Why

This closes F-001 and F-007 without making Hermes a core dependency for other agent hosts.

## Consequences

- WP-07 owns host mapping, registration, and descriptor migration.
- WP-08 must expose the required lifecycle/capability operations; WP-21 owns local transport behavior.
- Optional integration failure must be visible without crashing unrelated agent work.
- Read timeout/unavailable behavior fails open for Hermes control flow, while unauthorized reads and writes fail closed at the Zero-Mem boundary.

## Rejected Alternatives

- Allow registered hooks to silently drop events when a store is absent.
- Bind descriptor validity solely to package patch version.
- Add Hermes-specific storage, ranking, authorization, or MCP semantics to the core.
