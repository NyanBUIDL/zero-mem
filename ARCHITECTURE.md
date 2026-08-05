# Hermes External Zero-Mem Architecture

**Status:** M0 Policy & Architecture
**Authority:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`
**Scope:** Local-first External Zero-Mem sidecar for Hermes Agent

## 1. Responsibilities and boundaries

- **Hermes Agent** remains the orchestration, tool, task, final reasoning, and action layer.
- **Zero-Mem sidecar** captures events, redacts secrets, validates and classifies traces, appends canonical records, builds deterministic indexes, routes retrieval, calibrates evidence, and returns bounded evidence.
- **Final LLM** receives only the selected evidence and performs reasoning, decisions, and final response generation.
- **Obsidian Knowledge Workspace** is the human-readable audit, curation, and projection layer. It does not replace raw trace storage or act as the retrieval engine.

## 2. Canonical storage

- SQLite with WAL and FTS5 stores queryable trace metadata and relationships.
- JSONL stores append-only raw events per session/day.
- A separate local versioned artifact store holds large tool outputs, documents, diffs, and attachments.
- Retrieval indexes and Obsidian projections are rebuildable derived views and never source-of-record.

## 3. Data flow

```text
Hermes event
  -> event adapter
  -> secret/PII redaction or reject
  -> schema validation
  -> content hash and duplicate check
  -> append JSONL + SQLite metadata
  -> deterministic metadata/index updates
  -> bounded retrieval evidence
  -> Hermes final reasoning/action
```

Observation-only capture is the initial operating mode: captured memory is not automatically injected into prompts.

## 4. Trace and provenance decisions

Trace types are `user_statement`, `assistant_claim`, `tool_observation`, `system_event`,
`external_source`, `inference`, `decision`, `verified_state`, and `derived_summary`.
Every trace has an immutable ID, source, session/profile/project context when available,
time validity, lifecycle status, verification, confidence, sensitivity, retention, content
reference, and integrity hash. Raw updates append a new trace and link it with a replacement
or supersession relation.

Verified tool output, tests, user confirmation, and deterministic verification outrank assistant
self-report. An assistant claim never becomes an active fact without evidence.

## 5. Lifecycle and conflict decisions

Lifecycle states are `raw`, `observed`, `candidate`, `confirmed`, `active`, `superseded`,
`conflicted`, `archived`, and `deleted`. Conflicting claims remain visible with all source
traces and a resolution record. No conflict is silently overwritten. Active state is unique
per entity, scope, and state key unless the state explicitly permits multiple values.

## 6. Profile and access decisions

The default profile is `general-assistant` with global read access, profile-first ranking,
global fallback, bounded evidence, and no implicit cross-profile writes. Supported access modes
are `profile_first`, `explicit_union`, `isolated`, `global`, and `source_restricted`.
Cross-profile writes require explicit authorization and pass review/verification gates.

## 7. Security, retention, and governance decisions

Sensitivity classes are `public`, `internal`, `private`, and `secret`. Credentials, bearer
tokens, private keys, passwords, and OAuth secrets are redacted or rejected at the capture
boundary and never persisted. Redaction emits an audit event without the original value.
Retention classes are `temporary`, `session`, `persistent`, and `never_store`. Delete requests
cover raw traces, artifacts, indexes, and projections, using tombstones/versioning where needed.
Schema migrations are versioned and rollback-capable; write-back is audited.

## 8. M0 implementation choices and deferred choices

MVP uses Python 3.11+, SQLite WAL/FTS5, JSONL, local versioned files, and deterministic local
rules. The service boundary remains MCP or local HTTP/Unix socket. Vector index, embedding
model, and service framework remain replaceable adapters because the master specification lists
FAISS/Qdrant, BGE-M3/multilingual local embeddings, and FastAPI/local MCP as alternatives.
No full corpus ingestion, automatic memory injection, distributed infrastructure, or deep
Hermes-core modification is part of M0.

## 9. Rebuild and release gates

Canonical traces and artifacts must be sufficient to rebuild metadata indexes, search indexes,
graph/relationship views, and Obsidian projections. Before a release, run the benchmark and
security gates, verify provenance, check profile isolation, and record sanitized evidence in
project state.

## 10. Source mapping

- Master specification §§3–5: objectives, boundaries, architecture
- §§6–8: trace, lifecycle, profiles, provenance
- §§9–11: storage, capture, retrieval, routing
- §14: security, privacy, retention, governance
- §§16–18: stack, repository, build order, acceptance, roadmap
- §21 and Appendices A–F: defaults, first implementation, fixtures, checklists

This document is a derived architecture artifact. The master specification remains the highest
source of truth.
