# 00 — Guardrails and definition of “done”

## Authority and reading order

Before changing a package, read:

1. [`AGENTS.md`](../../../AGENTS.md).
2. [`docs/architecture/ARCHITECTURE.md`](../../architecture/ARCHITECTURE.md).
3. [Spec Amendment 001](../../v1.2.0/SPEC-AMENDMENT-001-CANONICAL-MEMORY-EVENT-TRUTH.md) and [ADR-009](../../v1.2.0/decisions/ADR-009-CANONICAL_MEMORY_EVENT_TRUTH_AND_DERIVED_STATE_BOUNDARY.md).
4. The selected row in [01-FINDING-REMEDIATION-LEDGER.md](01-FINDING-REMEDIATION-LEDGER.md).
5. [02-IMPLEMENTATION-PROTOCOL.md](02-IMPLEMENTATION-PROTOCOL.md) and the linked code/tests.

Before commit, push, tag, release or remote change, read [`docs/governance/GITHUB-POLICY.md`](../../governance/GITHUB-POLICY.md).

## Non-negotiable invariants

- JSONL is the single canonical append-only truth; SQLite/FTS/indexes are derived and rebuildable.
- `CAPTURED` requires a durable canonical receipt, never merely a projection result.
- Authorization happens before candidate discovery, freshness inspection or metadata disclosure.
- A public API never requires a consumer to import `src.*`, create a SQLite connection, know a storage path, or inject an internal-only service.
- Hermes remains orchestration/final action; Zero-Mem operates through explicit, owned boundaries.
- A platform is unsupported until its real CI/host matrix row passes. A local mock or skipped test is not qualification.
- A finding is closed only if the exact release SHA has code wiring, a public E2E proof, and a reproducible evidence bundle.

## Three-proof closure rule

Every ledger row needs all three proofs:

```text
1. WIRING: production code reaches the correct single owner.
2. BEHAVIOR: a black-box E2E test exercises the public entrypoint.
3. PROVENANCE: exact-SHA evidence and raw log are accessible from the release tag.
```

If any proof is absent, use `OPEN`, `PARTIAL`, `DEFERRED_WITH_AUTHORITY`, or `LINUX_ONLY`; never use `CLOSED_VERIFIED`.

## Stop conditions

Stop for maintainer decision when a change would introduce a new public API name, modify canonical event format, weaken authorization, rely on an untested filesystem primitive, or require rewriting a published tag/release. Do not convert an evidence gap into a documentation claim.
