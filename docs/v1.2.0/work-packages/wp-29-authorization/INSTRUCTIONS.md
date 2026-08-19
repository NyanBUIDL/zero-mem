# WP-29 Instructions

## Objective

Guarantee authorization-first read behavior: explicit identity and effective grants are resolved before candidate discovery, unauthorized candidates cannot affect results, and scope isolation is preserved across all read surfaces.

## Dependencies

- WP-28 Public API — VERIFIED.
- WP-25 Runtime Ownership and WP-26 Projection — VERIFIED prerequisites.

## Scope

- Normalize `AccessRequest` and grant identity.
- Compose effective profile/project/knowledge-space scopes.
- Gate structured, trace, search, project-memory, corpus, and linked reads before low-level query.
- Enforce deterministic scope filtering, ordering, pagination, and sanitized denial/error behavior.
- Add leakage-negative and scope-isolation tests.

## Out of scope

Sidecar transport (WP-30), Hermes integration (WP-31), context assembly/ranking (WP-32), retrieval evolution (WP-33), profile/Obsidian projection (WP-34), new external identity provider, and destructive schema migration.

## Required invariants

- Authorization precedes candidate discovery, ranking, count, pagination, and serialization.
- Unauthorized rows cannot influence score, count, cursor, ordering, identifiers, error behavior, or scope metadata.
- Identity is explicit and never inferred.
- READ and WRITE grants are distinct; revoked/deleted/non-authorizing grants fail closed.
- Derived indexes remain derived; authorization does not mutate canonical JSONL.
- Deterministic ordering and sanitized reason codes are preserved.

## Allowed changes

Existing `src/access` contracts, grants, resolver, policy, authorized-read facade, narrow read adapters required for authorization-first parity, and focused tests/docs/evidence.

## Prohibited changes

Retrieve-all-then-filter, caller self-authorization, authorization in sidecar/Hermes, raw SQL exposure, secret/error leakage, new dependency, vector/ranking implementation, canonical rewrite, or future-WP transport/context features.

## Escalation conditions

Escalate if authorization requires weakening an approved security invariant, changing canonical scope semantics, adding an identity trust boundary, introducing a new storage authority, or if any leakage-negative test cannot be made pass without architecture change.

## Completion conditions

All read surfaces gate before discovery; leakage-negative and scope-isolation evidence passes; public API parity remains; focused/full regression passes; independent fail-closed review passes; project state is `VERIFIED`.
