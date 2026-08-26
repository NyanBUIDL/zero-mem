# Hermes External Zero-Mem Architecture

**Status:** Cross-version foundation with v1.6.0 overlay
**Authority:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`
**Scope:** Local-first External Zero-Mem sidecar for Hermes Agent

## 1. Responsibilities and boundaries

- **Hermes Agent** remains the orchestration, tool, task, final reasoning, and action layer.
- **Zero-Mem sidecar** captures events, redacts secrets, validates and classifies traces, appends canonical records, builds deterministic indexes, routes retrieval, calibrates evidence, and returns bounded evidence.
- **Final LLM** receives only the selected evidence and performs reasoning, decisions, and final response generation.
- **Obsidian Knowledge Workspace** is the human-readable audit, curation, and projection layer. It does not replace raw trace storage or act as the retrieval engine.

## 2. Canonical storage

- JSONL is the append-only canonical source of truth for memory events/traces, including event identity, ordering/sequence, historical provenance, lifecycle events, and artifact references.
- SQLite with WAL and FTS5 stores derived/materialized query state, metadata, relationships, checkpoints, watermarks, and projection metadata. It is rebuildable from canonical sources and is not the canonical event log.
- A separate local versioned artifact store holds large tool outputs, documents, diffs, and attachments. It may be authoritative for the contents of a specific artifact version, but it is not the canonical memory-event stream.
- Retrieval indexes, graph/vector projections, corpus indexes, materialized views, and Obsidian projections are rebuildable derived views and never source-of-record.
- This v1.2+ boundary is governed by `docs/v1.2.0/SPEC-AMENDMENT-001-CANONICAL-MEMORY-EVENT-TRUTH.md` and accepted ADR-009. Verified v1.1 history remains historical and is not rewritten.

## 3. Recovery and projection data flow

```text
Hermes event
  -> event adapter
  -> secret/PII redaction or reject
  -> schema validation
  -> content hash and duplicate check
  -> canonical JSONL append + durability confirmation
  -> derived SQLite projection / checkpoint / watermark update
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

## 11. M1 Architecture Decision Records

### ADR-M1-001 — JSONL raw trace source of record

M1 uses a versioned, append-only JSONL raw event store as the authoritative raw trace stream.
This is not disposable temporary storage. M2 adds SQLite metadata, lifecycle state,
relationships, and indexes above the JSONL source of record. M1 exposes a stable project-owned
storage interface: `append(event)`, `contains(event_id)`, and `write_dead_letter(event, error)`.
M1 does not create a competing canonical store.

### ADR-M1-002 — Verified-hook coverage only

M1 integrates only Hermes lifecycle/plugin hooks directly verified during planning. Supported
classes are session lifecycle, pre/post tool, LLM/API lifecycle where used for observation,
subagent, and verified task/Kanban lifecycle events. File-operation, skill-usage, and generic
task hooks are deferred coverage because no generic verified hook was found. M1 must declare
unsupported classes rather than claim them captured, and must not modify installed Hermes core.
The >=99% capture threshold applies only to the declared supported event classes in the
controlled harness.

### ADR-M1-003 — Opt-in project-local observer bridge

The integration is a project-local, independently enabled/disabled observer bridge based on
verified lifecycle hooks. It is not the shell-hook subprocess bridge and does not modify the
installed Hermes source or real `~/.hermes` state. Capture failures are fail-open with respect
to Hermes control flow: they cannot alter tool results, prompts, model context, or actions.

### ADR-M1-004 — Project-owned redaction boundary

M1 owns deterministic redaction rules derived from the M0 schema and policy files. Incoming
payloads are copied, normalized into an isolated structure, redacted or rejected, hashed only
after sanitization, validated, and then persisted. Original secrets must not occur in raw JSONL,
dead-letter JSONL, redaction audits, logs, exceptions, temporary files, or test snapshots.
Installed Hermes private redaction modules are compatibility references only, not runtime
dependencies.

### ADR-M1-005 — Bounded retry and sanitized dead-letter

Storage receives three total attempts with 50 ms then 200 ms backoff and a 500 ms maximum
event deadline. There is no automatic dead-letter replay in M1. Sanitized dead-letter records
are written to `data/dead-letter/YYYY-MM-DD.jsonl` and contain event ID, available trace ID,
failure class, timestamp, attempt count, and sanitized diagnostic message. If both normal and
dead-letter persistence fail, only a sanitized local diagnostic is emitted and the failure is
not raised into Hermes.

### ADR-M1-006 — Explicit identity metadata

`project_id` resolves only from `HERMES_PROJECT_ID`, then project-local bridge configuration,
then null/`unassigned`. `profile_id` follows the same explicit-value-or-null rule. Neither is
inferred from cwd, repository name, session text, prompt content, or unrelated Hermes state.

### ADR-M1-007 — M1 secret-scan and observer-only acceptance scope

M1 secret scanning covers raw capture, dead-letter output, redaction audits, logs, exceptions,
temporary verification artifacts, and test snapshots. SQLite/index scanning is deferred to M2.
“No prompt injection” means observer non-interference: M1 must not modify, append, rewrite, or
inject content into prompts, messages, tool arguments, model context, or Hermes actions; it is
not a prompt-injection classifier.

This document is a derived architecture artifact. The master specification remains the highest
source of truth.

## 12. v1.6.0 Multi-KS overlay

The v1.6.0 implementation refines event scope without changing the canonical
boundary above. New canonical envelopes may carry an optional ordered
`knowledge_space_ids` list. Legacy singular `knowledge_space_id` remains readable.

Derived schema v13 adds `zm_event_spaces(event_id, knowledge_space_id)` as the
complete event-to-space junction. Structured and FTS authorization query this
junction with correlated `EXISTS` predicates; a missing membership fails closed.
`zm_meta.knowledge_space_id` retains only PRIMARY-KS for backward compatibility
and singular graph/temporal consumers. Projections expose the full list, while
corpus units remain singular in v1.6.0.

The current version architecture, module map and evidence authority are indexed
under [`docs/v1.6.0/`](../v1.6.0/README.md). The DOCX and `MASTER-SPEC.md`
projection are not hand-rewritten by this overlay.
