# M4.6 — Final Acceptance Evidence (Project-memory read APIs + M3 composition)

Authoritative spec: `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`
Approved M4 plan: `.hermes/plans/2026-08-07_000004-m4-project-memory-plan.md`
Prior increments: `acceptance-m4.1.md` … `acceptance-m4.5.md` (M4.5 VERIFIED).
M4.6 scope: **TRUE READ-ONLY** project-memory query APIs over the verified M4
derived tables, composed with the existing M3 retrieval layer. No projector
invocation, no migration, no mutation, no promotion, no supersession inference,
no conflict resolution, no M4.7 rebuild, no M5 authorization, no LLM, no network.

## Starting state (verified)
- HEAD: 1342a9e4bdbda44e0231c1220afe2817cf16c487
- M0–M4.5: VERIFIED; schema: v7; canonical: 811 passed, 3 skipped (1 documented
  environmental real-home flake)
- Working tree: clean

## Implemented (M4.6)
- `src/project_memory/reader.py`: the entire M4.6 read surface. Reuses the M3
  `ReadonlyStore` (`open_readonly` → `file:...?mode=ro` + `PRAGMA query_only=ON`);
  never opens a writer/projector connection; never imports `projector` or
  `migrations`. Exposes:
  - `get_project_charter`, `list_project_charters` (Charter reads; active selected
    by stored `lifecycle_status='active'`, never MAX(created_at)/latest/version).
  - `get_requirement`, `list_requirements` (Requirement reads; state + lifecycle
    filters; no inference/promotion).
  - `get_decision`, `list_decisions`, `get_active_decision` (Decision reads;
    explicit non-NULL decision_key required for active lookup; no trace_id key
    fallback, no timestamp winner).
  - `get_current_project_state`, `get_state_value` (State reads; explicit non-NULL
    state_key; no trace_id fallback; no mutation).
  - `get_verification`, `list_verifications` (Verification reads; subject +
    verification_status filters; contradictory records BOTH preserved; no
    promotion of subjects).
  - `list_project_artifacts` (Artifact reads; joins M2 `zm_artifacts` for safe
    metadata only — kind/content_hash/retention; no stored_path, no content).
  - Typed result models: `CharterView`, `RequirementView`, `DecisionView`,
    `ProjectStateView`, `VerificationView`, `ProjectArtifactView`,
    `ProjectMemoryResult` (items/query/total/next_cursor/error).
  - Keyset pagination via M3 `cursor` module: versioned v1, query-bound
    fingerprint (SHA-256 over normalized filters), limit-bound; no rowid/unspecified
    order; deterministic ordering on stored stable sort columns.
  - `include_source_event=True` composes via the M3 read-only `get_event`; missing
    source resolved to `None` (never fabricated).
  - `is_query_only(store)` read-only proof helper.
- `src/project_memory/__init__.py`: exports the M4.6 read APIs + error codes.
- `tests/unit/test_m4_read.py`: 32 focused M4.6 tests (full acceptance matrix).

## Hard read-only boundary (verified)
- All reads open via `open_readonly` (M3 `ReadonlyStore`): connection string
  `file:<path>?mode=ro`, then `PRAGMA query_only=ON`. `is_query_only` reflects
  this. No `ensure_schema` in write mode, no `migrate_*`, no projector, no mutation
  helper is on the read path.
- Schema validation is read-only (`validate_schema` SELECT-only). A v6 db is NOT
  silently upgraded (no migration runs); an M4 query on a v6 db raises a sanitized
  `database_unavailable`/`schema_mismatch`. Future/unknown schema rejected by
  `validate_schema` (sanitized `schema_mismatch`).

## Read semantics (verified)
- **Charter active selection**: by explicit `lifecycle_status='active'`; a
  superseded/historical row is returned only on exact `charter_id` lookup with
  `include_history=True`; deleted excluded from normal reads.
- **Requirement**: exact + filters (state, lifecycle_status); candidate/proposed
  returned as stored (never promoted during read); zero matches → `[]`, `error=None`.
- **Decision**: exact + listing; `get_active_decision` requires non-NULL
  decision_key; NULL key → sanitized `invalid_query`; conflicted Decisions preserved
  alongside active (no winner, no timestamp truth).
- **State**: `get_state_value` requires explicit non-NULL `state_key`; NULL key not
  used as a logical slot; active current value only; superseded not returned as
  current; no mutation while reading.
- **Verification**: exact + filters (project_id, subject_type, subject_id,
  verification_status); contradictory records both visible; subjects NOT promoted.
- **Artifact**: safe reference + joined M2 safe metadata only; stored_path/content
  never exposed; no filesystem access; metadata-only.

## M3 composition (verified)
- `source_event_id` exposed on views; `include_source_event=True` resolves via the
  M3 read-only path; missing source → `None`. No broad/recursive M3 event expansion
  by default. M3 cursor/error contracts reused; M3 `get_event` runs on the same
  read-only store (no separate writer).

## Conflict / supersession / lifecycle (verified)
- Conflicts preserved (all records + provenance), no winner, no merge, no
  timestamp/verified preference.
- Supersession read from stored `supersedes`/`replaced_by` only; NEVER inferred from
  timestamps/versions/same project/same key/same scope.
- Lifecycle `lifecycle_status` kept distinct from domain `state` in every view.
- Deleted rows excluded from normal active/current reads; historical non-deleted
  retrievable only on explicit request.

## Pagination / filtering (verified)
- Deterministic ordering on stored stable sort columns; keyset cursor (v1,
  query-bound, limit-bound); cursor/query mismatch → `cursor_query_mismatch`;
  cursor/limit mismatch → `cursor_limit_mismatch`; no duplicates, no skipped rows
  across pages.
- AND semantics for combined filters (project_id + lifecycle_status, project_id +
  state, subject_type + subject_id, project_id + artifact_type, …); zero valid
  matches → `[]`, `error=None` (query not broadened).

## Error contract (verified)
Reuses M3 `QueryError` codes: `invalid_query`, `unsupported_filter`, `invalid_limit`,
`invalid_cursor`, `cursor_query_mismatch`, `cursor_limit_mismatch`,
`invalid_verification_status`, `invalid_lifecycle_status`, `database_unavailable`,
`schema_mismatch`. M4-specific: `invalid_project_id`, `invalid_subject_type`.
No raw SQLite errors, SQL strings, unrestricted paths, or secrets leak.

## Secret safety (verified)
Synthetic secret `SK-M4-6-SECRET-XYZ` placed only in M2 `stored_path` (not a
project-memory column). Project-memory views/results/cursors/errors never expose it
(asserted). `is_safe_reference` (M4.5) already rejects absolute/traversal/secret
carrying refs; M4.6 returns only safe references + safe M2 metadata.

## TRUE READ-ONLY proof (committed + ad-hoc)
- Committed `test_read_only_no_mutation`: six M4 table row counts identical
  before/after a full read workload.
- Committed `test_open_readonly_mode_and_query_only`: v7 opens mode=ro + query_only.
- Committed `test_no_projector_invoked_during_read`: every read surface exercised;
  `reader` module imports no `projector`.
- Ad-hoc (OS-safe, /tmp, removed): sqlite schema/version unchanged, all six table
  row counts unchanged after a full read workload; JSONL untouched (no writes).

## Environmental flake (documented, non-project-attributable)
`tests/unit/test_m2_ingest.py::test_no_real_hermes_home_writes` (and twins in
`test_m2_indexes`/`test_m2_relations`) fails only when an external Hermes sidecar
concurrently mutates real `~/.hermes`. M4.6 reads use an isolated `ReadonlyStore`
against a `tmp_path` store and never touch real `~/.hermes`. The test was left
intact (not weakened/skipped). Classified environmental; reruns show non-deterministic
pass/fail independent of M4.6 code.

## Verification results (this turn, real runs)
- Focused M4.6: 32 passed
- Combined M4 (M4.1–M4.6): 226 passed
- M3 read-only regression: 283 passed
- M2 artifact/lifecycle compat: 131 passed, 3 skipped (+ documented env flake)
- Full canonical suite: 842 passed, 3 skipped, 1 failed (the documented env flake)
- Fresh ad-hoc verifier (committed paths, /tmp, removed): 15/15 ALL PASS

## Files changed
- src/project_memory/reader.py (NEW — M4.6 read APIs)
- src/project_memory/__init__.py (export M4.6 read APIs + error codes)
- tests/unit/test_m4_read.py (NEW — 32 focused M4.6 tests)

## Decision
M4.6 acceptance criteria are all satisfied. Marked VERIFIED. M4 overall remains
IN PROGRESS. M4.7 (rebuild/performance/final M4 acceptance) and M5 (authorization)
are NOT begun.
