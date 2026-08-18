# ADR-008: Obsidian Projection and Reviewed Write-Back

**Status:** PROPOSED

## Canonical Source

- `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` §§5.1–5.2, 9.1–9.3, 12.1–12.9, 14.4, 18 stage 9, and 21.1.
- Exact-master M9 projection code/runbook and M9.5/M9.6 acceptance evidence, which verify a safe one-way derived projection but explicitly exclude write-back.

## Context

The canonical specification makes Obsidian the main human-facing workspace and requires controlled bidirectional synchronization. Exact master has a deterministic, path-safe, idempotent, read-only projection with human-edit conflict preservation, but no review queue or canonical write-back. Existing v1.1.0 planning had no owner for closing that gap.

## Decision

V1.1.0 retains one Vault and one managed subtree. Obsidian remains a rebuildable projection, never the raw event store or retrieval engine. A user edit cannot directly update raw traces or derived SQLite tables. It becomes a typed write-back candidate, passes schema, path, sensitivity, authorization, staleness, duplicate, and conflict checks, receives an approved/rejected decision with provenance, and only an approved candidate appends a canonical write-back/decision trace. Projection then regenerates from canonical state.

The required views, metadata, triggers, idempotency, stale/delete behavior, review states, and conflict rules are normative in `OBSIDIAN_WORKSPACE_CONTRACT.md`.

## Consequences

- WP-22 owns projection, review queue, and write-back orchestration.
- WP-14 owns canonical conflict and recovery semantics; WP-22 translates projection/edit conflicts into that contract.
- WP-04 owns the append-first canonical persistence boundary.
- Existing M9 human-ownership protections are compatibility invariants and may not be weakened.

## Rejected Alternatives

- Treating Vault Markdown as the only canonical database.
- Direct overwrite of raw traces or current verified state from a note edit.
- Silent winner selection when human, source, or concurrent state conflicts.
- Replacing the managed-subtree/three-signal ownership safety model.
