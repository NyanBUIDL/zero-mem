# ADR-003: Composite Canonical Trace Contract with Explicit Derived Freshness

**Status:** PROPOSED

**Reconciliation:** RETAINED at exact master 78c4bb46b88b8ce9987c6882b24201e08b82a7f0; the one-commit post-tag delta does not change this ADR's code evidence. The decision remains proposed pending maintainer review.

## Canonical Source and Context

The canonical DOCX §§1, 4.1, 9.1–9.3, 16.1, and 21.1 defines the canonical trace store as SQLite + JSONL, with raw events append-first and search/index/projection layers rebuildable. V1.0.0 implementation truth treats sanitized JSONL as the durable canonical event source and SQLite/FTS as rebuildable. Capture and derived ingestion have separate lifecycles; startup/ingest reread history and canonical writes have only process-local coordination. Planning must preserve this product/implementation distinction rather than silently calling all SQLite either canonical or derived.

## Decision

V1.1.0 will implement the canonical trace system as:

- append-first sanitized JSONL event/write-back records and versioned artifacts as the durable replay source and immutable raw provenance;
- queryable canonical SQLite tables for trace metadata, lifecycle, provenance, relations, task/decision state, and approved write-back state, updated through a declared commit/recovery protocol;
- disposable/rebuildable FTS, vector, graph, ranking, cache, and Obsidian projection state.

The SQLite canonical tables remain reproducible from the durable append-first records plus approved configuration/schema migrations; this replay proof is a recovery invariant, not permission to treat stale or partial SQLite state as authoritative. A public write outcome states whether the append committed and whether canonical query state/derived indexes reached their declared watermark. Explicit consistency modes, observable lag, safe rebuild, and a documented local writer policy are mandatory.

## Why

This reconciles canonical product terminology with the strongest existing durability/replay model while addressing F-002, F-003, F-004, F-010, and the health portion of F-013.

## Consequences

- WP-04 must specify checkpoint/watermark, dedupe/idempotency, and recovery semantics.
- WP-04 must separate canonical SQLite tables from disposable index/projection tables and prove replay equivalence.
- WP-12 must define supported multi-process behavior.
- WP-14/WP-15 own failure handling and status exposure.
- WP-17 must migrate v1.0.0 JSONL/SQLite without assuming a clean install or silently rewriting raw traces.

## Rejected Alternatives

- Treat stale/partial SQLite or any FTS/index/projection as authoritative.
- Hide ingestion scheduling/freshness from callers.
- Claim shared-writer safety without a proven coordination policy.
- Discard the canonical DOCX's SQLite metadata/lifecycle contract by relabeling every SQLite table as merely optional.
