# M10 Owner Review — plan-m10.md

**Status:** OWNER REVIEW COMPLETE — plan APPROVED by owner (review verdict APPROVE_WITH_CHANGES; three clarifications folded in before approval).
**Reviewed artifact:** `plan-m10.md` (now APPROVED / IMPLEMENTATION CONTRACT).
**Authority:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`, `AGENTS.md`, `ARCHITECTURE.md`, `project-state.yaml`, `implementation-plan.json`, and the VERIFIED M1–M9 source tree.

This document performs no implementation, no schema change, no ingestion, no M10 start.

---

## A. Verdict

**APPROVE WITH CHANGES**

The plan is architecturally sound and extends Zero-Mem cleanly rather than creating a second parallel system. Three plan-text clarifications (two of them HIGH-severity guardrails drawn from the M9.6 secret-leak lesson) must be folded into the approved plan before M10.1 implementation. None require design redesign; they are explicitness fixes.

---

## B. Architecture Fit — PASS (with 2 required clarifications)

The plan reuses the actual load-bearing contracts:
- **M5** `AuthorizedReadService` as the sole authorization authority (wired from M10.1, not later).
- **M6.6** resource_type isolation (two distinct `corpus_*` types).
- **M7** `EvidenceSet` + `eligibility.py` (corpus added as a bounded, DATA-only channel).
- **M8** closed `RelationType`/`EntityType` vocabulary, `graph_access.py` (authorization-first, bounded).
- **M9** Obsidian projection (M10.8 reuses engine/manifest/ownership/path-safety).
- **M1** fail-closed redactor; **M2** idempotent ingest + checkpoint + FTS discipline.

**Required clarifications (BLOCKING for the approved plan text, not for the design):**
1. **Authorization enforcement must be explicit.** Every corpus read path (M10.5 planner, M10.6 graph reads, M10.8 projection) MUST route through `AuthorizedReadService` — never a direct SQLite/FTS/JSONL query. The plan says "authorization-first" but must state this as a hard invariant with a static/regression gate (mirroring M8.3's "no graph-derived auth").
2. **Corpus redaction must reuse M1 fail-closed RULES on extracted text.** The M1 redactor is envelope-shaped; corpus extraction is a NEW text surface. The plan's "reuse M1 redactor" must become an explicit `src/corpus/redact.py` adapter that applies the SAME M1 rules (and the M9 non-disableable baseline + extend-never-replace discipline) to extracted corpus text. This directly prevents a repeat of the M9.6 V9 leak class.

---

## C. Memory-Corpus Boundary — PASS

The plan cleanly separates memory (M1–M9 JSONL event stream) from corpus (content-addressed blob store + `corpus_sources.jsonl`). Document contents are never dumped into memory JSONL. The logical flow

```
External Sources -> Corpus ingestion/storage/indexing -> Authorized retrieval -> EvidenceSet -> Hermes
```

coexists with the existing M1–M9 memory path; the two meet only at the authorization + evidence layer. Canonical corpus storage is distinct from canonical memory storage. No blocking issue.

---

## D. Universal-Domain Requirement — PASS

No finance/PDF-specific core logic. The 600 finance/quant PDFs are explicitly a generic stress test. `domain` is a free optional metadata field, filter-only, with unknown domain a valid normal case (required by the task). The `FormatAdapter` boundary lets DOCX/HTML/code/log/CSV/JSON be added as pure adapters with no core change. No blocking issue.

---

## E. Increment Review (8 proposed)

| Inc | Verdict | Issues / recommended changes |
| --- | --- | --- |
| **M10.1** Registry + Auth | PASS | Necessary, correct order (auth from day one), right-sized, no schema, no deps, zero-LLM. Add the §B.1 auth-enforcement invariant explicitly. |
| **M10.2** Multi-format ingest + extraction | PASS | Right-sized (PDF+TXT first). PDF is an optional extra (absence → `unsupported_format`, never crash). Add the §B.2 corpus-redaction adapter explicitly. Do NOT over-promise "figure" extraction — scope to page boundaries / figure metadata. |
| **M10.3** Normalization + Dedup + Versioning | PASS (with trim) | "Near-dedup" is correctly exact-hash over normalized text (deterministic). **Trim `unit_kind`**: keep a COARSE structural set only (section, paragraph, table, code, heading, list, figure, metadata). Defer the semantic subtypes (definition/fact/claim/reference) to optional M10.6 enrichment — they are over-modeling at this stage (see §M). |
| **M10.4** Derived storage + `migrate_10` | PASS | Additive derived v10 tables, `down()`-safe, v1–v9 untouched. Reuses M2.5 FTS + M8 vocabulary. Justification sound (see §F). |
| **M10.5** Hybrid retrieval + EvidenceSet | PASS | Reuses M3/M5/M6/M7/M8; `corpus_evidence` as bounded DATA-only channel. Must state the §B.1 invariant and specify M7.4 injection handles `corpus_evidence` with the same DATA-only escaping as `m8_metadata` (never as authorized memory fact). |
| **M10.6** Graph + optional enrichment | PASS (highest risk) | Reuses M8 graph; enrichment optional + fail-closed. Keep graph MINIMAL and deterministic in M10.6; AI enrichment must stay optional and never become required for basic access/rebuild. |
| **M10.7** Rollout + benchmark + acceptance | PASS | 600-PDF stress test; benchmark categories listed. Keep "no unsupported performance numbers promised." |
| **M10.8** Optional Obsidian projection | PASS (owner scope) | Clearly separated, reuses M9 (ownership three-signal, manifest, path safety, `internal` ceiling, secret-never-projects). May be deferred to a separate milestone without blocking M10 core. |

**Coherence:** the 8 increments are already coherent and correctly ordered. No merge/split required. Two trims only: M10.3 `unit_kind` scope, and explicit §B invariants.

---

## F. Schema Recommendation

**Classification: B — Deliberate v10 migration at a specific increment (M10.4).**

- M10.1–M10.3: **stay v9** (canonical = JSONL + blobs; derived units in-memory/derived JSONL). No migration.
- M10.4: **`migrate_10` (v9 → v10), derived corpus tables only**, additive, `down()` returns to v9, v1–v9 tables/JSONL/blobs never altered.

**Why v10 is justified (not premature):**
- The v1–v9 tables are the *memory* substrate (events, M4 project memory, M8 graph/temporal). Corpus units are a distinct derived class; mixing them would blur canonical/derived and risk M6.6 bleed.
- `migrate_10` writes **zero** canonical data — canonical corpus truth remains blob store + `corpus_sources.jsonl`.
- Precedent: M8.1 `migrate_9` is exactly this shape (additive derived, down-safe).

**Alternative considered (non-blocking):** a separate `corpus.db` sqlite file would give even stronger memory/corpus isolation and zero chance of M6.6 bleed. Acceptable, but the same-store additive `migrate_10` matches repo precedent and is lower-friction. Either is safe; the plan's choice is fine.

---

## G. Dependency Recommendation

**Mandatory new dependencies: NONE.**

- Core (M10.1–M10.5, M10.7): stdlib + existing repo deps only.
- PDF parser: **optional extra** (`extras_require`); absence → `unsupported_format`. Pinned, local-only, no network, permissive license.
- DOCX: optional extra (`python-docx`). HTML: stdlib `html.parser` (optional `html2text` extra).
- Semantic/vector (M10.5/6 optional): local-only embeddings, never mandatory, never canonical. **No commercial API/cloud mandated.**

This matches M0's "vector index, embedding model, service framework remain replaceable adapters."

---

## H. Retrieval / Authorization Review — PASS

Corpus retrieval integrates with the existing stack: M5 authorization (sole authority, before any ranking), M3 FTS pattern, M6 MCP read-only, M7 router/eligibility, M8 graph/temporal. "Embed everything" is explicitly avoided; the query planner selects paths deterministically. Hidden/unauthorized corpus resources have zero influence on ranking/snippets/evidence (enforced via §B.1). Results surface through the existing bounded `EvidenceSet` (DATA-only). No parallel unrestricted RAG path.

---

## I. Zero-LLM Review — PASS

All core operations are deterministic and LLM-free: hashing, unchanged-file detection, ingestion orchestration, parser-based extraction, normalization, dedup, versioning, provenance, metadata indexing, FTS, lifecycle, authorization (M5), deterministic rebuild. AI/LLM enrichment (M10.6) is optional, non-blocking, writes derived metadata only, and degrades gracefully. No paid LLM is required for normal ingestion/retrieval/rebuild.

---

## J. Performance / Scale Review — PASS

600 PDFs are routine, not an architectural limit. Path to ~10k then ~100k documents via index-backed access (scope indexes, `content_hash` index, FTS, `unit_kind`, lifecycle). Incremental re-ingest skips unchanged content via hash check. Benchmark categories (first ingest, unchanged ingest, one changed source, exact lookup, FTS, hybrid, graph/entity, rebuild, memory, disk, evidence construction) are complete and appropriate. No obvious full-corpus O(N) routine query. No premature optimization.

---

## K. Portability Review — PASS

Explicit/config-only corpus root (Q3 Option A discipline, matching `BridgeConfig`/`ProjectionConfig`); no `/home/<user>` in code; optional Obsidian path remains runtime config; corpus paths configurable; local/offline operation preserved; no mandatory commercial/cloud API; all derived indexes rebuildable on another machine. Packaging itself is explicitly out of M10 (future: VERIFIED → local run → stabilize → release engineering → clean-machine install → backup/restore → final audit → v1).

---

## L. Owner Decisions (6 → 4 remaining after review)

| Q | Decision | Resolvable from repo/spec? | Recommendation | Downstream consequence |
| --- | --- | --- | --- | --- |
| **Q1** | `corpus_source` + `corpus_unit` (2 types) vs one `corpus` type | No — genuine isolation/simplicity tradeoff | **A (two types)** — mandated by M6.6 fidelity | Cleaner grants; slightly larger M5 enum (mirrored to M8 with existing equality test) |
| **Q2** | Semantic/vector retrieval include (optional) or defer | No — scope/timeline product call | **A (optional local-only adapter)** | Hybrid retrieval fulfilled; no cloud/API; absence safe |
| **Q3** | Corpus storage root: dedicated config root vs reuse `capture_root` | **Yes — resolved by repo convention** (explicit-only root is the established pattern) | **A** (dedicated configurable root) — treat as decided | One env var/config key; zero code change; portable |
| **Q4** | `domain` free vs closed vocabulary | **Yes — resolved by task spec** ("unknown domain must be valid") | **A (free optional)** — treat as decided | Filter-only; unknown domain always valid |
| **Q5** | Obsidian projection in-M10 (M10.8) or separate milestone | No — scope/timeline call | **A (M10.8 reusing M9), but deferrable without blocking core** | Curated projection; never corpus-canonical |
| **Q6** | First adapter set: PDF+TXT vs all formats | No — scope call | **A (PDF+TXT first)** | Universal adapter interface proven; others are pure adapter additions |

**After review, Q3 and Q4 are resolvable by existing repo convention / task spec and should be treated as decided (Option A). Genuine owner decisions remaining: Q1, Q2, Q5, Q6 (4).**

---

## M. Blocking Changes Before Approval

Three plan-text clarifications must be present in the approved `plan-m10.md`:

1. **(HIGH, §B.1)** State as a hard invariant: every corpus read routes through `AuthorizedReadService`; no direct SQLite/FTS/JSONL access bypasses M5. Add a static/regression guard.
2. **(HIGH, §B.2)** Add an explicit `src/corpus/redact.py` adapter that applies the SAME M1 fail-closed redaction rules (plus M9 non-disableable baseline, extend-never-replace) to extracted corpus text. Prevents a repeat of the M9.6 secret-leak class on the new corpus text surface.
3. **(MEDIUM)** Trim M10.3 `unit_kind` to a coarse structural set; move semantic subtypes (definition/fact/claim/reference) to optional M10.6 enrichment (over-modeling guard).

---

## N. Non-Blocking Improvements

- Specify M7.4 injection handling for `corpus_evidence` (same DATA-only escaping as `m8_metadata`; never as authorized memory fact).
- Consider a separate `corpus.db` as an alternative to same-store `migrate_10` (stronger isolation) — current same-store choice is acceptable.
- Keep M10.6 knowledge graph minimal and deterministic; treat AI enrichment strictly as optional.
- M10.8 may be deferred to a separate milestone without blocking M10 core acceptance.

---

## O. Recommended Final M10 Increment Structure

Keep the existing 8 increments (already coherent). Apply only the trims above:

1. **M10.1** Corpus Source Registry + Authorization Boundary (+ §B.1 invariant)
2. **M10.2** Multi-format Ingestion + Structural Extraction (+ §B.2 redaction adapter; PDF+TXT first; conservative figure scope)
3. **M10.3** Normalization + Dedup + Versioning (**coarse `unit_kind` only**)
4. **M10.4** Derived Storage + Indexing (`migrate_10`, v9→v10, derived-only)
5. **M10.5** Universal / Hybrid Retrieval + EvidenceSet Integration (+ M7.4 DATA-only handling)
6. **M10.6** Knowledge Graph + Optional Enrichment (**minimal deterministic graph; AI optional**)
7. **M10.7** Large-Corpus Rollout + Benchmark + Final Acceptance
8. **M10.8** (optional/deferrable) Curated Obsidian Corpus Projection reusing M9

---

## P. Final Owner Recommendation

**Approve `plan-m10.md` after folding in the three §M clarifications.** The plan preserves every load-bearing M1–M9 contract, wraps corpus under M5 authorization from the first increment, keeps canonical corpus storage distinct from memory JSONL, defers `migrate_10` until the canonical model is frozen (M8.1 precedent), adds no mandatory dependency, treats the 600 PDFs as a generic stress test, and reuses M9 for any Obsidian projection. Resolve Q3/Q4 by convention/spec; confirm Q1/Q2/Q5/Q6. **Do NOT begin M10.1 until the owner approves the (clarified) plan.**
