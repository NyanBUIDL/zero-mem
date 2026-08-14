# ADR-004: One Typed Configuration Contract

**Status:** PROPOSED

**Reconciliation:** RETAINED at exact master 78c4bb46b88b8ce9987c6882b24201e08b82a7f0; the one-commit post-tag delta does not change this ADR's code evidence. The decision remains proposed pending maintainer review.

## Context

Paths, setup, integration bridge configuration, descriptors, and runtime state currently form several partially overlapping configuration authorities. Defaults can conflict with safety rules and portability behavior.

## Decision

V1.1.0 will define one typed, validated configuration contract with deterministic precedence and immutable effective configuration per runtime. Platform support is an explicit tested matrix, not an inference from installer behavior.

## Why

This resolves the configuration boundary underlying F-005, F-006, and F-012.

## Consequences

- WP-13 owns schema/precedence/runtime configuration design.
- The schema includes profile/knowledge-space policy, local endpoint/transport, deadlines/limits, Obsidian managed root/review policy, and secret classification without hidden adapter defaults.
- WP-09/WP-10 consume the approved support and installation contract.
- Configuration migration is part of WP-17.

## Rejected Alternatives

- Environment variables and integration-specific defaults as independent live configuration systems.
- Making any platform supported without a passing lifecycle matrix.
