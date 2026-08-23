# Hermes External Zero-Mem

## Authority

The authoritative specification is `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` in this repository (frozen + hash-anchored per `docs/v1.3.2/decisions/ADR-V132-02-MASTER-SPEC-FREEZE.md`; enforced by `scripts/check_master_spec_hash.py` — a changed .docx hash blocks spec-touching work until the projection is reconciled). Read the relevant section before implementing a milestone. Generated summaries, assistant claims, and Obsidian projections never replace the master document or canonical evidence.

**Machine state precedence (D-02 Option A, v1.3.2):** `project-state.yaml` is the SINGLE machine state for current and future milestone/increment status. `implementation-plan.json` is a FROZEN HISTORICAL RECORD (`record_role: historical_record_frozen`, superseded by project-state.yaml) — do not update it; enforcement in `scripts/check_machine_state.py`. Verified bug-fix decisions are recorded in `docs/v1.3.2/decisions/` (see ADR-V132-01 for the is_verified enum alignment).

## Architecture constraints

- Hermes remains the orchestration and final-action layer.
- The sidecar captures, redacts, classifies, indexes, retrieves, and calibrates evidence.
- **v1.2+ canonical-storage refinement:** JSONL is the canonical append-only source of truth for memory events/traces. SQLite and indexes are derived/materialized state rebuildable from canonical sources. The master storage model remains SQLite + JSONL with this approved v1.2+ refinement. Versioned artifacts remain separately authoritative for their own contents; Obsidian is a human-facing rebuildable projection, not raw storage or the retrieval engine.
- The approved refinement is recorded in `docs/v1.2.0/SPEC-AMENDMENT-001-CANONICAL-MEMORY-EVENT-TRUTH.md` and `docs/v1.2.0/decisions/ADR-009-CANONICAL_MEMORY_EVENT_TRUTH_AND_DERIVED_STATE_BOUNDARY.md`. It is prospective for v1.2+ and does not rewrite v1.1 history.
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

## Defect registry (mandatory)

Every discovered defect (from audit, review, test, or inspection) MUST be registered in `docs/defects/DEFECT-REGISTRY.md` BEFORE any fix code is written. Fix order: registry entry → RED-first test → smallest fix → focused test → full suite → entry closed with verbatim evidence. Commits fixing a defect MUST reference the DEFECT-ID. Entries are append-only. See the registry for the full process and per-defect tech-stack guidance.

## Mandatory Git/GitHub governance

Before any Git or GitHub mutation, the agent **MUST** read [`docs/governance/GITHUB-POLICY.md`](docs/governance/GITHUB-POLICY.md). This includes commit, branch creation/update, merge, rebase, tag, push, release, hotfix, rollback, and remote modification. The policy is mandatory and its stop/escalation conditions apply.

## Required quality gates

Every module needs schema/migration coverage, unit and failure tests, structured logs/metrics, provenance output, security/redaction tests where content is handled, and runbook/rollback documentation. Do not claim completion without executable evidence.

## Prohibited shortcuts

Do not replace canonical stores with Obsidian, inject memory automatically before controlled-injection gates pass, ingest the full corpus before the basic pipeline is validated, silently resolve conflicts, delete raw traces/superseded decisions, or modify Hermes core deeply before the sidecar is proven.

## Current workflow

Planning and environment inspection are in progress. Do not begin milestone implementation until the user approves `implementation-plan.json` and the open questions recorded there.
