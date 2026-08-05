# Hermes External Zero-Mem

## Authority

The authoritative specification is `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` in this repository. Read the relevant section before implementing a milestone. Generated summaries, assistant claims, and Obsidian projections never replace the master document or canonical evidence.

## Architecture constraints

- Hermes remains the orchestration and final-action layer.
- The sidecar captures, redacts, classifies, indexes, retrieves, and calibrates evidence.
- SQLite + JSONL are canonical trace storage; artifacts are separate and versioned.
- Obsidian is a human-facing Knowledge Workspace and curated, rebuildable projection—not raw storage or the retrieval engine.
- Memory operations use deterministic/local mechanisms by default and make zero LLM calls; only final reasoning/response may use an LLM.
- Preserve raw traces append-first with provenance; updates create linked traces, never silent overwrite.
- Verified state outranks assistant self-report. Unverified claims must not become active facts.
- Reads are global by default but profile-first and evidence-bounded; isolated/source-restricted modes must not leak scope.
- Cross-profile writes require explicit authorization and review/verification gates.
- Redact or reject secrets before persistence; never persist raw secrets.
- Conflicts remain visible with source traces and resolution records.
- Indexes and projections must be rebuildable from canonical traces, artifacts, and approved write-back records.

## Delivery protocol

1. Inspect the repository and verified state.
2. Read the applicable master-spec section and state the change scope.
3. Implement one smallest complete milestone only.
4. Run unit, integration, security, benchmark, and acceptance checks applicable to it.
5. Record exact changed files and sanitized command evidence.
6. Update project state only after acceptance criteria pass.
7. Create a checkpoint before destructive changes; never install system-wide packages or perform destructive operations without explicit approval.

## Required quality gates

Every module needs schema/migration coverage, unit and failure tests, structured logs/metrics, provenance output, security/redaction tests where content is handled, and runbook/rollback documentation. Do not claim completion without executable evidence.

## Prohibited shortcuts

Do not replace canonical stores with Obsidian, inject memory automatically before controlled-injection gates pass, ingest the full corpus before the basic pipeline is validated, silently resolve conflicts, delete raw traces/superseded decisions, or modify Hermes core deeply before the sidecar is proven.

## Current workflow

Planning and environment inspection are in progress. Do not begin milestone implementation until the user approves `implementation-plan.json` and the open questions recorded there.
