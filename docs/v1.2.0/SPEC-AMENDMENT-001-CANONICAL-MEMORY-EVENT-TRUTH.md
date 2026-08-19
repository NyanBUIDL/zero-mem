# Spec Amendment 001 — Canonical Memory-Event Truth and Derived-State Boundary

**Applies to:** Zero-Mem v1.2 and later, unless superseded by a later approved amendment
**Status:** APPROVED
**Amends:** The storage/canonical-semantics portions of `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` only
**Related ADR:** `docs/v1.2.0/decisions/ADR-009-CANONICAL_MEMORY_EVENT_TRUTH_AND_DERIVED_STATE_BOUNDARY.md`

## 1. Authority and scope

The unified document `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` remains the authoritative product/system specification. This amendment does not replace that document and does not alter its product goals, sidecar boundary, provenance requirements, security requirements, profile/knowledge-space model, retrieval objectives, or release gates.

This amendment is an explicit, version-scoped refinement of storage and canonical-source semantics for Zero-Mem v1.2 onward. The v1.2 Master Plan does not override the unified specification by itself; this approved amendment is the governing refinement for the specified storage semantics.

The authority order for this refinement is:

```text
Unified Specification
        │
        ├── approved Spec Amendments / ADRs
        │
        ▼
v1.2 MASTER PLAN
        │
        ▼
WP-specific implementation plan
        │
        ▼
implementation
        │
        ▼
tests + acceptance evidence
        │
        ▼
verified project state
```

An ADR or amendment marked `PROPOSED` is design input for review, not executable implementation authority.

## 2. Refinement of the ambiguous wording

Effective from Zero-Mem v1.2, references in the unified specification to **“SQLite/JSONL canonical trace storage”**, **“SQLite/JSONL là canonical”**, or equivalent wording are refined as follows:

> JSONL is the canonical append-only source of truth for memory events/traces. SQLite and query/index projections are derived/materialized state rebuildable from canonical sources. Versioned artifacts may remain authoritative for their own artifact contents but are not the canonical memory-event stream.

This refinement removes dual-canonical ambiguity. It does not claim that SQLite is unimportant or that the unified specification's queryable metadata/lifecycle requirements disappear.

## 3. Storage semantics

### Layer 1 — Canonical Event Truth

The append-only JSONL event log is the **single canonical source of truth for memory events/traces**. It owns:

- append-only memory events;
- event identity;
- ordering and sequence;
- canonical provenance;
- historical event records;
- lifecycle events;
- references to artifacts where applicable.

A memory event is canonical durable state only after the canonical append succeeds under the applicable durability contract. Capture acknowledgement or projection success alone is insufficient. A capture success acknowledgement must not be based only on SQLite or another projection.

Canonical history is append-only. A later update, supersession, deletion, approval, or lifecycle transition is represented by an appropriate new event or linked record; it silently rewrites no historical event.

### Layer 2 — Derived / Materialized State

The following are derived/materialized state:

```text
SQLite
FTS
retrieval indexes
relationship/graph projections
dense/vector indexes, if introduced later
corpus indexes
materialized views
```

These components:

- are not canonical memory-event truth;
- must be rebuildable from canonical sources;
- may be stale, pending, missing, corrupt, or unavailable;
- must not silently modify canonical event history;
- must not make capture successful when canonical append failed.

SQLite may contain materialized query state, query-optimized structures, checkpoints, watermarks, projection metadata, and schema/migration metadata. The existence of those records does not make SQLite the canonical event log.

### Layer 3 — Versioned Artifacts

The versioned artifact store is a separate layer. An artifact store may be authoritative for the contents of a specific artifact, file, document, or external object version. That authority is limited to the artifact content itself.

The artifact store is not the canonical memory-event stream and does not replace JSONL history. References and provenance for an artifact must have a canonical representation in the event stream where the artifact participates in memory history. Artifact lifecycle must preserve the version and provenance rules of the unified specification.

Accordingly, **authoritative artifact content** must not be conflated with **canonical memory-event truth**.

### Layer 4 — Human-Facing Projection

Obsidian, Markdown projections, and other human-readable workspace views are rebuildable human-facing projections. They are not source of truth and are not the retrieval engine. They must not automatically write back into canonical state.

If a future approved feature supports write-back, the only valid semantic path is:

```text
Obsidian edit
→ proposed event
→ validation
→ authorization/policy
→ review/approval
→ canonical JSONL append
```

Direct Markdown edits must never directly mutate canonical truth.

## 4. Recovery invariant

The recovery direction is:

```text
Canonical JSONL
      ↓
Projection / Rebuild
      ↓
SQLite / FTS / indexes / graph / materialized views
```

Derived state must not rewrite canonical history:

```text
SQLite
   ↓
rewrite canonical JSONL history   [FORBIDDEN]
```

If derived state is missing, stale, corrupt, or schema-incompatible, the system must diagnose that condition according to its approved runtime contract and rebuild from canonical sources when valid. Derived state must not be reported as current unless its freshness/watermark proves that status for the requested consistency level.

This amendment does not implement the recovery contract or choose its future status vocabulary. Those details remain implementation/WP scope.

## 5. Capture invariant

The required semantic order is:

```text
capture request
      ↓
validation / redaction
      ↓
canonical JSONL append
      ↓
durability confirmation
      ↓
capture success
      ↓
projection
```

Projection failure after canonical durability does not make the canonical event nonexistent. The runtime must eventually expose a typed derived condition such as pending, stale, or unavailable according to the approved implementation contract. This amendment does not implement that contract.

## 6. Compatibility and historical preservation

The v1.1 verified history is not rewritten by this amendment. Historical acceptance evidence, release records, milestone records, and prior decisions retain the terminology and semantics that were applicable when they were produced. A historical reference to SQLite/JSONL as canonical is not silently mass-rewritten.

The refinement is prospective for v1.2+. Migration semantics, compatibility behavior for existing v1.1 stores, and any required data-preserving transition must be specified and verified by a later authorized work package. No destructive migration is implied by this amendment.

## 7. Non-goals

This amendment does not:

- implement WP-24 or any runtime work;
- change production source, tests, or schemas;
- migrate SQLite or JSONL data;
- select a vector database or graph database;
- change ranking or retrieval algorithms;
- modify Hermes or its hooks;
- add MCP or a sidecar transport;
- make Obsidian bidirectional or canonical;
- bump a release version, tag, publish, or push.

## 8. Approval gate

Approval is recorded. Implementation authorization remains separate:

```text
SPEC_AMENDMENT_STATUS = APPROVED
WP24_IMPLEMENTATION_AUTHORIZED = FALSE
```

Approval of this proposal authorizes governance synchronization for the approved storage semantics only. It does not authorize WP-24, migration, production source changes, tests/schema changes, release/version changes, or publication.
