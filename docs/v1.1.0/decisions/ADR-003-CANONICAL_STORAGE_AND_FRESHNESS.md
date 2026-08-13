# ADR-003: Canonical JSONL with Explicit Derived Freshness

**Status:** PROPOSED

**Reconciliation:** RETAINED at exact master 78c4bb46b88b8ce9987c6882b24201e08b82a7f0; the one-commit post-tag delta does not change this ADR's code evidence. The decision remains proposed pending maintainer review.

## Context

V1.0.0 treats sanitized JSONL as canonical and SQLite/FTS as rebuildable, but capture and derived ingestion have separate lifecycles. Startup and ingest also materialize/re-read history, and canonical writes have only process-local coordination.

## Decision

Retain canonical JSONL unless WP-04 evidence justifies a separately approved change. Define durable incremental progress, explicit consistency modes, observable lag, safe rebuild, and a documented local writer policy. Derived SQLite/FTS remains rebuildable.

## Why

This preserves the strongest existing durability model while addressing F-002, F-003, F-004, F-010, and the health portion of F-013.

## Consequences

- WP-04 must specify checkpoint/watermark, dedupe/idempotency, and recovery semantics.
- WP-12 must define supported multi-process behavior.
- WP-14/WP-15 own failure handling and status exposure.

## Rejected Alternatives

- Treat stale derived SQLite as authoritative.
- Hide ingestion scheduling/freshness from callers.
- Claim shared-writer safety without a proven coordination policy.
