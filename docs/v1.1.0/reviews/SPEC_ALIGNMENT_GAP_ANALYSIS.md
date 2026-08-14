# V1.1.0 Canonical-Spec Alignment Gap Analysis

**Date:** 2026-08-14

**Scope:** Documentation/planning only. No source, test, schema, migration, configuration, CI, package, tag, or release mutation is authorized.

**Canonical source:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` at reconciliation point `78c4bb46b88b8ce9987c6882b24201e08b82a7f0` (SHA-256 `85b66cbfd380a756eba9266ec8021b331dfee232ab95bd030f287766ba628b9a`).

## Method

The audit compared the canonical DOCX requirement-by-requirement with `MASTER_PLAN.md`, ADR-001 through ADR-005, WP-00 through WP-19, historical M5/M6/M7/M9/M10 acceptance evidence, and exact-master implementation evidence. A planning gap is not an implementation finding and does not receive an `F-###` identifier.

## Gaps Before Correction

| ID | Requirement | Expected | Current planning before correction | Gap | Severity | Owning correction | Canonical source |
|---|---|---|---|---|---|---|---|
| GAP-001 | Local sidecar interface | A sidecar exposes retrieval through MCP or another approved local transport | WP-08 rejected mandatory MCP/local HTTP; WP-01 rejected a service boundary | Direct contradiction | BLOCKER | ADR-006, WP-08, WP-21 | DOCX §§4.2, 13, 16.1, 18 |
| GAP-002 | MCP capability names | Four MVP capabilities have stable contracts | No v1.1.0 contract for `zero_mem.search`, `zero_mem.get_trace`, `zero_mem.get_task_state`, `zero_mem.get_decisions` | Missing contract | BLOCKER | `INTERFACE_CONTRACT.md`, WP-08, WP-21 | DOCX §13.2 |
| GAP-003 | Hermes boundary | Hermes is a thin client/adapter of the sidecar/public API | WP-07 described hooks but not a complete transport/read/write/fallback matrix | Partial and ambiguous | HIGH | ADR-002, WP-07 | DOCX §§2.3, 5, 13.1 |
| GAP-004 | Agent-agnostic acceptance | A non-Hermes agent integrates without core changes | Python facade test existed, but local-service conformance and adapter replacement were absent | Partial | HIGH | ADR-001, WP-08, WP-21 | DOCX §§2.3, 3.1, 5.1 |
| GAP-005 | Profile-first global reads | Default reads are global, profile-first, and bounded | WP-12 excluded cross-profile retrieval by default | Direct contradiction | BLOCKER | ADR-007, WP-05, WP-20 | DOCX §§8.1–8.5, 12.5, 21.1 |
| GAP-006 | Access-mode semantics | Five modes have executable positive/negative/leakage semantics | Planning mentioned only fragments; no normative mode contract | Missing/partial | HIGH | `PROFILE_KNOWLEDGE_SPACE_CONTRACT.md`, WP-20 | DOCX §§8.3, 12.5, 17.1 |
| GAP-007 | Obsidian role | One Vault is the main human knowledge workspace and a rebuildable curated projection | MASTER_PLAN treated UI as a non-goal and had no Obsidian owner | Direct contradiction | BLOCKER | ADR-008, WP-22 | DOCX §§12.1–12.9, 18 |
| GAP-008 | Obsidian required views | System/Profile/Project homes, decisions, task state, candidate and conflict queues, knowledge-space index | No v1.1.0 ownership or release gate | Missing | HIGH | WP-22 | DOCX §12.7 |
| GAP-009 | Obsidian write-back | Edits enter a review/validation/conflict queue before an append-first canonical write | Historical M9 explicitly had zero write-back; planning did not add the missing lifecycle | Missing | BLOCKER | ADR-008, WP-22 | DOCX §12.6 |
| GAP-010 | Write-back failure matrix | Approved, rejected, duplicate, stale, concurrent, unauthorized, and malformed edits are testable | No acceptance matrix | Missing | HIGH | WP-22, WP-16 | DOCX §§7.2–7.3, 12.6, 14.4 |
| GAP-011 | Conflict taxonomy | Source, decision, profile, projection, concurrent, and stale conflicts remain visible | Conflict behavior was distributed and incomplete | Ambiguous ownership | HIGH | WP-14 owns canonical conflicts; WP-22 owns projection/write-back conflicts | DOCX §§7.2–7.3, 11.4–11.5, 12.6–12.7 |
| GAP-012 | Canonical storage terminology | Canonical trace is the composite SQLite+JSONL contract; indexes/projections remain rebuildable | ADR-003 and WPs called only JSONL canonical and all SQLite derived | Product/implementation terminology conflict | BLOCKER | ADR-003, WP-04, WP-17 | DOCX §§1, 4.1, 9.1–9.3, 16.1, 21.1 |
| GAP-013 | Provenance parity | Evidence and projections expose source, trace, time, profile/project, verification, state, and transformation | General provenance intent existed; API/projection field guarantees were incomplete | Partial | HIGH | WP-05, WP-08, WP-22 | DOCX §§6.2–6.3, 11.5, 12.3–12.4 |
| GAP-014 | Trace lifecycle | All canonical lifecycle states and append/supersede rules are owned and tested | Present in source/history but not complete in v1.1.0 planning | Partial | HIGH | WP-04, WP-14 | DOCX §§6–7 |
| GAP-015 | Capture coverage | Messages, tools, files, skills, tasks, sessions, and verification are captured or explicitly diagnosed as unavailable | WP-07 did not map canonical event classes to hooks/fallbacks | Partial | HIGH | WP-07 | DOCX §§2.2, 10.1–10.2 |
| GAP-016 | Dense/dual-view retrieval | Lexical and local dense paths compose with temporal/relational views | Vector/semantic behavior was only a non-goal/optional note | Partial | MEDIUM | WP-05, WP-16 | DOCX §§11.2, 16.1, 17.3 |
| GAP-017 | Retention/delete | `temporary`, `session`, `persistent`, `never_store` and cross-layer delete are planned | No primary v1.1.0 owner or acceptance gate | Missing | HIGH | WP-04, WP-14, WP-17 | DOCX §§14.3–14.4 |
| GAP-018 | Local API threat boundary | Local callers authenticate/authorize; local does not imply trusted | API planning did not define transport exposure and caller identity | Missing | HIGH | WP-21, WP-13 | DOCX §§8, 13, 14 |
| GAP-019 | Migration completeness | Existing JSONL/SQLite/config/profiles/Hermes/projection state and interruption/rollback are covered | WP-17 omitted Obsidian/write-back and access-mode contract migration | Partial | HIGH | WP-17 | DOCX §§9.3, 14.4, 16.4, 19 |
| GAP-020 | Spec traceability | Every normative requirement maps to plan, WP, acceptance, and release gate | Finding traceability existed; canonical requirement traceability did not | Missing | HIGH | `SPEC_TRACEABILITY.md`, WP-19 | DOCX full document |
| GAP-021 | Release gate | Canonical parity, MCP/API, profiles, Obsidian/write-back/conflicts are release blockers | WP-19 covered findings but not the full canonical requirement set | Partial | HIGH | WP-19 | DOCX §§17–18 and Appendix D–E |
| GAP-022 | WP quality | Every WP carries equivalent scope, negative/regression, security, performance, observability, rollback, and traceability | Existing WPs were strong but several cross-cutting fields were implicit | Partial | MEDIUM | MASTER_PLAN cross-cutting contract plus each affected WP | DOCX §16.4 |

## Ownership Rules After Correction

- WP-04 owns canonical persistence, canonical-to-derived freshness, rebuild, retention/delete mechanics.
- WP-05 owns retrieval algorithms and evidence ranking; WP-20 owns profile/knowledge-space policy semantics applied by retrieval.
- WP-08 owns transport-neutral public capabilities and data contracts.
- WP-21 owns MCP/local service bindings, local endpoint security, timeouts, and transport conformance.
- WP-07 owns only Hermes hook mapping, client lifecycle, and fail-open host behavior.
- WP-14 owns canonical lifecycle/conflict/recovery semantics; WP-22 owns projection and write-back conflicts.
- WP-22 owns Obsidian workspace, projection, review queue, approved write-back, and required pages.
- WP-16 owns shared executable validation; WP-19 owns the final canonical-parity go/no-go gate.

## Closure Rule

This gap analysis is closed only when every row has a mapped correction in `SPEC_TRACEABILITY.md`, the dependency graph is acyclic, all mandatory canonical requirements are `COVERED`, and the second-pass audit finds no `MISSING`, `PARTIAL`, or `CONFLICT` row.
