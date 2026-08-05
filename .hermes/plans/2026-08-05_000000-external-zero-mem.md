# External Zero-Mem Implementation Plan

> **For Hermes:** Execute milestone-by-milestone only after user approval; re-read the authoritative master specification section before each milestone.

**Goal:** Build the local-first External Zero-Mem sidecar for Hermes Agent with append-only provenance, deterministic retrieval, profile-aware bounded evidence, security gates, and rebuildable Obsidian projection.

**Architecture:** Hermes remains orchestration/final reasoning. A sidecar captures and redacts events, stores canonical SQLite/JSONL/artifacts, builds rebuildable indexes, routes and calibrates bounded evidence, and later integrates read-only MCP before controlled injection. Obsidian is a curated human workspace/projection, never raw source-of-record.

**Tech Stack:** Python 3.11+, SQLite WAL/FTS5, JSONL, local versioned artifact files, local retrieval/index adapters, MCP or local HTTP/Unix socket, Markdown Obsidian Vault. Embeddings and service framework remain open choices pending approval.

---

## Planning-only baseline

- Master specification read in full from the available DOCX; requested Markdown path is absent.
- Derived governance is in `AGENTS.md`.
- Machine-readable plan and open questions are in `implementation-plan.json`.
- Explicit state is in `project-state.yaml`.
- Contract-only baseline tests are in `tests/baseline/test_project_artifacts.py`.
- No milestone implementation, system-wide installation, full corpus ingestion, automatic injection, or deep Hermes-core change is permitted before approval.

## Milestones

1. **M0 Policy & Architecture:** architecture, taxonomy, provenance, lifecycle, sensitivity, retention, benchmark plan, runbooks.
2. **M1 Observation-only sidecar:** adapter, boundary redaction, validation, append capture, retry/dead-letter.
3. **M2 Canonical store:** SQLite/FTS5 schema, JSONL, artifacts, migrations, backup/restore.
4. **M3 Read-only retrieval:** FTS search, trace/task/decision queries, provenance envelope.
5. **M4 Query routing:** memory routes, bounded retry, insufficiency reporting.
6. **M5 Profile policy:** profile-first/global/union/isolated/restricted modes and write authorization.
7. **M6 MCP/Hermes read-only integration:** minimal stable tools and structured errors.
8. **M7 Controlled injection:** confidence/privacy gates, evidence budget, conflicts, kill switch.
9. **M8 Graph/temporal/calibration:** links, validity, closure and deterministic conflict handling.
10. **M9 Obsidian projection:** single Vault, idempotent metadata projection and review queue.
11. **M10 Corpus/operations:** staged corpus expansion, runbooks and release gates.

## Approval decisions required

- Confirm whether DOCX is the intended authoritative source or provide the missing `.md`.
- Select MVP service and vector choices, or approve conservative local adapter defaults.
- Define incomplete benchmark thresholds and local threat/key-management policy.
- Specify Hermes event adapter/MCP integration surface.
- Select the third initial profile: `quant-researcher` or `coin68-editor`.

## Verification approach

Each milestone must add failing tests first where applicable, implement the smallest increment, run focused and regression tests, run security/benchmark checks relevant to the milestone, record sanitized exact evidence, and update `project-state.yaml` only after acceptance passes. Checkpoint before destructive changes; no history rewrite or system-wide installation without explicit approval.

## Known risks

Secret leakage, assistant self-report becoming fact, stale/superseded state, profile scope leakage, over/under-retrieval, index corruption, projection loops, and premature graph/corpus complexity. Mitigations are encoded in the master specification and derived `AGENTS.md`.

**Current status:** awaiting user approval.
