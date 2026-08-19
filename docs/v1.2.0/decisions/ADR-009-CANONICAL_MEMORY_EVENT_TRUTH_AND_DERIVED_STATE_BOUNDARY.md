# ADR-009: Canonical Memory-Event Truth and Derived-State Boundary

**Status:** ACCEPTED
**Scope:** Zero-Mem v1.2 and later
**Related proposal:** `docs/v1.2.0/SPEC-AMENDMENT-001-CANONICAL-MEMORY-EVENT-TRUTH.md`

## Context

The unified specification currently uses wording equivalent to **“SQLite/JSONL canonical trace storage”** and describes SQLite metadata/lifecycle together with append-first JSONL. The v1.2 Master Plan states a corrective architecture in which JSONL is canonical event truth and SQLite is derived state. Existing v1.1 ADR-003 deliberately preserved the earlier composite wording and is historical v1.1 planning evidence.

Without an explicit refinement, the two active-looking descriptions permit two competing interpretations of canonical memory-event truth. That creates split-brain risk for capture acknowledgement, recovery direction, freshness, provenance, migration, and corruption handling.

The repository also contains implementation and acceptance evidence that already distinguishes JSONL canonical event history from derived SQLite projections in several v1.1 paths. That evidence is corroborating implementation/history, not authority to rewrite the unified specification or v1.1 records.

## Decision

The approved decision is:

1. **JSONL is the single canonical append-only source of truth for memory events/traces for Zero-Mem v1.2+.** It owns event identity, ordering/sequence, provenance, historical records, lifecycle events, and artifact references.
2. **SQLite, FTS, retrieval indexes, graph projections, future vector indexes, corpus indexes, and materialized views are derived/materialized state.** They are rebuildable from canonical sources, may lag or be unavailable, and must never silently rewrite canonical event history.
3. **SQLite may hold query-optimized state and projection metadata**—including checkpoints, watermarks, and schema/migration metadata—without becoming the canonical event log.
4. **Versioned artifacts have separate authority for their own artifact contents.** Artifact authority does not make the artifact store the canonical memory-event stream.
5. **Obsidian and Markdown are human-facing rebuildable projections.** They are not canonical state or the retrieval engine. Future write-back, if approved, must become a proposed event and pass validation, authorization, review/approval, and canonical JSONL append.
6. **Capture success requires canonical durability.** Projection success cannot substitute for canonical append success. Projection failure after canonical durability preserves the event and yields a typed derived pending/stale/unavailable condition under the later implementation contract.
7. **Recovery is one-way from canonical JSONL to derived state.** Derived state is diagnosed and rebuilt from canonical sources; it never rewrites canonical JSONL history.

The amendment is prospective for v1.2+. It does not retroactively rewrite verified v1.1 history or historical acceptance evidence.

## Rationale

This decision:

- eliminates dual-canonical ambiguity;
- prevents split-brain capture and recovery semantics;
- gives deterministic recovery and rebuildability;
- preserves durable capture semantics and provenance;
- makes ownership of event history, artifacts, projections, and indexes explicit;
- isolates derived corruption from canonical history;
- permits SQLite/index implementations to evolve independently;
- supports future retrieval/index replacement without changing canonical memory truth.

## Consequences

- Capture success depends on canonical JSONL durability, not SQLite/projection success.
- Projection may lag canonical append and must expose freshness/watermark state through a later approved contract.
- Derived state can be missing, stale, corrupt, or unavailable without implying canonical loss.
- Derived indexes and projections can be dropped and rebuilt from canonical sources.
- Retrieval must account for derived freshness before claiming currentness.
- Recovery and migration work must preserve canonical JSONL and define compatibility for existing v1.1 stores.
- Existing v1.1 terminology and evidence remain historical and are not mass-rewritten.
- Active governance documents that still state SQLite and JSONL are co-canonical require synchronization only after this proposal is approved.

## Non-goals

This ADR does not:

- implement WP-24, `AppendReceipt`, `ZeroMemRuntime`, public API, authorization, sidecar, or Hermes hook behavior;
- change production source code, tests, or SQLite schema;
- run or authorize a migration;
- select a vector store, graph database, ranking algorithm, or transport;
- change Obsidian into a bidirectional canonical store;
- bump, tag, publish, or push a release.

## Authority and approval semantics

The unified specification remains the product/system authority. This accepted ADR and its approved companion Spec Amendment refine the unified specification only for the stated v1.2+ storage semantics. The v1.2 Master Plan is consistent corrective planning input but is not itself an override.

Implementation authorization remains separate. Approval of this ADR and amendment does not authorize WP-24, migration, production source changes, release changes, or any other v1.2 runtime implementation.

```text
SPEC_AMENDMENT_STATUS = APPROVED
WP24_IMPLEMENTATION_AUTHORIZED = FALSE
```

## Required follow-up after approval

The next permitted governance action is to synchronize active governance documents with the approved amendment and verify repository-wide consistency. That action must remain separate from preparing or implementing WP-24. Historical v1.1 records must remain unchanged.
