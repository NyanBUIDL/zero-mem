# Work Package: WP-20 — Profiles and Knowledge Spaces

**ID:** WP-20

**Status:** NOT STARTED

**Priority:** P1

## Objective

Implement the canonical profile/knowledge-space policy and all five retrieval modes without leakage, hidden fallback, or coupling behavior profiles to data scopes.

## Why

Exact master has grants, profile/project/knowledge-space filters, `isolated_mode`, and global-read behavior, but no single public v1.1.0 contract for `profile_first`, `explicit_union`, `isolated`, `global`, and `source_restricted`. Existing WP-12 text also contradicted the default global/profile-first policy.

## Canonical Requirements and Sources

REQ-PROF-001 through REQ-PROF-010 in `SPEC_TRACEABILITY.md`; canonical DOCX §§8.1–8.5, 11.2, 12.5, 17.1, 19.2–19.3, 21.1 and Appendix B; ADR-005 and ADR-007; `PROFILE_KNOWLEDGE_SPACE_CONTRACT.md`.

## Scope

- Profile and knowledge-space typed models, versioning, priorities, privacy/evidence/write policies.
- Authorization-first mode resolution and deterministic fallback/union/dedupe semantics.
- Cross-profile read versus write separation and policy diagnostics.
- Mode conformance tests across memory, corpus, links, conflicts, API/MCP, generic client, Hermes, and Obsidian projection.

## Out of Scope

Physical multi-process writer isolation (WP-12), retrieval scoring implementation (WP-05), transport framing (WP-21), and Obsidian file layout/write-back (WP-22).

## Dependencies

WP-01, WP-02, WP-05 design, WP-13 configuration, ADR-007.

## Architecture Constraints

Profiles are policies, not directories; authorization precedes influence; isolated/source-restricted modes never fall back; default reads are authorized global/profile-first and bounded; cross-profile writes require explicit WRITE authorization and review; no identity inference or process-global active profile.

## Files / Components Expected to Change

Future authorization may name the minimum subset of `src/access/**`, profile/config contracts, retrieval request types, public API types, and directly associated tests/benchmarks. Exact paths require maintainer authorization.

## Files / Components That Must Not Change

Hermes core, raw trace payloads, unrelated storage/packaging, or any executable path before authorization. Planning phase permits only `docs/**`.

## Implementation Tasks

1. Inventory exact-master access/grant/profile fields and freeze compatibility mappings.
2. Implement the normative mode resolver from `PROFILE_KNOWLEDGE_SPACE_CONTRACT.md`.
3. Separate behavior, active/requesting profile, targets, spaces, source filters, privacy ceiling, and evidence budget.
4. Bind resolved allowed scopes into WP-05/WP-08 without duplicating authorization.
5. Add versioned profile/config migration and profile/knowledge-system operator workflows.
6. Add content-safe scope/fallback diagnostics and full conformance fixtures.

## Acceptance Criteria

- Each mode passes every Given/When/Then scenario in `PROFILE_KNOWLEDGE_SPACE_CONTRACT.md`.
- `profile_first` uses one bounded authorized fallback and never lets unauthorized profiles influence scores/counts.
- `explicit_union` is order-independent, canonical-ID deduplicated, provenance-preserving, and all-or-nothing authorized.
- `isolated` and `source_restricted` leak no content, identifier, count, link, conflict, dense score, cache state, or timing-class distinction outside approved tolerances.
- Default `general-assistant` semantics match the canonical global/profile-first configuration.
- Cross-profile read never creates cross-profile WRITE authority.

## Negative and Regression Tests

Privilege fields, malformed mode, hidden profile, revoked grant, linked-resource escape, cache contamination, concurrent callers, reversed union order, pagination, timeout, source traversal, and transport/adapter parity. Preserve exact-master M5/M6 authorization-before-influence behavior.

## Migration and Compatibility Impact

Map existing `isolated_mode`, `include_global`, target profiles, knowledge spaces, grants, and default-profile settings to the versioned contract without silently changing effective scope. Ambiguous legacy combinations fail with a migration action.

## Security / Privacy Impact

Primary security boundary. Local/global access never raises privacy ceiling; unknown/hidden scopes are non-probing; diagnostics contain no memory content or secret identifiers.

## Performance Impact and Benchmarks

Measure candidate counts, query count, latency, and peak memory for every mode at 1k/10k and approved large scale. Fallback and unions remain within the global candidate/evidence budget.

## Observability

Expose active mode, authorized scope count, fallback used, omitted count, and safe deny/error code; never list hidden scopes by default.

## Rollback

Profile policy/config versions are backed up and reversible. Derived caches/indexes may be rebuilt; canonical traces are not rewritten. Rollback restores the prior resolver/version and re-runs isolation tests.

## Exit Gate and Traceability

Exit requires ADR-007 approval, all mode conformance/security/performance tests passing through embedded and local-service paths, migration proof, and `SPEC_TRACEABILITY.md` rows REQ-PROF-001..010 at `COVERED` with linked evidence.

## Planning and Implementation Authorization

This package is design-only in the current phase. Proposed source/test scopes are not authorization.
