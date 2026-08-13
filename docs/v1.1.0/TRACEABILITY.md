# V1.1.0 Traceability — Planned Truth

Every v1.1.0 implementation change must trace to at least one reconciled finding or an approved goal. “Refactor” alone is not a valid reason. Each finding has exactly one primary closure owner; supporting WPs may supply prerequisites or shared validation but cannot independently close it.

| Finding / Goal | Reconciled status | ADR | Primary closure owner | Supporting WPs | Required validation | Release criterion |
|---|---|---|---|---|---|---|
| F-001 | CONFIRMED OPEN | [ADR-002](decisions/ADR-002-HERMES_ADAPTER_BOUNDARY.md) | WP-07 | WP-04, WP-08, WP-15 | Installed Hermes capture lifecycle with missing-writer diagnostic | Registration success guarantees a persistence path and declared freshness behavior |
| F-002 | CONFIRMED OPEN | [ADR-003](decisions/ADR-003-CANONICAL_STORAGE_AND_FRESHNESS.md) | WP-04 | WP-08, WP-14, WP-15 | Observe/sync/retrieve, lag, restart, idempotency | Canonical/derived consistency and freshness are explicit and visible |
| F-003 | CONFIRMED OPEN | [ADR-003](decisions/ADR-003-CANONICAL_STORAGE_AND_FRESHNESS.md) | WP-04 | WP-03, WP-16 | Bounded startup and checkpointed ingest benchmarks | Normal startup/incremental ingest do not reread/materialize all history |
| F-004 | CONFIRMED OPEN | [ADR-003](decisions/ADR-003-CANONICAL_STORAGE_AND_FRESHNESS.md) | WP-04 | WP-12, WP-14 | Multi-process writer/rejection, crash, sequence, dedupe tests | Shared writes are process-safe or deterministically rejected |
| F-005 | CONFIRMED OPEN | [ADR-004](decisions/ADR-004-CONFIGURATION_RUNTIME_OWNERSHIP.md) | WP-10 | WP-09, WP-16 | Exact-wheel install/setup/doctor/uninstall platform matrix | Claimed OS/Python combinations pass the published lifecycle |
| F-006 | CONFIRMED OPEN | [ADR-001](decisions/ADR-001-AGENT_AGNOSTIC_CORE.md), [ADR-004](decisions/ADR-004-CONFIGURATION_RUNTIME_OWNERSHIP.md) | WP-13 | WP-08, WP-12 | Multi-runtime isolation and configuration-owner tests | Runtime configuration is immutable per owner or conflicts are rejected |
| F-007 | CONFIRMED OPEN | [ADR-002](decisions/ADR-002-HERMES_ADAPTER_BOUNDARY.md) | WP-07 | WP-10, WP-17 | Descriptor compatibility and upgrade/revalidation matrix | Compatible package drift does not invalidate the adapter contract |
| F-008 | CONFIRMED OPEN | [ADR-005](decisions/ADR-005-BOUNDED_AUTHORIZED_RETRIEVAL.md) | WP-05 | WP-03, WP-06, WP-16 | Authorization-first candidate-count/RAM/latency tests | Context candidate discovery is bounded and policy-safe |
| F-009 | CONFIRMED OPEN | [ADR-005](decisions/ADR-005-BOUNDED_AUTHORIZED_RETRIEVAL.md) | WP-05 | WP-06, WP-16 | Ordering/currentness/conflict contract and gold-set quality tests | Context-facing ordering is deterministic, documented, and current-state aware |
| F-010 | CONFIRMED OPEN | [ADR-003](decisions/ADR-003-CANONICAL_STORAGE_AND_FRESHNESS.md) | WP-04 | WP-03, WP-11, WP-16 | Durability/batch throughput and crash-loss-window tests | Safe defaults and batching semantics meet approved budgets |
| F-011 | CONFIRMED OPEN | [ADR-001](decisions/ADR-001-AGENT_AGNOSTIC_CORE.md) | WP-08 | WP-02, WP-10, WP-18 | Installed generic-agent lifecycle using public imports only | External agents do not depend on internal `src.*` topology |
| F-012 | CONFIRMED OPEN | [ADR-004](decisions/ADR-004-CONFIGURATION_RUNTIME_OWNERSHIP.md) | WP-13 | WP-09, WP-10, WP-17 | Cross-platform path precedence/safety/setup composition | One data-root policy composes across setup and adapters |
| F-013 | CONFIRMED OPEN | [ADR-003](decisions/ADR-003-CANONICAL_STORAGE_AND_FRESHNESS.md), [ADR-004](decisions/ADR-004-CONFIGURATION_RUNTIME_OWNERSHIP.md) | WP-15 | WP-07, WP-14 | Content-safe health schema and failure/lag fault injection | Operators distinguish disabled, empty, stale, degraded, and failed states |
| F-014 | NEEDS VERIFICATION | [ADR-001](decisions/ADR-001-AGENT_AGNOSTIC_CORE.md), [ADR-003](decisions/ADR-003-CANONICAL_STORAGE_AND_FRESHNESS.md) | WP-11 | WP-03, WP-16 | Connection ownership, handle stability, latency, cancellation, event-loop responsiveness | Read-session ownership and sync/async behavior are explicit and bounded |
| Agent-agnostic product goal | Planned goal | [ADR-001](decisions/ADR-001-AGENT_AGNOSTIC_CORE.md) | WP-08 | WP-02, WP-18 | Public API lifecycle E2E | Generic agent uses only the stable public API |
| Release quality goal | Planned goal | Governed by [MASTER_PLAN.md](MASTER_PLAN.md) | WP-19 | WP-00, WP-16, WP-17, WP-18 | Exact-wheel matrix, migration/rollback, docs execution, benchmark suite | No open release blocker; every declared gate passes at the candidate SHA |

## Update Rule

When a finding status, owner, or approved goal changes, update this file, the findings reconciliation, its WP, any needed ADR, required tests/benchmarks, and the release criterion together before implementation begins.
